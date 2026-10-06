"""Failure paths and branches that the feature tests do not reach."""

import json
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from jwt.exceptions import PyJWKClientConnectionError
from sqlalchemy import func, select
from svix.webhooks import Webhook

from src.api import dependencies
from src.core import security
from src.core.config import settings
from src.models.payment import Payment
from src.models.user import User
from src.services.ai import ats, base, cover_letter, rewrite
from src.services.ai.base import AINotConfiguredError, AIResponseError
from src.utils.sanitizer import mask_cv_pii, restore_cv_pii
from test.stripe_helpers import signed_stripe_request

USER = "user_test_1"
CV = {"personal": {"name": "Jane", "email": "jane@example.com", "socials": []}}


class FakeOpenAI:
    def __init__(self, reply):
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))
        self.reply = reply

    async def _create(self, **kwargs):
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=self.reply))])


async def make_pro(db, user_id=USER):
    db.add(User(id=user_id, is_pro=True))
    await db.commit()


def clerk_signed(body: str):
    msg_id, timestamp = "msg_1", datetime.now(UTC)
    return {
        "svix-id": msg_id,
        "svix-timestamp": str(int(timestamp.timestamp())),
        "svix-signature": Webhook(settings.CLERK_WEBHOOK_SECRET).sign(msg_id, timestamp, body),
        "content-type": "application/json",
    }


# ── Authentication ────────────────────────────────────────────────────────────


def test_jwks_client_points_at_the_issuer(monkeypatch):
    monkeypatch.setattr(security, "_jwks_client", None)
    client = security._get_jwks_client()
    assert client.uri == f"{settings.CLERK_ISSUER}/.well-known/jwks.json"
    assert security._get_jwks_client() is client  # cached


def test_unreachable_identity_provider_is_503(monkeypatch):
    def unreachable(token):
        raise PyJWKClientConnectionError("down")

    monkeypatch.setattr(security, "_get_jwks_client", lambda: SimpleNamespace(get_signing_key_from_jwt=unreachable))

    with pytest.raises(HTTPException) as exc:
        security.get_current_user_id(HTTPAuthorizationCredentials(scheme="Bearer", credentials="x.y.z"))
    assert exc.value.status_code == 503


async def test_requests_without_a_token_are_rejected(session_factory):
    from httpx import ASGITransport, AsyncClient

    from src.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as anonymous:
        for path in ("/api/v1/users/me", "/api/v1/cvs/"):
            assert (await anonymous.get(path)).status_code in (401, 403)
        assert (await anonymous.get("/health")).json()["status"] == "healthy"


async def test_default_get_db_yields_a_session():
    generator = dependencies.get_db()
    session = await anext(generator)
    assert session.is_active
    await generator.aclose()


# ── CVs ───────────────────────────────────────────────────────────────────────


async def test_cv_unknown_and_malformed_ids(client):
    missing = uuid4()
    assert (await client.get(f"/api/v1/cvs/{missing}")).status_code == 404
    assert (await client.put(f"/api/v1/cvs/{missing}", json={"title": "x"})).status_code == 404
    assert (await client.delete(f"/api/v1/cvs/{missing}")).status_code == 404
    assert (await client.get("/api/v1/cvs/not-a-uuid")).status_code == 422


async def test_cv_partial_update_keeps_other_fields(client):
    created = (
        await client.post("/api/v1/cvs/", json={"title": "T", "content": {"a": 1}, "language": "EN", "theme": "basic"})
    ).json()

    updated = (await client.put(f"/api/v1/cvs/{created['id']}", json={"language": "PT", "content": {"b": 2}})).json()

    assert updated["language"] == "PT" and updated["content"] == {"b": 2}
    assert updated["title"] == "T" and updated["theme"] == "basic"


# ── AI ────────────────────────────────────────────────────────────────────────


def test_ai_client_requires_a_key(monkeypatch):
    monkeypatch.setattr(base, "_client", None)
    monkeypatch.setattr(settings, "OPENAI_API_KEY", None)
    with pytest.raises(AINotConfiguredError):
        base.get_ai_client()

    monkeypatch.setattr(settings, "OPENAI_API_KEY", "sk-test")
    client, model = base.get_ai_client()
    assert model == settings.OPENAI_MODEL
    assert base.get_ai_client()[0] is client  # reused


async def test_ai_without_provider_key_is_503(client, db, monkeypatch):
    await make_pro(db)
    monkeypatch.setattr(settings, "OPENAI_API_KEY", None)

    response = await client.post(
        "/api/v1/ai/rewrite", json={"cv_content": CV, "action": "enhance", "target_language": "en"}
    )

    assert response.status_code == 503


