"""Recruiter subscriptions: plans, the free trial, quota, and staying in step with Stripe."""

from datetime import UTC, datetime, timedelta

import pytest
import stripe
from sqlalchemy import func, select

from src.core.config import settings
from src.models.ai_request import AIRequest
from src.models.recruiter import RecruiterSubscription
from src.models.user import User
from src.scripts import grant_recruiter as grant_script
from src.services.recruiter_plans import (
    USAGE_KEY,
    entitlement,
    release_evaluation,
    reserve_evaluation,
)
from test.stripe_helpers import signed_stripe_request

API = "/api/v1"
USER = "user_test_1"
STARTER, PRO = "price_starter_test", "price_pro_test"
NOW = int(datetime.now(UTC).timestamp())
DAY = 86400


@pytest.fixture(autouse=True)
def prices(monkeypatch):
    monkeypatch.setattr(settings, "STRIPE_PRICE_RECRUITER_STARTER", STARTER)
    monkeypatch.setattr(settings, "STRIPE_PRICE_RECRUITER_PRO", PRO)


def subscription(
    status="active",
    price=STARTER,
    sub_id="sub_1",
    user=USER,
    start=NOW - DAY,
    end=NOW + 29 * DAY,
    on_item=False,
    **extra,
):
    """A Stripe subscription object, with the period where the given API version puts it."""
    item = {"price": {"id": price}}
    body = {"id": sub_id, "customer": "cus_1", "status": status, "metadata": {"user_id": user} if user else {}}
    (item if on_item else body).update({"current_period_start": start, "current_period_end": end})
    body["items"] = {"data": [item]}
    body.update(extra)
    return body


async def send(client, event_type, obj, created=None):
    event = {"type": event_type, "created": created or int(datetime.now(UTC).timestamp()), "data": {"object": obj}}
    body, headers = signed_stripe_request(event)
    response = await client.post(f"{API}/webhooks/stripe", content=body, headers=headers)
    assert response.status_code == 200, response.text
    return response


async def status_of(client):
    response = await client.get(f"{API}/recruiter/me")
    assert response.status_code == 200, response.text
    return response.json()


async def get_sub(db, user_id=USER):
    query = select(RecruiterSubscription).where(RecruiterSubscription.user_id == user_id)
    return (await db.execute(query.execution_options(populate_existing=True))).scalar_one_or_none()


async def the_user(db, user_id=USER):
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if not user:
        user = User(id=user_id, is_pro=False)
        db.add(user)
        await db.commit()
    return user


async def use(db, count, user_id=USER, at=None):
    await the_user(db, user_id)
    db.add_all(
        [AIRequest(user_id=user_id, endpoint=USAGE_KEY, created_at=at or datetime.now(UTC)) for _ in range(count)]
    )
    await db.commit()


# ── Free trial ────────────────────────────────────────────────────────────────


async def test_a_new_user_is_on_the_trial(client):
    assert await status_of(client) == {
        "plan": "trial",
        "status": "trial",
        "can_evaluate": True,
        "used": 0,
        "limit": 10,
        "remaining": 10,
        "period_end": None,
        "retention_days": 90,
        "reason": None,
        "has_billing": False,
    }


async def test_the_trial_runs_out_once(client, db, monkeypatch):
    monkeypatch.setattr(settings, "RECRUITER_TRIAL_CVS", 2)
    user = await the_user(db)

    first = await reserve_evaluation(db, user)
    await reserve_evaluation(db, user)
    with pytest.raises(Exception) as refused:
        await reserve_evaluation(db, user)
    assert refused.value.status_code == 403
    assert "free trial" in refused.value.detail

    state = await status_of(client)
    assert (state["can_evaluate"], state["used"], state["remaining"]) == (False, 2, 0)
    assert "free trial" in state["reason"]

    # A failed evaluation is given back
    await release_evaluation(db, first)
    assert (await status_of(client))["remaining"] == 1


async def test_other_ai_usage_does_not_touch_the_trial(client, db):
    await the_user(db)
    db.add_all([AIRequest(user_id=USER, endpoint="/api/v1/ai/rewrite") for _ in range(5)])
    await db.commit()
    assert (await status_of(client))["used"] == 0


# ── Subscribing ───────────────────────────────────────────────────────────────


