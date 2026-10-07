import json
import logging
from datetime import UTC, datetime

import stripe
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.models.payment import Payment
from src.models.user import User
from src.services.pro import PLAN_GRANTS, grant_pro, revoke_grant
from src.services.recruiter_plans import apply_stripe_subscription

logger = logging.getLogger(__name__)


async def _handle_checkout_paid(session: dict, db: AsyncSession) -> None:
    if session.get("mode") == "subscription":
        # Recruiter subscriptions are driven by the customer.subscription.* events, which carry
        # the user id and the billing period. Nothing is granted from the checkout itself.
        return
    if session.get("payment_status") != "paid":
        # Delayed payment methods complete later via checkout.session.async_payment_succeeded
        return

    session_id = session.get("id")
    metadata = session.get("metadata") or {}
    # Extract Clerk User ID from client_reference_id or metadata
    clerk_user_id = session.get("client_reference_id") or metadata.get("user_id")
    plan_duration = metadata.get("plan_duration")

    if not session_id or not clerk_user_id or plan_duration not in PLAN_GRANTS:
        logger.warning("Ignoring checkout session %s: missing user or unknown plan", session_id)
        return

    # Stripe retries deliveries: a session is only ever applied once
    existing = await db.execute(select(Payment).where(Payment.session_id == session_id))
    if existing.scalar_one_or_none():
        return

    days, premium = PLAN_GRANTS[plan_duration]

    result = await db.execute(select(User).where(User.id == clerk_user_id).with_for_update())
    user = result.scalar_one_or_none()
    if not user:
        # If user doesn't exist in our DB yet, we create it
        user = User(id=clerk_user_id, is_pro=False)
        db.add(user)

    grant_pro(user, days, premium=premium)
    db.add(
        Payment(
            session_id=session_id,
            user_id=clerk_user_id,
            plan=plan_duration,
            payment_intent=session.get("payment_intent"),
            granted_days=days,
        )
    )

    try:
        await db.commit()
    except IntegrityError:
        # A concurrent delivery of the same event won the race
        await db.rollback()


async def _handle_charge_refunded(charge: dict, db: AsyncSession) -> None:
    if not charge.get("refunded"):
        # Partial refund: access is kept
        return

    payment_intent = charge.get("payment_intent")
    if not payment_intent:
        return

    result = await db.execute(
        select(Payment).where(Payment.payment_intent == payment_intent, Payment.refunded_at.is_(None)).with_for_update()
    )
    payment = result.scalar_one_or_none()
    if not payment:
        return

    user_result = await db.execute(select(User).where(User.id == payment.user_id).with_for_update())
    user = user_result.scalar_one_or_none()
    if user:
        # The plan that was bought decides whether premium time is taken back too
        _, premium = PLAN_GRANTS.get(payment.plan, (None, False))
        revoke_grant(user, payment.granted_days, premium=premium)

    payment.refunded_at = datetime.now(UTC)
    await db.commit()


async def process_webhook_event(payload: bytes, sig_header: str, db: AsyncSession):
    if not settings.STRIPE_WEBHOOK_SECRET:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Stripe webhook secret not configured"
        )

    try:
        # Signature and timestamp check only; raises if the payload was not sent by Stripe.
        # The event itself is read from the verified JSON below, as plain dicts, so the handlers
        # do not depend on the SDK's object model (newer SDK versions return objects without
        # dict methods such as .get()).
        body = payload.decode("utf-8")
        stripe.WebhookSignature.verify_header(
            body, sig_header, settings.STRIPE_WEBHOOK_SECRET, stripe.Webhook.DEFAULT_TOLERANCE
        )
        event = json.loads(body)
    except stripe.SignatureVerificationError:
        # Invalid signature
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid signature") from None
    except ValueError:
        # Invalid payload
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid payload") from None

    if not isinstance(event, dict) or not isinstance((event.get("data") or {}).get("object"), dict):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid payload")

    event_type = event.get("type")
    obj = event["data"]["object"]

    if event_type in ("checkout.session.completed", "checkout.session.async_payment_succeeded"):
        await _handle_checkout_paid(obj, db)
    elif event_type == "charge.refunded":
        await _handle_charge_refunded(obj, db)
    elif event_type in ("customer.subscription.created", "customer.subscription.updated"):
        await apply_stripe_subscription(db, obj, event.get("created"))
    elif event_type == "customer.subscription.deleted":
        await apply_stripe_subscription(db, obj, event.get("created"), deleted=True)

    return {"status": "success"}
