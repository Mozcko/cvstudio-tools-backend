from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from src.api.dependencies import get_db, get_current_user
from src.models.user import User
from src.schemas.ai_schemas import ImprovementRequest, CoverLetterRequest, ATSRequest
from src.services.ai.improvement import improve_text
from src.services.ai.cover_letter import generate_cover_letter
from src.services.ai.ats import simulate_ats

router = APIRouter(prefix="/ai", tags=["AI Agents"])

async def check_pro_status(user_id: str, db: AsyncSession):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user or not user.is_pro:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This feature requires a Pro subscription."
        )
    return user

@router.post("/improve")
async def ai_improve(
    req: ImprovementRequest, 
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    try:
        await check_pro_status(user_id, db)
        print(f"DEBUG: AI Improve request received. Context: {req.context}")
        result = await improve_text(req.text, req.context)
        return {"improved_text": result}
    except Exception as e:
        print(f"ERROR: AI Improve failed: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/cover-letter")
async def ai_cover_letter(
    req: CoverLetterRequest, 
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    try:
        await check_pro_status(user_id, db)
        result = await generate_cover_letter(req.cv_content, req.job_description)
        return {"cover_letter": result}
    except Exception as e:
        print(f"ERROR: AI Cover Letter failed: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/ats")
async def ai_ats(
    req: ATSRequest, 
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    try:
        await check_pro_status(user_id, db)
        result = await simulate_ats(req.cv_content, req.job_description)
        return result
    except Exception as e:
        print(f"ERROR: AI ATS Match failed: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