async def test_checkout_starts_a_subscription_that_carries_the_user(client, monkeypatch):
    monkeypatch.setattr(settings, "STRIPE_API_KEY", "sk_test_x")
    seen = {}

    def create(**kwargs):
        seen.update(kwargs)
        return stripe.checkout.Session.construct_from({"url": "https://checkout.stripe.test/x"}, "sk_test_x")

    monkeypatch.setattr(stripe.checkout.Session, "create", create)

    response = await client.post(f"{API}/recruiter/billing/checkout", json={"plan": "pro"})

    assert response.json() == {"url": "https://checkout.stripe.test/x"}
    assert seen["mode"] == "subscription"
    assert seen["line_items"] == [{"price": PRO, "quantity": 1}]
    assert seen["subscription_data"] == {"metadata": {"user_id": USER}}
    assert seen["client_reference_id"] == USER
    assert seen["success_url"].endswith("/app/recruiter?subscribed=1")
    assert "customer" not in seen


@pytest.mark.parametrize("body", [{"plan": "enterprise"}, {"plan": "lifetime"}, {}])
async def test_only_the_two_priced_plans_can_be_bought(client, body):
    assert (await client.post(f"{API}/recruiter/billing/checkout", json=body)).status_code == 422


async def test_checkout_when_not_configured_or_failing(client, monkeypatch):
    assert (await client.post(f"{API}/recruiter/billing/checkout", json={"plan": "starter"})).status_code == 503

    monkeypatch.setattr(settings, "STRIPE_API_KEY", "sk_test_x")

    def boom(**kwargs):
        raise RuntimeError("stripe secret detail")

    monkeypatch.setattr(stripe.checkout.Session, "create", boom)
    failed = await client.post(f"{API}/recruiter/billing/checkout", json={"plan": "starter"})
    assert failed.status_code == 502
    assert "secret detail" not in failed.text


async def test_a_running_subscription_cannot_be_bought_twice(client, db, monkeypatch):
    monkeypatch.setattr(settings, "STRIPE_API_KEY", "sk_test_x")
    await send(client, "customer.subscription.created", subscription())

    again = await client.post(f"{API}/recruiter/billing/checkout", json={"plan": "pro"})

    assert again.status_code == 409
    assert "manage subscription" in again.json()["detail"]


async def test_a_returning_customer_keeps_their_stripe_customer(client, db, monkeypatch):
    monkeypatch.setattr(settings, "STRIPE_API_KEY", "sk_test_x")
    await send(client, "customer.subscription.created", subscription())
    await send(client, "customer.subscription.deleted", subscription(status="canceled"))
    seen = {}

    def create(**kwargs):
        seen.update(kwargs)
        return stripe.checkout.Session.construct_from({"url": "https://x"}, "sk_test_x")

    monkeypatch.setattr(stripe.checkout.Session, "create", create)

    assert (await client.post(f"{API}/recruiter/billing/checkout", json={"plan": "starter"})).status_code == 200
    assert seen["customer"] == "cus_1"


# ── What Stripe tells us ──────────────────────────────────────────────────────


@pytest.mark.parametrize(("price", "plan", "limit"), [(STARTER, "starter", 100), (PRO, "pro", 1000)])
async def test_subscription_created(client, db, price, plan, limit):
    await send(client, "customer.subscription.created", subscription(price=price))

    state = await status_of(client)
    assert (state["plan"], state["status"], state["can_evaluate"]) == (plan, "active", True)
    assert (state["used"], state["limit"], state["remaining"], state["has_billing"]) == (0, limit, limit, True)
    assert state["period_end"] is not None
    sub = await get_sub(db)
    assert (sub.stripe_customer_id, sub.stripe_subscription_id) == ("cus_1", "sub_1")


async def test_the_period_is_read_wherever_stripe_puts_it(client, db):
    await send(client, "customer.subscription.created", subscription(on_item=True))
    sub = await get_sub(db)
    assert sub.current_period_start is not None and sub.current_period_end > datetime.now(UTC)


async def test_a_subscription_for_a_user_we_have_not_seen_yet(client, db):
    await send(client, "customer.subscription.created", subscription(user="user_brand_new"))
    assert (await get_sub(db, "user_brand_new")).plan == "starter"
    assert (await db.execute(select(User).where(User.id == "user_brand_new"))).scalar_one().is_pro is False


async def test_nothing_is_granted_before_the_first_payment(client, db):
    await send(client, "customer.subscription.created", subscription(status="incomplete"))
    assert await get_sub(db) is None
    assert (await status_of(client))["plan"] == "trial"


async def test_events_we_cannot_use_are_ignored(client, db):
    await send(client, "customer.subscription.created", subscription(price="price_of_something_else"))
    await send(client, "customer.subscription.created", subscription(user=None))
    await send(client, "customer.subscription.created", {"status": "active"})
    # The end of a subscription we never knew must not cost the user their trial
    await send(client, "customer.subscription.deleted", subscription(status="canceled"))

    assert (await db.execute(select(func.count()).select_from(RecruiterSubscription))).scalar_one() == 0
    assert (await status_of(client))["plan"] == "trial"


