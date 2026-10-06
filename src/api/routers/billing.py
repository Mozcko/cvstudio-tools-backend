import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, status
import stripe
from src.api.dependencies import get_current_user
from src.schemas.billing_schemas import CheckoutRequest, CheckoutResponse
from src.core.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/billing", tags=["Billing"])

@router.post("/create-checkout-session", response_model=CheckoutResponse)
async def create_checkout_session(
    request: CheckoutRequest,
    user_id: str = Depends(get_current_user)
):
    price_id = {
        "7": settings.STRIPE_PRICE_7D,
        "30": settings.STRIPE_PRICE_30D,
        "lifetime": settings.STRIPE_PRICE_LIFETIME
    }.get(request.plan_type)

    if not price_id or not settings.STRIPE_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="This plan is not available right now."
        )

    try:
        # The Stripe SDK call is blocking; keep it off the event loop
        checkout_session = await asyncio.to_thread(
            stripe.checkout.Session.create,
            api_key=settings.STRIPE_API_KEY,
            line_items=[
                {
                    "price": price_id,
                    "quantity": 1,
                },
            ],
            mode='payment',
            client_reference_id=user_id,
            metadata={
                "plan_duration": request.plan_type
            },
            success_url=f"{settings.FRONTEND_URL}/app/dashboard?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{settings.FRONTEND_URL}/app/dashboard",
        )
    except Exception:
        logger.exception("Could not create Stripe Checkout session")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not start the checkout. Please try again."
        )

    return CheckoutResponse(url=checkout_session.url)
