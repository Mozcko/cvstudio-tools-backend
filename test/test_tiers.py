"""Plan levels (free / sprint / active / lifetime) and the free weekly AI allowance."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

import create_promo
from src.api.dependencies import FREE_AI_KEY, IMPORT_KEY
from src.core.config import settings
from src.models.ai_request import AIRequest
from src.models.promo import PromoCode
from src.models.user import User
from src.scripts import upgrade_user as upgrade_script
from src.services.pro import PLAN_GRANTS, apply_expiry, grant_pro, is_premium, plan_of, revoke_grant
from test.test_ai import fake_ai, rewrite_body  # noqa: F401  (fixture)
from test.test_billing_promo import checkout_event, send_webhook, stripe_event  # noqa: F401  (fixture)

NOW = datetime(2026, 1, 1, tzinfo=UTC)
USER = "user_test_1"
REWRITE = "/api/v1/ai/rewrite"


def days(n):
    return NOW + timedelta(days=n)


def new_user(**fields):
    return User(id="u", is_pro=False, **fields)


async def reload(db, user_id=USER):
    result = await db.execute(select(User).where(User.id == user_id).execution_options(populate_existing=True))
    return result.scalar_one_or_none()


# ── Levels ────────────────────────────────────────────────────────────────────


def test_plans_on_sale():
    assert PLAN_GRANTS == {"7": (7, False), "30": (30, True), "lifetime": (None, True)}


def test_sprint_is_pro_but_not_premium():
    user = new_user()
    grant_pro(user, 7, NOW)
    assert (plan_of(user, NOW), is_premium(user, NOW)) == ("sprint", False)
    assert user.premium_until is None


def test_active_hunt_is_premium_for_its_days():
    user = new_user()
    grant_pro(user, 30, NOW, premium=True)
    assert (plan_of(user, NOW), is_premium(user, NOW)) == ("active", True)
    assert user.premium_until == user.pro_expires_at == days(30)
    # Once the days have passed the user is free again
    later = days(31)
    assert apply_expiry(user, later)
    assert (plan_of(user, later), user.premium_until) == ("free", None)


def test_lifetime_is_premium_without_a_date():
    user = new_user()
    grant_pro(user, None, NOW, premium=True)
    assert (plan_of(user, NOW), is_premium(user, NOW), user.premium_until) == ("lifetime", True, None)
    # A timed purchase on top changes nothing
    grant_pro(user, 30, NOW, premium=True)
    assert (plan_of(user, NOW), user.pro_expires_at, user.premium_until) == ("lifetime", None, None)


def test_buying_lifetime_clears_the_premium_date():
    user = new_user()
    grant_pro(user, 30, NOW, premium=True)
    grant_pro(user, None, NOW, premium=True)
    assert (user.pro_expires_at, user.premium_until, is_premium(user, NOW)) == (None, None, True)


def test_sprint_on_top_of_active_extends_pro_only():
    user = new_user()
    grant_pro(user, 30, NOW, premium=True)
    grant_pro(user, 7, NOW)
    assert (user.pro_expires_at, user.premium_until) == (days(37), days(30))
    # Premium for the first 30 days, plain Pro for the last 7
    assert plan_of(user, days(29)) == "active"
    assert plan_of(user, days(33)) == "sprint"
    assert is_premium(user, days(33)) is False


def test_active_on_top_of_sprint_starts_premium_now():
    user = new_user()
    grant_pro(user, 7, NOW)
    grant_pro(user, 30, NOW, premium=True)
    assert (user.pro_expires_at, user.premium_until) == (days(37), days(30))


def test_two_active_purchases_stack():
    user = new_user()
    grant_pro(user, 30, NOW, premium=True)
    grant_pro(user, 30, days(10), premium=True)
    assert user.premium_until == user.pro_expires_at == days(60)


def test_premium_never_outlives_pro():
    user = new_user(premium_until=days(10))
    assert is_premium(user, NOW) is False
    assert apply_expiry(user, NOW)
    assert user.premium_until is None


def test_refund_takes_back_the_premium_days_too():
    user = new_user()
    grant_pro(user, 7, NOW)
    grant_pro(user, 30, NOW, premium=True)
    revoke_grant(user, 30, NOW, premium=True)
    assert (user.pro_expires_at, user.premium_until, plan_of(user, NOW)) == (days(7), None, "sprint")


def test_refunding_a_sprint_leaves_premium_alone():
    user = new_user()
    grant_pro(user, 30, NOW, premium=True)
    grant_pro(user, 7, NOW)
    revoke_grant(user, 7, NOW)
    assert (user.pro_expires_at, user.premium_until) == (days(30), days(30))


def test_refunding_lifetime_removes_everything():
    user = new_user()
    grant_pro(user, None, NOW, premium=True)
    revoke_grant(user, None, NOW, premium=True)
    assert (user.is_pro, user.premium_until, plan_of(user, NOW)) == (False, None, "free")


# ── Through Stripe, promo codes and the scripts ───────────────────────────────


@pytest.mark.parametrize(
    ("plan", "expected", "premium"), [("7", "sprint", False), ("30", "active", True), ("lifetime", "lifetime", True)]
)
async def test_checkout_sets_the_level(client, db, stripe_event, plan, expected, premium):  # noqa: F811
    stripe_event["event"] = checkout_event(plan=plan)
    assert (await send_webhook(client, stripe_event)).status_code == 200

    profile = (await client.get("/api/v1/users/me")).json()
    assert (profile["plan"], profile["is_premium"], profile["is_pro"]) == (expected, premium, True)
    assert (profile["premium_until"] is not None) == (plan == "30")


async def test_refund_of_active_hunt_removes_premium(client, db, stripe_event):  # noqa: F811
    stripe_event["event"] = checkout_event(session_id="cs_sprint", plan="7", payment_intent="pi_sprint")
    await send_webhook(client, stripe_event)
    stripe_event["event"] = checkout_event(session_id="cs_active", plan="30", payment_intent="pi_active")
    await send_webhook(client, stripe_event)
    assert (await client.get("/api/v1/users/me")).json()["plan"] == "active"

    stripe_event["event"] = {
        "type": "charge.refunded",
        "data": {"object": {"id": "ch_1", "payment_intent": "pi_active", "refunded": True}},
    }
    assert (await send_webhook(client, stripe_event)).status_code == 200

    profile = (await client.get("/api/v1/users/me")).json()
    assert (profile["plan"], profile["is_premium"], profile["premium_until"]) == ("sprint", False, None)


@pytest.mark.parametrize(
    ("granted_days", "premium", "expected"), [(30, True, "active"), (30, False, "sprint"), (9999, False, "lifetime")]
)
async def test_promo_codes_carry_their_level(client, db, granted_days, premium, expected):
    db.add(PromoCode(code="CODE", max_uses=5, granted_days=granted_days, premium=premium))
    await db.commit()

    assert (await client.post("/api/v1/promo/redeem", json={"code": "CODE"})).status_code == 200

    assert (await client.get("/api/v1/users/me")).json()["plan"] == expected


async def test_scripts_can_grant_premium(db, session_factory, monkeypatch):
    monkeypatch.setattr(upgrade_script, "AsyncSessionLocal", session_factory)
    monkeypatch.setattr(create_promo, "AsyncSessionLocal", session_factory)

    assert await upgrade_script.upgrade_user(user_id="user_a", days=30, premium=True) == 0
    assert await upgrade_script.upgrade_user(user_id="user_b", days=30) == 0
    assert is_premium(await reload(db, "user_a")) is True
    assert is_premium(await reload(db, "user_b")) is False

    await create_promo.create_promo_code("VIP", 1, 30, premium=True)
    await create_promo.create_promo_code("PLAIN", 1, 30)
    codes = {c.code: c.premium for c in (await db.execute(select(PromoCode))).scalars()}
    assert codes == {"VIP": True, "PLAIN": False}


# ── Free weekly allowance ─────────────────────────────────────────────────────


async def rows(db, key=None):
    query = select(func.count()).select_from(AIRequest)
    if key:
        query = query.where(AIRequest.endpoint == key)
    return (await db.execute(query)).scalar_one()


async def test_free_user_can_enhance_and_optimize_a_few_times_a_week(client, db, fake_ai):  # noqa: F811
    remaining = []
    for action in ("enhance", "optimize", "enhance"):
        body = rewrite_body(action=action, job_description="Python role")
        response = await client.post(REWRITE, json=body)
        assert response.status_code == 200
        remaining.append(response.json()["free_remaining"])
    assert remaining == [2, 1, 0]

    blocked = await client.post(REWRITE, json=rewrite_body())
    assert blocked.status_code == 403
    assert "Free AI limit" in blocked.json()["detail"]
    assert len(fake_ai.calls) == 3

    usage = (await client.get("/api/v1/users/me")).json()["usage"]["free_ai"]
    assert (usage["limit"], usage["remaining"]) == (3, 0)
    assert datetime.fromisoformat(usage["resets_at"]) > datetime.now(UTC) + timedelta(days=6)


async def test_the_allowance_comes_back_after_a_week(client, db, fake_ai):  # noqa: F811
    await client.get("/api/v1/users/me")
    old = datetime.now(UTC) - timedelta(days=7, minutes=1)
    recent = datetime.now(UTC) - timedelta(days=2)
    db.add_all(
        [
            AIRequest(user_id=USER, endpoint=FREE_AI_KEY, created_at=old),
            AIRequest(user_id=USER, endpoint=FREE_AI_KEY, created_at=old),
            AIRequest(user_id=USER, endpoint=FREE_AI_KEY, created_at=recent),
        ]
    )
    await db.commit()

    usage = (await client.get("/api/v1/users/me")).json()["usage"]["free_ai"]
    assert (usage["remaining"], usage["resets_at"]) == (2, None)
    response = await client.post(REWRITE, json=rewrite_body())
    assert (response.status_code, response.json()["free_remaining"]) == (200, 1)


async def test_failed_and_invalid_requests_do_not_use_the_allowance(client, db, monkeypatch):
    async def boom(*args, **kwargs):
        raise RuntimeError("provider down")

    monkeypatch.setattr("src.api.routers.ai.rewrite_cv", boom)

    assert (await client.post(REWRITE, json=rewrite_body())).status_code == 502
    assert (await client.post(REWRITE, json=rewrite_body(action="optimize"))).status_code == 422
    assert (await client.post(REWRITE, json={"action": "enhance"})).status_code == 422
    assert await rows(db) == 0


async def test_free_allowance_can_be_switched_off(client, fake_ai, monkeypatch):  # noqa: F811
    monkeypatch.setattr(settings, "FREE_AI_WEEKLY_LIMIT", 0)
    assert (await client.post(REWRITE, json=rewrite_body())).status_code == 403
    assert fake_ai.calls == []


async def test_other_ai_tools_stay_pro_only(client, fake_ai):  # noqa: F811
    cv = rewrite_body()["cv_content"]
    for path, body in [
        ("/api/v1/ai/ats", {"cv_content": cv, "job_description": "x"}),
        ("/api/v1/ai/cover-letter", {"cv_content": cv, "job_description": "x"}),
        ("/api/v1/ai/improve", {"text": "{}", "context": "Action: enhance, Lang: en, JD: "}),
    ]:
        assert (await client.post(path, json=body)).status_code == 403, path
    assert fake_ai.calls == []


async def test_pro_use_is_not_counted_as_free_use(client, db, fake_ai):  # noqa: F811
    db.add(User(id=USER, is_pro=True))
    await db.commit()

    for _ in range(4):
        response = await client.post(REWRITE, json=rewrite_body(action="translate"))
        assert (response.status_code, response.json()["free_remaining"]) == (200, None)
    assert await rows(db, FREE_AI_KEY) == 0
    assert await rows(db, REWRITE) == 4

    # If Pro lapses, the weekly allowance is still whole
    user = await reload(db)
    user.is_pro = False
    await db.commit()
    assert (await client.get("/api/v1/users/me")).json()["usage"]["free_ai"]["remaining"] == 3


async def test_profile_counts_free_imports(client, db):
    await client.get("/api/v1/users/me")
    db.add(AIRequest(user_id=USER, endpoint=IMPORT_KEY))
    await db.commit()

    usage = (await client.get("/api/v1/users/me")).json()["usage"]
    assert usage["free_imports"] == {"limit": 2, "remaining": 1, "resets_at": None}


async def test_premium_gate(db):
    from fastapi import HTTPException

    from src.api.dependencies import require_premium

    sprint, active = new_user(), new_user()
    grant_pro(sprint, 7)
    grant_pro(active, 30, premium=True)

    assert await require_premium(active) is active
    for user in (new_user(), sprint):
        with pytest.raises(HTTPException) as error:
            await require_premium(user)
        assert error.value.status_code == 403
        assert "Active Hunt" in error.value.detail
