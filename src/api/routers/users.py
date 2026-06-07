from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from src.api.dependencies import get_db, get_current_user_id
from src.models.user import User

router = APIRouter(prefix="/users", tags=["Users"])

@router.get("/me")
async def get_me(
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id)
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    
    if not user:
        # Create user if it doesn't exist
        new_user = User(id=user_id, is_pro=False)
        db.add(new_user)
        await db.commit()
        await db.refresh(new_user)
        return new_user
        
    return user