async def test_the_same_event_twice_changes_nothing(client, db):
    event = subscription()
    await send(client, "customer.subscription.created", event, created=NOW)
    await send(client, "customer.subscription.created", event, created=NOW)
    assert (await db.execute(select(func.count()).select_from(RecruiterSubscription))).scalar_one() == 1


async def test_upgrade_renewal_and_usage_per_period(client, db):
    await send(client, "customer.subscription.created", subscription(), created=NOW - 10)
    await use(db, 40, at=datetime.now(UTC) - timedelta(hours=1))
    assert (await status_of(client))["remaining"] == 60

    # Upgrade in the portal: more room in the same period
    await send(client, "customer.subscription.updated", subscription(price=PRO), created=NOW - 5)
    state = await status_of(client)
    assert (state["plan"], state["used"], state["remaining"]) == ("pro", 40, 960)

    # Renewal: a new period starts, and with it a fresh allowance
    renewed = subscription(price=PRO, start=NOW - 60, end=NOW + 30 * DAY)
    await send(client, "customer.subscription.updated", renewed, created=NOW + 2)
    state = await status_of(client)
    assert (state["used"], state["remaining"]) == (0, 1000)


async def test_the_monthly_allowance_runs_out(client, db):
    await send(client, "customer.subscription.created", subscription())
    await use(db, 100)

    state = await status_of(client)
    assert (state["can_evaluate"], state["remaining"]) == (False, 0)
    assert "allowance" in state["reason"]
    with pytest.raises(Exception) as refused:
        await reserve_evaluation(db, await the_user(db))
    assert refused.value.status_code == 403


async def test_a_failed_payment_pauses_evaluating_until_it_is_fixed(client, db):
    await send(client, "customer.subscription.created", subscription(), created=NOW - 10)

    await send(client, "customer.subscription.updated", subscription(status="past_due"), created=NOW - 5)
    state = await status_of(client)
    assert (state["status"], state["can_evaluate"], state["plan"]) == ("past_due", False, "starter")
    assert "payment" in state["reason"]

    await send(client, "customer.subscription.updated", subscription(status="active"), created=NOW)
    assert (await status_of(client))["can_evaluate"] is True


async def test_cancelling_keeps_access_until_the_period_ends(client, db):
    await send(client, "customer.subscription.created", subscription(), created=NOW - 10)

    # Cancelled in the portal: Stripe keeps it active until the end of what was paid
    await send(client, "customer.subscription.updated", subscription(cancel_at_period_end=True), created=NOW - 5)
    assert (await status_of(client))["can_evaluate"] is True

    # The period is over
    await send(client, "customer.subscription.deleted", subscription(status="canceled"), created=NOW)
    state = await status_of(client)
    assert (state["plan"], state["status"], state["can_evaluate"]) == ("starter", "canceled", False)
    assert (state["limit"], state["remaining"]) == (0, 0)
    assert "ended" in state["reason"]
    # They can still reach billing (invoices), and the trial does not come back
    assert state["has_billing"] is True


async def test_a_period_that_ran_out_without_news_from_stripe_does_not_grant_access(client, db):
    await send(client, "customer.subscription.created", subscription(start=NOW - 40 * DAY, end=NOW - 10 * DAY))
    assert (await status_of(client))["can_evaluate"] is False


async def test_late_and_stale_events_do_not_undo_newer_ones(client, db):
    await send(client, "customer.subscription.created", subscription(), created=NOW - 100)
    await send(client, "customer.subscription.deleted", subscription(status="canceled"), created=NOW - 10)

    # An older "active" arrives after the cancellation
    await send(client, "customer.subscription.updated", subscription(status="active"), created=NOW - 50)
    assert (await get_sub(db)).status == "canceled"

    # A new subscription after that is accepted...
    await send(client, "customer.subscription.created", subscription(sub_id="sub_2", price=PRO), created=NOW)
    assert ((await get_sub(db)).status, (await get_sub(db)).stripe_subscription_id) == ("active", "sub_2")
    # ...and late news about the old one does not disturb it
    await send(client, "customer.subscription.deleted", subscription(status="canceled"), created=NOW + 5)
    assert ((await get_sub(db)).status, (await get_sub(db)).plan) == ("active", "pro")


