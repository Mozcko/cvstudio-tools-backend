import asyncio
import logging

import stripe
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_current_user_obj, get_db
from src.core.config import settings
from src.models.user import User
from src.schemas.recruiter_schemas import RecruiterCheckoutRequest, RecruiterStatus, RecruiterUrl
from src.services.recruiter_plans import entitlement, get_subscription

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/recruiter", tags=["Recruiter"])

RECRUITER_HOME = "/app/recruiter"


@router.get("/me", response_model=RecruiterStatus)
async def recruiter_status(user: User = Depends(get_current_user_obj), db: AsyncSession = Depends(get_db)):
    """The caller's recruiter plan and what is left of it."""
    allowed = await entitlement(db, user)
    return RecruiterStatus(
        plan=allowed.plan,
        status=allowed.status,
        can_evaluate=allowed.can_evaluate,
        used=allowed.used,
        limit=allowed.limit,
        remaining=allowed.remaining,
        period_end=allowed.period_end,
        retention_days=allowed.retention_days,
        reason=allowed.reason,
        has_billing=allowed.has_billing,
    )


@router.post("/billing/checkout", response_model=RecruiterUrl)
async def recruiter_checkout(
    body: RecruiterCheckoutRequest, user: User = Depends(get_current_user_obj), db: AsyncSession = Depends(get_db)
):
    """Starts a subscription. Changing or cancelling an existing one happens in the portal."""
    price_id = {
        "starter": settings.STRIPE_PRICE_RECRUITER_STARTER,
        "pro": settings.STRIPE_PRICE_RECRUITER_PRO,
    }[body.plan]
    if not price_id or not settings.STRIPE_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="This plan is not available right now."
        )

    sub = await get_subscription(db, user.id)
    if sub and sub.stripe_subscription_id and sub.status in ("active", "past_due"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You already have a subscription. Use 'manage subscription' to change it.",
        )

    params = {
        "api_key": settings.STRIPE_API_KEY,
        "mode": "subscription",
        "line_items": [{"price": price_id, "quantity": 1}],
        "client_reference_id": user.id,
        # The subscription carries the user id, so every later event can be matched to them
        "subscription_data": {"metadata": {"user_id": user.id}},
        "metadata": {"kind": "recruiter", "user_id": user.id},
        "success_url": f"{settings.FRONTEND_URL}{RECRUITER_HOME}?subscribed=1",
        "cancel_url": f"{settings.FRONTEND_URL}{RECRUITER_HOME}",
    }
    if sub and sub.stripe_customer_id:
        # A returning customer keeps their Stripe customer (cards, invoices)
        params["customer"] = sub.stripe_customer_id

    try:
        # The Stripe SDK call is blocking; keep it off the event loop
        session = await asyncio.to_thread(stripe.checkout.Session.create, **params)
    except Exception:
        logger.exception("Could not create the recruiter Checkout session")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="Could not start the checkout. Please try again."
        ) from None
    return RecruiterUrl(url=session.url)


@router.post("/billing/portal", response_model=RecruiterUrl)
async def recruiter_portal(user: User = Depends(get_current_user_obj), db: AsyncSession = Depends(get_db)):
    """Stripe's own page to change plan, update the card, see invoices or cancel."""
    sub = await get_subscription(db, user.id)
    if not sub or not sub.stripe_customer_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="There is no subscription to manage.")
    if not settings.STRIPE_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Billing is not available right now."
        )

    try:
        session = await asyncio.to_thread(
            stripe.billing_portal.Session.create,
            api_key=settings.STRIPE_API_KEY,
            customer=sub.stripe_customer_id,
            return_url=f"{settings.FRONTEND_URL}{RECRUITER_HOME}",
        )
    except Exception:
        logger.exception("Could not create the billing portal session")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="Could not open billing. Please try again."
        ) from None
    return RecruiterUrl(url=session.url)
