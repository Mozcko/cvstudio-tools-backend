from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import IMPORT_KEY, free_ai_usage, free_imports_used, get_current_user_obj, get_db
from src.api.routers.interviews import DAY, MONTH, interviews_started
from src.core.config import settings
from src.models.user import User
from src.schemas.user_schemas import Quota, Usage, UserResponse
from src.services.pro import is_premium, plan_of

router = APIRouter(prefix="/users", tags=["Users"])


@router.get("/me", response_model=UserResponse)
async def get_me(user: User = Depends(get_current_user_obj), db: AsyncSession = Depends(get_db)):
    ai_used, ai_resets_at = await free_ai_usage(user, db)
    imports_used = await free_imports_used(user, IMPORT_KEY, db)
    daily_used, daily_resets_at = await interviews_started(user, db, DAY)
    monthly_used, monthly_resets_at = await interviews_started(user, db, MONTH)

    def interviews(limit: int, used: int, resets_at):
        return Quota(limit=limit, remaining=max(0, limit - used), resets_at=resets_at if used >= limit > 0 else None)

    return UserResponse(
        id=user.id,
        is_pro=bool(user.is_pro),
        pro_expires_at=user.pro_expires_at,
        plan=plan_of(user),
        is_premium=is_premium(user),
        premium_until=user.premium_until,
        usage=Usage(
            free_ai=Quota(
                limit=settings.FREE_AI_WEEKLY_LIMIT,
                remaining=max(0, settings.FREE_AI_WEEKLY_LIMIT - ai_used),
                # Only meaningful once the allowance is used up
                resets_at=ai_resets_at if ai_used >= settings.FREE_AI_WEEKLY_LIMIT else None,
            ),
            free_imports=Quota(
                limit=settings.FREE_IMPORT_LIMIT,
                remaining=max(0, settings.FREE_IMPORT_LIMIT - imports_used),
            ),
            interviews_daily=interviews(settings.INTERVIEW_DAILY_LIMIT, daily_used, daily_resets_at),
            interviews_monthly=interviews(settings.INTERVIEW_MONTHLY_LIMIT, monthly_used, monthly_resets_at),
        ),
    )