@pytest.mark.parametrize("reply", ["not json", "[1, 2]", ""])
async def test_unusable_model_output_is_rejected(monkeypatch, reply):
    fake = (FakeOpenAI(reply), "m")
    for module in (rewrite, ats, cover_letter):
        monkeypatch.setattr(module, "get_ai_client", lambda: fake)

    with pytest.raises(AIResponseError):
        await rewrite.rewrite_cv(CV, "enhance", "en")
    with pytest.raises(AIResponseError):
        await ats.simulate_ats(CV, "job")
    if reply == "":
        with pytest.raises(AIResponseError):
            await cover_letter.generate_cover_letter(CV, "job")


async def test_cover_letter_and_ats_without_language(monkeypatch):
    monkeypatch.setattr(cover_letter, "get_ai_client", lambda: (FakeOpenAI("Dear team,"), "m"))
    monkeypatch.setattr(ats, "get_ai_client", lambda: (FakeOpenAI('{"final_ats_score": 1}'), "m"))

    letter = await cover_letter.generate_cover_letter({"personal": {}}, "job")
    assert letter.startswith("[Your Name]\n")
    assert await ats.simulate_ats(CV, "job") == {"final_ats_score": 1}


async def test_legacy_improve_rejects_unknown_actions(client, db):
    await make_pro(db)
    response = await client.post(
        "/api/v1/ai/improve", json={"text": json.dumps(CV), "context": "Action: destroy, Lang: en, JD: "}
    )
    assert response.status_code == 400


async def test_request_size_limits(client, db):
    await make_pro(db)
    huge = {"personal": {"summary": "x" * 200_001}}
    response = await client.post(
        "/api/v1/ai/rewrite", json={"cv_content": huge, "action": "enhance", "target_language": "en"}
    )
    assert response.status_code == 422


async def test_rate_limit_can_be_disabled(client, db, monkeypatch):
    await make_pro(db)
    monkeypatch.setattr(settings, "AI_RATE_LIMIT_PER_HOUR", 0)
    monkeypatch.setattr(settings, "AI_RATE_LIMIT_PER_DAY", 0)
    monkeypatch.setattr(ats, "get_ai_client", lambda: (FakeOpenAI("{}"), "m"))

    for _ in range(3):
        response = await client.post("/api/v1/ai/ats", json={"cv_content": CV, "job_description": "job"})
        assert response.status_code == 200


# ── Sanitizer ────────────────────────────────────────────────────────────────


def test_restore_handles_missing_pieces():
    original = {"personal": {"email": "a@b.c", "socials": [{"url": "https://x"}]}}

    assert restore_cv_pii({}, {"personal": {"email": "z"}}) == {"personal": {"email": "z"}}
    assert restore_cv_pii(original, {"summary": "no personal"}) == {"summary": "no personal"}

    # A redaction marker for a field the user never had is dropped, not kept as text
    restored = restore_cv_pii(original, {"personal": {"email": "[REDACTED_PII]", "phone": "[REDACTED_PII]"}})
    assert restored["personal"]["email"] == "a@b.c"
    assert "phone" not in restored["personal"]
    assert restored["personal"]["socials"] == original["personal"]["socials"]


def test_mask_ignores_malformed_socials():
    cv = {"personal": {"email": "", "socials": ["oops", {"network": "x"}]}}
    assert mask_cv_pii(cv) == cv
    assert mask_cv_pii({"personal": {"socials": "nope"}}) == {"personal": {"socials": "nope"}}


# ── Stripe ───────────────────────────────────────────────────────────────────


@pytest.fixture
def stripe_event():
    return {}


async def post_stripe(client, holder):
    body, headers = signed_stripe_request(holder["event"])
    return await client.post("/api/v1/webhooks/stripe", content=body, headers=headers)


def session_event(**overrides):
    session = {
        "id": "cs_1",
        "payment_status": "paid",
        "client_reference_id": USER,
        "payment_intent": "pi_1",
        "metadata": {"plan_duration": "30"},
    }
    session.update(overrides)
    return {"type": "checkout.session.completed", "data": {"object": session}}


