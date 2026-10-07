import math
import uuid
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.core.security import get_current_user_id
from src.db.database import AsyncSessionLocal
from src.models.ai_request import AIRequest
from src.models.user import User
from src.services.pro import apply_expiry, is_premium


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session


async def get_current_user_obj(user_id: str = Depends(get_current_user_id), db: AsyncSession = Depends(get_db)) -> User:
    """Returns the caller's user row, creating it on first sight and applying Pro expiry."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        user = User(id=user_id, is_pro=False)
        db.add(user)
        try:
            await db.commit()
        except IntegrityError:
            # A concurrent request created the row first
            await db.rollback()
            result = await db.execute(select(User).where(User.id == user_id))
            user = result.scalar_one()
    elif apply_expiry(user):
        await db.commit()

    return user


async def get_current_user(user: User = Depends(get_current_user_obj)) -> str:
    return user.id


async def require_pro(user: User = Depends(get_current_user_obj)) -> User:
    if not user.is_pro:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=PRO_REQUIRED_DETAIL)
    return user


async def _check_ai_rate_limit(user: User, db: AsyncSession) -> None:
    """Raises 429 when the user is at or above the hourly or daily AI limit."""
    now = datetime.now(UTC)
    windows = (
        (timedelta(hours=1), settings.AI_RATE_LIMIT_PER_HOUR),
        (timedelta(days=1), settings.AI_RATE_LIMIT_PER_DAY),
    )

    for window, limit in windows:
        if limit <= 0:
            continue
        since = now - window
        result = await db.execute(
            select(func.count(), func.min(AIRequest.created_at)).where(
                AIRequest.user_id == user.id, AIRequest.created_at >= since
            )
        )
        count, oldest = result.one()
        if count >= limit:
            retry_after = max(1, math.ceil((oldest + window - now).total_seconds())) if oldest else 60
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="AI usage limit reached. Please try again later.",
                headers={"Retry-After": str(retry_after)},
            )


async def enforce_ai_quota(
    request: Request, user: User = Depends(require_pro), db: AsyncSession = Depends(get_db)
) -> User:
    """Pro-only + per-user rate limit for AI endpoints. Records the call when accepted."""
    await _check_ai_rate_limit(user, db)
    db.add(AIRequest(user_id=user.id, endpoint=request.url.path))
    await db.commit()
    return user


FREE_IMPORT_LIMIT_DETAIL = "Free import limit reached. Upgrade to Pro to import more CVs."
FREE_AI_LIMIT_DETAIL = "Free AI limit reached for this week. Upgrade to Pro for more."
PRO_REQUIRED_DETAIL = "This feature requires a Pro subscription."
PREMIUM_REQUIRED_DETAIL = "This feature requires the Active Hunt or Lifetime plan."

# Rewrite actions a non-Pro user may try, and the window their allowance is counted over
FREE_AI_ACTIONS = ("enhance", "optimize")
FREE_AI_WINDOW = timedelta(days=7)
# Free uses are recorded under their own key so they never mix with what a user did while Pro
FREE_AI_KEY = "free:rewrite"
# Imports are recorded under the route they came through
IMPORT_KEY = "/api/v1/ai/import"


async def require_premium(user: User = Depends(get_current_user_obj)) -> User:
    if not is_premium(user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=PREMIUM_REQUIRED_DETAIL)
    return user


@dataclass
class Allowance:
    """An accepted, recorded AI call. Not FastAPI dependencies on purpose: dependencies run
    even when the request body is invalid, and a rejected or failed request must not use up
    part of a free user's allowance. Handlers reserve one, and release it if the call fails."""

    user: User
    # The usage row recorded for this call
    request_id: uuid.UUID
    # What a free user has left after this call; None for Pro
    remaining: int | None


ImportAllowance = Allowance


async def _record(user: User, key: str, remaining: int | None, db: AsyncSession) -> Allowance:
    usage = AIRequest(id=uuid.uuid4(), user_id=user.id, endpoint=key)
    db.add(usage)
    await db.commit()
    return Allowance(user=user, request_id=usage.id, remaining=remaining)


async def release_allowance(allowance: Allowance, db: AsyncSession) -> None:
    """Gives back a reserved call that produced nothing."""
    await db.execute(delete(AIRequest).where(AIRequest.id == allowance.request_id))
    await db.commit()


async def free_ai_usage(user: User, db: AsyncSession, now: datetime | None = None) -> tuple[int, datetime | None]:
    """Free rewrites used in the current window, and when the oldest of them leaves it."""
    now = now or datetime.now(UTC)
    result = await db.execute(
        select(func.count(), func.min(AIRequest.created_at)).where(
            AIRequest.user_id == user.id,
            AIRequest.endpoint == FREE_AI_KEY,
            AIRequest.created_at >= now - FREE_AI_WINDOW,
        )
    )
    used, oldest = result.one()
    return used, (oldest + FREE_AI_WINDOW if oldest else None)


async def free_imports_used(user: User, endpoint: str, db: AsyncSession) -> int:
    result = await db.execute(select(func.count()).where(AIRequest.user_id == user.id, AIRequest.endpoint == endpoint))
    return result.scalar_one()


async def reserve_rewrite(endpoint: str, action: str, user: User, db: AsyncSession) -> Allowance:
    """
    CV rewrite: Pro users get every action under the normal AI rate limit. Everyone else may
    try FREE_AI_ACTIONS up to FREE_AI_WEEKLY_LIMIT times per rolling week.
    """
    if user.is_pro:
        await _check_ai_rate_limit(user, db)
        return await _record(user, endpoint, None, db)

    if action not in FREE_AI_ACTIONS:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=PRO_REQUIRED_DETAIL)

    used, _ = await free_ai_usage(user, db)
    if used >= settings.FREE_AI_WEEKLY_LIMIT:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=FREE_AI_LIMIT_DETAIL)
    return await _record(user, FREE_AI_KEY, settings.FREE_AI_WEEKLY_LIMIT - used - 1, db)


async def reserve_import(endpoint: str, user: User, db: AsyncSession) -> Allowance:
    """
    AI-assisted CV import: Pro users share the normal AI rate limit, everyone else gets
    FREE_IMPORT_LIMIT imports in total.
    """
    remaining = None
    if user.is_pro:
        await _check_ai_rate_limit(user, db)
    else:
        used = await free_imports_used(user, endpoint, db)
        if used >= settings.FREE_IMPORT_LIMIT:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=FREE_IMPORT_LIMIT_DETAIL)
        remaining = settings.FREE_IMPORT_LIMIT - used - 1
    return await _record(user, endpoint, remaining, db)
