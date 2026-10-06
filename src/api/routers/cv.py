from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_current_user, get_current_user_obj, get_db
from src.core.config import settings
from src.models.cv import CV
from src.models.user import User
from src.schemas.cv_schemas import CVCreate, CVResponse, CVUpdate

router = APIRouter(prefix="/cvs", tags=["CVs"])


@router.post("/", response_model=CVResponse, status_code=status.HTTP_201_CREATED)
async def create_cv(cv_in: CVCreate, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user_obj)):
    if not user.is_pro:
        # Count existing CVs
        count_result = await db.execute(select(func.count()).select_from(CV).where(CV.user_id == user.id))
        cv_count = count_result.scalar() or 0

        if cv_count >= settings.FREE_CV_LIMIT:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Free tier limit reached ({settings.FREE_CV_LIMIT} CVs). Please upgrade to Pro to create more.",
            )

    new_cv = CV(
        user_id=user.id,
        title=cv_in.title,
        content=cv_in.content,
        language=cv_in.language or "ES",
        theme=cv_in.theme,
    )
    db.add(new_cv)
    await db.commit()
    await db.refresh(new_cv)
    return new_cv


@router.get("/", response_model=list[CVResponse])
async def list_cvs(db: AsyncSession = Depends(get_db), user_id: str = Depends(get_current_user)):
    result = await db.execute(select(CV).where(CV.user_id == user_id).order_by(CV.updated_at.desc()))
    return result.scalars().all()


@router.get("/{cv_id}", response_model=CVResponse)
async def get_cv(cv_id: UUID, db: AsyncSession = Depends(get_db), user_id: str = Depends(get_current_user)):
    result = await db.execute(select(CV).where(CV.id == cv_id))
    cv = result.scalar_one_or_none()

    if not cv:
        raise HTTPException(status_code=404, detail="CV not found")

    if cv.user_id != user_id:
        raise HTTPException(status_code=403, detail="Not authorized to access this CV")

    return cv


@router.put("/{cv_id}", response_model=CVResponse)
async def update_cv(
    cv_id: UUID, cv_in: CVUpdate, db: AsyncSession = Depends(get_db), user_id: str = Depends(get_current_user)
):
    result = await db.execute(select(CV).where(CV.id == cv_id))
    cv = result.scalar_one_or_none()

    if not cv:
        raise HTTPException(status_code=404, detail="CV not found")

    if cv.user_id != user_id:
        raise HTTPException(status_code=403, detail="Not authorized to update this CV")

    if cv_in.title is not None:
        cv.title = cv_in.title
    if cv_in.content is not None:
        cv.content = cv_in.content
    if cv_in.language is not None:
        cv.language = cv_in.language
    if cv_in.theme is not None:
        cv.theme = cv_in.theme

    await db.commit()
    await db.refresh(cv)
    return cv


@router.delete("/{cv_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_cv(cv_id: UUID, db: AsyncSession = Depends(get_db), user_id: str = Depends(get_current_user)):
    result = await db.execute(select(CV).where(CV.id == cv_id))
    cv = result.scalar_one_or_none()

    if not cv:
        raise HTTPException(status_code=404, detail="CV not found")

    if cv.user_id != user_id:
        raise HTTPException(status_code=403, detail="Not authorized to delete this CV")

    await db.execute(delete(CV).where(CV.id == cv_id))
    await db.commit()
    return None
