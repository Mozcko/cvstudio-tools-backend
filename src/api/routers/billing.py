from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import stripe
from src.api.dependencies import get_db, get_current_user
from src.models.promo import PromoCode
from src.models.user import User
from src.schemas.billing_schemas import RedeemRequest, RedeemResponse, CheckoutRequest, CheckoutResponse
from src.core.config import settings
from datetime import datetime, timedelta, timezone

router = APIRouter(prefix="/billing", tags=["Billing"])

@router.post("/redeem", response_model=RedeemResponse)
async def redeem_code(
    request: RedeemRequest,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user)
):
    # 1. Query for the promo code
    result = await db.execute(select(PromoCode).where(PromoCode.code == request.code))
    promo = result.scalar_one_or_none()

    # 2. Validations
    if not promo or not promo.is_active or promo.used_count >= promo.max_uses:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired code"
        )

    # 3. Update PromoCode usage
    promo.used_count += 1
    if promo.used_count >= promo.max_uses:
        promo.is_active = False

    # 4. Calculate expiration
    expires_at = None
    if promo.granted_days < 9999:
        expires_at = datetime.now(timezone.utc) + timedelta(days=promo.granted_days)

    # 5. Upgrade User to Pro
    user_result = await db.execute(select(User).where(User.id == user_id))
    user = user_result.scalar_one_or_none()
    
    if not user:
        user = User(id=user_id, is_pro=True, pro_expires_at=expires_at)
        db.add(user)
    else:
        user.is_pro = True
        user.pro_expires_at = expires_at

    # 6. Commit
    await db.commit()
    
    return RedeemResponse(
        success=True,
        message=f"Code redeemed successfully! {promo.granted_days} days of Pro access granted.",
        is_pro=True
    )

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
    
    if not price_id:
        raise HTTPException(status_code=400, detail="Invalid plan type or Price ID not configured")

    try:
        stripe.api_key = settings.STRIPE_API_KEY
        checkout_session = stripe.checkout.Session.create(
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
        return CheckoutResponse(url=checkout_session.url)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
