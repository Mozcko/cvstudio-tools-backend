from typing import AsyncGenerator
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from src.db.database import AsyncSessionLocal
from src.core.security import get_current_user_id
from src.models.user import User

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session

from datetime import datetime, timezone

async def get_current_user(
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db)
) -> str:
    # Ensure user exists in our DB
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    
    if not user:
        new_user = User(id=user_id, is_pro=False)
        db.add(new_user)
        await db.commit()
    elif user.is_pro and user.pro_expires_at:
        # Check for expiration
        now = datetime.now(timezone.utc)
        if user.pro_expires_at < now:
            user.is_pro = False
            user.pro_expires_at = None
            await db.commit()
    
    return user_id
