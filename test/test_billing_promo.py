from datetime import datetime, timedelta, timezone

import pytest
import stripe
from sqlalchemy import func, select

from src.models.payment import Payment
from src.models.promo import PromoCode
from src.models.user import User

USER = "user_test_1"


async def get_user(db, user_id=USER):
    result = await db.execute(select(User).where(User.id == user_id).execution_options(populate_existing=True))
    return result.scalar_one_or_none()


@pytest.fixture
def stripe_event(monkeypatch):
    """Lets a test choose the event Stripe 'sends'; signature checking is stubbed out."""
    holder = {}
    monkeypatch.setattr(
        stripe.Webhook, "construct_event", lambda payload, sig, secret: holder["event"]
    )
    return holder


def checkout_event(session_id="cs_1", plan="30", payment_status="paid", payment_intent="pi_1"):
    return {
        "type": "checkout.session.completed",
        "data": {"object": {
            "id": session_id,
            "payment_status": payment_status,
            "client_reference_id": USER,
            "payment_intent": payment_intent,
            "metadata": {"plan_duration": plan},
        }},
    }


async def send_webhook(client):
    return await client.post(
        "/api/v1/webhooks/stripe", content=b"{}", headers={"Stripe-Signature": "t=1,v1=x"}
    )


async def test_stripe_webhook_requires_signature_header(client):
    response = await client.post("/api/v1/webhooks/stripe", content=b"{}")
    assert response.status_code == 400


async def test_stripe_webhook_rejects_bad_signature(client):
    response = await send_webhook(client)
    assert response.status_code == 400


async def test_checkout_grants_pro_once(client, db, stripe_event):
    stripe_event["event"] = checkout_event()

    assert (await send_webhook(client)).status_code == 200
    first_expiry = (await get_user(db)).pro_expires_at
    # Stripe retries the same event
    assert (await send_webhook(client)).status_code == 200

    user = await get_user(db)
    assert user.is_pro
    assert user.pro_expires_at == first_expiry
    assert abs(user.pro_expires_at - (datetime.now(timezone.utc) + timedelta(days=30))) < timedelta(minutes=1)
    assert (await db.execute(select(func.count()).select_from(Payment))).scalar() == 1


async def test_second_purchase_extends_instead_of_overwriting(client, db, stripe_event):
    stripe_event["event"] = checkout_event("cs_1", "30", payment_intent="pi_1")
    await send_webhook(client)
    stripe_event["event"] = checkout_event("cs_2", "7", payment_intent="pi_2")
    await send_webhook(client)

    user = await get_user(db)
    assert abs(user.pro_expires_at - (datetime.now(timezone.utc) + timedelta(days=37))) < timedelta(minutes=1)


async def test_unpaid_session_grants_nothing(client, db, stripe_event):
    stripe_event["event"] = checkout_event(payment_status="unpaid")

    assert (await send_webhook(client)).status_code == 200

    assert await get_user(db) is None


async def test_refund_revokes_the_grant(client, db, stripe_event):
    stripe_event["event"] = checkout_event("cs_1", "lifetime", payment_intent="pi_life")
    await send_webhook(client)
    assert (await get_user(db)).is_pro

    stripe_event["event"] = {
        "type": "charge.refunded",
        "data": {"object": {"id": "ch_1", "refunded": True, "payment_intent": "pi_life"}},
    }
    await send_webhook(client)
    await send_webhook(client)  # retried delivery must not revoke twice

    user = await get_user(db)
    assert not user.is_pro
    payment = (await db.execute(select(Payment))).scalar_one()
    assert payment.refunded_at is not None


async def test_checkout_endpoint_hides_provider_errors(client, monkeypatch):
    from src.core.config import settings

    monkeypatch.setattr(settings, "STRIPE_API_KEY", "sk_test_x")
    monkeypatch.setattr(settings, "STRIPE_PRICE_7D", "price_x")

    def boom(**kwargs):
        raise RuntimeError("stripe secret detail")

    monkeypatch.setattr(stripe.checkout.Session, "create", boom)

    response = await client.post("/api/v1/billing/create-checkout-session", json={"plan_type": "7"})

    assert response.status_code == 502
    assert "secret detail" not in response.text


async def test_checkout_unconfigured_plan(client):
    response = await client.post("/api/v1/billing/create-checkout-session", json={"plan_type": "30"})
    assert response.status_code == 503


async def test_old_redeem_endpoint_is_gone(client):
    response = await client.post("/api/v1/billing/redeem", json={"code": "X"})
    assert response.status_code == 404


async def test_promo_redeem_once_per_user(client, db, current_user):
    db.add(PromoCode(code="LAUNCH", max_uses=5, granted_days=30))
    await db.commit()

    first = await client.post("/api/v1/promo/redeem", json={"code": " LAUNCH "})
    assert first.status_code == 200 and first.json()["granted_days"] == 30

    again = await client.post("/api/v1/promo/redeem", json={"code": "LAUNCH"})
    assert again.status_code == 400

    current_user["id"] = "user_other"
    other = await client.post("/api/v1/promo/redeem", json={"code": "LAUNCH"})
    assert other.status_code == 200

    promo = (await db.execute(select(PromoCode))).scalar_one()
    assert promo.used_count == 2
    user = await get_user(db)
    assert abs(user.pro_expires_at - (datetime.now(timezone.utc) + timedelta(days=30))) < timedelta(minutes=1)


async def test_promo_limits_and_lifetime(client, db, current_user):
    db.add_all([
        PromoCode(code="ONCE", max_uses=1, granted_days=9999),
        PromoCode(code="OFF", max_uses=5, granted_days=30, is_active=False),
    ])
    await db.commit()

    assert (await client.post("/api/v1/promo/redeem", json={"code": "NOPE"})).status_code == 404
    assert (await client.post("/api/v1/promo/redeem", json={"code": "OFF"})).status_code == 400
    assert (await client.post("/api/v1/promo/redeem", json={"code": "  "})).status_code == 400

    assert (await client.post("/api/v1/promo/redeem", json={"code": "ONCE"})).status_code == 200
    user = await get_user(db)
    assert user.is_pro and user.pro_expires_at is None

    current_user["id"] = "user_other"
    assert (await client.post("/api/v1/promo/redeem", json={"code": "ONCE"})).status_code == 400