async def test_buying_a_recruiter_plan_does_not_make_someone_pro_and_vice_versa(client, db):
    await send(client, "customer.subscription.created", subscription())
    profile = (await client.get(f"{API}/users/me")).json()
    assert (profile["is_pro"], profile["plan"]) == (False, "free")

    # A job-seeker pass, bought the usual way, grants no recruiter plan
    checkout = {
        "id": "cs_pass",
        "mode": "payment",
        "payment_status": "paid",
        "client_reference_id": "user_seeker",
        "metadata": {"plan_duration": "lifetime"},
    }
    await send(client, "checkout.session.completed", checkout)
    assert await get_sub(db, "user_seeker") is None


async def test_the_subscription_checkout_itself_grants_nothing(client, db):
    session = {
        "id": "cs_sub",
        "mode": "subscription",
        "payment_status": "paid",
        "client_reference_id": USER,
        "subscription": "sub_1",
        "metadata": {"kind": "recruiter", "user_id": USER},
    }
    await send(client, "checkout.session.completed", session)

    assert await get_sub(db) is None
    user = (await db.execute(select(User).where(User.id == USER))).scalar_one_or_none()
    assert user is None or user.is_pro is False


# ── Managing ──────────────────────────────────────────────────────────────────


async def test_portal(client, db, monkeypatch):
    assert (await client.post(f"{API}/recruiter/billing/portal")).status_code == 404

    await send(client, "customer.subscription.created", subscription())
    assert (await client.post(f"{API}/recruiter/billing/portal")).status_code == 503

    monkeypatch.setattr(settings, "STRIPE_API_KEY", "sk_test_x")
    seen = {}

    def create(**kwargs):
        seen.update(kwargs)
        return stripe.billing_portal.Session.construct_from({"url": "https://billing.stripe.test/p"}, "sk_test_x")

    monkeypatch.setattr(stripe.billing_portal.Session, "create", create)
    opened = await client.post(f"{API}/recruiter/billing/portal")
    assert opened.json() == {"url": "https://billing.stripe.test/p"}
    assert seen["customer"] == "cus_1" and seen["return_url"].endswith("/app/recruiter")

    def boom(**kwargs):
        raise RuntimeError("stripe secret detail")

    monkeypatch.setattr(stripe.billing_portal.Session, "create", boom)
    failed = await client.post(f"{API}/recruiter/billing/portal")
    assert failed.status_code == 502 and "secret" not in failed.text


# ── Enterprise, agreed by hand ────────────────────────────────────────────────


@pytest.fixture
def script_db(session_factory, monkeypatch):
    monkeypatch.setattr(grant_script, "AsyncSessionLocal", session_factory)


async def test_enterprise_is_unlimited_and_keeps_data_longer(client, db, script_db):
    assert await grant_script.grant_recruiter(USER, retention_days=365) == 0
    await use(db, 5000)

    state = await status_of(client)
    assert (state["plan"], state["status"], state["can_evaluate"]) == ("enterprise", "active", True)
    assert (state["limit"], state["remaining"], state["retention_days"]) == (None, None, 365)
    assert (state["period_end"], state["has_billing"]) == (None, False)


async def test_enterprise_with_an_agreed_quota_counts_a_rolling_month(client, db, script_db):
    await grant_script.grant_recruiter(USER, quota=50, months=12)
    await use(db, 30, at=datetime.now(UTC) - timedelta(days=40))
    await use(db, 20)

    state = await status_of(client)
    assert (state["used"], state["limit"], state["remaining"]) == (20, 50, 30)
    assert state["period_end"] is not None


async def test_grant_script_refuses_to_override_stripe_and_can_revoke(client, db, script_db, capsys):
    await send(client, "customer.subscription.created", subscription())
    assert await grant_script.grant_recruiter(USER) == 1
    assert "Stripe" in capsys.readouterr().out
    assert (await get_sub(db)).plan == "starter"

    assert await grant_script.grant_recruiter("user_ent") == 0
    assert await grant_script.grant_recruiter("user_ent", revoke=True) == 0
    assert (await get_sub(db, "user_ent")).status == "canceled"
    assert await grant_script.grant_recruiter("user_nobody", revoke=True) == 1


async def test_entitlement_of_an_expired_manual_plan(db, script_db):
    await grant_script.grant_recruiter(USER, months=1)
    sub = await get_sub(db)
    sub.current_period_end = datetime.now(UTC) - timedelta(days=1)
    await db.commit()

    allowed = await entitlement(db, await the_user(db))
    assert (allowed.can_evaluate, allowed.status) == (False, "canceled")


async def test_deleting_the_account_removes_the_subscription(client, db):
    await send(client, "customer.subscription.created", subscription())
    await db.delete((await db.execute(select(User).where(User.id == USER))).scalar_one())
    await db.commit()
    assert await get_sub(db) is None
