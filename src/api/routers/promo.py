from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import timedelta
from sqlalchemy.sql import func
import logging

from src.api.dependencies import get_db, get_current_user
from src.models.user import User
from src.models.promo import PromoCode
from src.schemas.promo_schemas import PromoRedeemRequest, PromoRedeemResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/promo", tags=["Promo"])

@router.post("/redeem", response_model=PromoRedeemResponse)
async def redeem_promo(
    request: PromoRedeemRequest,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user)
):
    code_str = request.code.strip()
    if not code_str:
        raise HTTPException(status_code=400, detail="Promo code cannot be empty")

    # Lock the promo code row for update to prevent race conditions
    result = await db.execute(
        select(PromoCode)
        .where(PromoCode.code == code_str)
        .with_for_update()
    )
    promo = result.scalar_one_or_none()

    if not promo:
        raise HTTPException(status_code=404, detail="Invalid promotional code")
    
    if not promo.is_active:
        raise HTTPException(status_code=400, detail="Promotional code is no longer active")
        
    if promo.max_uses > 0 and promo.used_count >= promo.max_uses:
        raise HTTPException(status_code=400, detail="Promotional code usage limit reached")

    # Fetch user
    user_result = await db.execute(
        select(User)
        .where(User.id == user_id)
        .with_for_update()
    )
    user = user_result.scalar_one_or_none()
    
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Update Promo stats
    promo.used_count += 1

    # Apply premium pass to User
    user.is_pro = True
    
    # If 9999, consider it lifetime (or just leave pro_expires_at as null to indicate lifetime)
    if promo.granted_days >= 9999:
        user.pro_expires_at = None
    else:
        # Extend from now if not pro, or extend from current expiration if already pro
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        
        if user.pro_expires_at and user.pro_expires_at > now:
            user.pro_expires_at = user.pro_expires_at + timedelta(days=promo.granted_days)
        else:
            user.pro_expires_at = now + timedelta(days=promo.granted_days)

    try:
        await db.commit()
    except Exception as e:
        await db.rollback()
        logger.error(f"Error redeeming promo: {e}")
        raise HTTPException(status_code=500, detail="Could not redeem promo code")

    return PromoRedeemResponse(
        success=True,
        message="Promotional code redeemed successfully",
        granted_days=promo.granted_days
    )
