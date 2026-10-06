from fastapi import APIRouter, Depends
from src.api.dependencies import get_current_user_obj
from src.models.user import User
from src.schemas.user_schemas import UserResponse

router = APIRouter(prefix="/users", tags=["Users"])

@router.get("/me", response_model=UserResponse)
async def get_me(user: User = Depends(get_current_user_obj)):
    return user
