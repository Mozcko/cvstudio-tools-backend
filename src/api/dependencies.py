import math
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.core.security import get_current_user_id
from src.db.database import AsyncSessionLocal
from src.models.ai_request import AIRequest
from src.models.user import User
from src.services.pro import apply_expiry


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
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This feature requires a Pro subscription.")
    return user


async def enforce_ai_quota(
    request: Request, user: User = Depends(require_pro), db: AsyncSession = Depends(get_db)
) -> User:
    """Pro-only + per-user rate limit for AI endpoints. Records the call when accepted."""
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

    db.add(AIRequest(user_id=user.id, endpoint=request.url.path))
    await db.commit()
    return user