async def test_stripe_webhook_configuration_and_payload_errors(client, stripe_event, monkeypatch):
    # Correctly signed, but not an event we can read
    for garbage in ("this is not json", "[1, 2, 3]", '{"type": "x", "data": {"object": "nope"}}'):
        stripe_event["event"] = garbage
        assert (await post_stripe(client, stripe_event)).status_code == 400

    # Sign while the secret exists, then send to a server that has none configured
    body, headers = signed_stripe_request(session_event())
    monkeypatch.setattr(settings, "STRIPE_WEBHOOK_SECRET", None)
    assert (await client.post("/api/v1/webhooks/stripe", content=body, headers=headers)).status_code == 500


@pytest.mark.parametrize(
    "overrides",
    [
        {"metadata": {"plan_duration": "365"}},  # unknown plan
        {"client_reference_id": None},  # nobody to credit
        {"id": None},
    ],
)
async def test_unusable_checkout_sessions_are_ignored(client, db, stripe_event, overrides):
    stripe_event["event"] = session_event(**overrides)

    assert (await post_stripe(client, stripe_event)).status_code == 200

    assert (await db.execute(select(func.count()).select_from(Payment))).scalar() == 0
    assert (await db.execute(select(func.count()).select_from(User))).scalar() == 0


async def test_user_id_can_come_from_metadata(client, db, stripe_event):
    stripe_event["event"] = session_event(
        client_reference_id=None, metadata={"plan_duration": "7", "user_id": "user_meta"}
    )
    await post_stripe(client, stripe_event)

    user = (await db.execute(select(User).where(User.id == "user_meta"))).scalar_one()
    assert user.is_pro


async def test_refunds_that_do_not_apply_change_nothing(client, db, stripe_event):
    stripe_event["event"] = session_event()
    await post_stripe(client, stripe_event)

    for charge in (
        {"refunded": False, "payment_intent": "pi_1"},  # partial refund
        {"refunded": True, "payment_intent": None},
        {"refunded": True, "payment_intent": "pi_unknown"},
    ):
        stripe_event["event"] = {"type": "charge.refunded", "data": {"object": charge}}
        assert (await post_stripe(client, stripe_event)).status_code == 200

    stripe_event["event"] = {"type": "customer.created", "data": {"object": {}}}
    assert (await post_stripe(client, stripe_event)).status_code == 200

    user = (
        await db.execute(select(User).where(User.id == USER).execution_options(populate_existing=True))
    ).scalar_one()
    assert user.is_pro
    assert (await db.execute(select(Payment))).scalar_one().refunded_at is None


# ── Clerk webhook ────────────────────────────────────────────────────────────


async def test_clerk_webhook_needs_its_secret(client, monkeypatch):
    monkeypatch.setattr(settings, "CLERK_WEBHOOK_SECRET", None)
    assert (await client.post("/api/v1/webhooks/clerk", json={})).status_code == 500


async def test_clerk_webhook_rejects_signed_garbage(client):
    body = "this is not json"
    response = await client.post("/api/v1/webhooks/clerk", content=body, headers=clerk_signed(body))
    assert response.status_code == 400


async def test_clerk_events_without_effect(client, db):
    for payload in ({"type": "user.created", "data": {}}, {"type": "session.created", "data": {"id": "sess_1"}}):
        body = json.dumps(payload)
        response = await client.post("/api/v1/webhooks/clerk", content=body, headers=clerk_signed(body))
        assert response.status_code == 200
    assert (await db.execute(select(func.count()).select_from(User))).scalar() == 0


async def test_clerk_user_updated_changes_email_and_survives_conflicts(client, db):
    db.add_all([User(id="user_a", email="taken@example.com"), User(id="user_b", email="old@example.com", is_pro=True)])
    await db.commit()

    async def send(email_addresses, primary=None):
        body = json.dumps(
            {
                "type": "user.updated",
                "data": {"id": "user_b", "primary_email_address_id": primary, "email_addresses": email_addresses},
            }
        )
        return await client.post("/api/v1/webhooks/clerk", content=body, headers=clerk_signed(body))

    async def email_of(user_id):
        query = select(User).where(User.id == user_id).execution_options(populate_existing=True)
        return (await db.execute(query)).scalar_one()

    # No primary marked: the first address is used
    assert (await send([{"id": "i1", "email_address": "new@example.com"}])).status_code == 200
    user_b = await email_of("user_b")
    assert user_b.email == "new@example.com" and user_b.is_pro

    # Address already used by another account: acknowledged, nothing changes
    assert (await send([{"id": "i2", "email_address": "taken@example.com"}], primary="i2")).status_code == 200
    assert (await email_of("user_b")).email == "new@example.com"

    # No addresses at all clears it
    assert (await send([])).status_code == 200
    assert (await email_of("user_b")).email is None
