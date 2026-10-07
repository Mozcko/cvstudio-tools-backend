import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_current_user, get_db
from src.models.promo import PromoCode, PromoRedemption
from src.models.user import User
from src.schemas.promo_schemas import PromoRedeemRequest, PromoRedeemResponse
from src.services.pro import grant_pro

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/promo", tags=["Promo"])


@router.post("/redeem", response_model=PromoRedeemResponse)
async def redeem_promo(
    request: PromoRedeemRequest, db: AsyncSession = Depends(get_db), user_id: str = Depends(get_current_user)
):
    code_str = request.code.strip()
    if not code_str:
        raise HTTPException(status_code=400, detail="Promo code cannot be empty")

    # Lock the promo code row for update to prevent race conditions
    result = await db.execute(select(PromoCode).where(PromoCode.code == code_str).with_for_update())
    promo = result.scalar_one_or_none()

    if not promo:
        raise HTTPException(status_code=404, detail="Invalid promotional code")

    if not promo.is_active:
        raise HTTPException(status_code=400, detail="Promotional code is no longer active")

    if promo.max_uses > 0 and promo.used_count >= promo.max_uses:
        raise HTTPException(status_code=400, detail="Promotional code usage limit reached")

    # One redemption per user per code
    already = await db.execute(
        select(PromoRedemption.id).where(
            PromoRedemption.promo_id == promo.id,
            PromoRedemption.user_id == user_id,
        )
    )
    if already.first():
        raise HTTPException(status_code=400, detail="You have already redeemed this code")

    # Fetch user
    user_result = await db.execute(select(User).where(User.id == user_id).with_for_update())
    user = user_result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    promo.used_count += 1
    db.add(PromoRedemption(promo_id=promo.id, user_id=user_id))
    grant_pro(user, promo.granted_days, premium=bool(promo.premium))

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=400, detail="You have already redeemed this code") from None
    except Exception:
        await db.rollback()
        logger.exception("Error redeeming promo")
        raise HTTPException(status_code=500, detail="Could not redeem promo code") from None

    return PromoRedeemResponse(
        success=True, message="Promotional code redeemed successfully", granted_days=promo.granted_days
    )
