import json
import logging
import re
from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import enforce_ai_quota, get_current_user_obj, get_db, reserve_import
from src.models.ai_request import AIRequest
from src.models.user import User
from src.schemas.ai_schemas import (
    ATSRequest,
    CoverLetterRequest,
    ImportRequest,
    ImportResponse,
    ImprovementRequest,
    RewriteRequest,
    RewriteResponse,
)
from src.services.ai.ats import simulate_ats
from src.services.ai.base import AINotConfiguredError
from src.services.ai.cover_letter import generate_cover_letter
from src.services.ai.importer import EmptyImportError, import_cv
from src.services.ai.rewrite import rewrite_cv

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ai", tags=["AI Agents"])

# Format the legacy /ai/improve `context` string was sent in
LEGACY_CONTEXT_RE = re.compile(r"^Action:\s*(\w+),\s*Lang:\s*(\w+),\s*JD:\s*(.*)$", re.DOTALL)


@asynccontextmanager
async def ai_errors(feature: str):
    """Maps provider failures to stable responses without leaking internals to the client."""
    try:
        yield
    except HTTPException:
        raise
    except AINotConfiguredError:
        logger.error("AI %s requested but the provider is not configured", feature)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI features are not available right now.",
        ) from None
    except Exception:
        logger.exception("AI %s failed", feature)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The AI service could not process this request. Please try again.",
        ) from None


@router.post("/rewrite", response_model=RewriteResponse)
async def ai_rewrite(req: RewriteRequest, user: User = Depends(enforce_ai_quota)):
    async with ai_errors("rewrite"):
        result = await rewrite_cv(req.cv_content, req.action, req.target_language, req.job_description)
    return RewriteResponse(cv=result)


@router.post("/improve", deprecated=True)
async def ai_improve(req: ImprovementRequest, user: User = Depends(enforce_ai_quota)):
    """Deprecated shim for clients that still send the CV as a string plus a free-text context."""
    match = LEGACY_CONTEXT_RE.match((req.context or "").strip())
    try:
        cv_content = json.loads(req.text)
    except ValueError:
        cv_content = None

    if not match or not isinstance(cv_content, dict):
        raise HTTPException(status_code=400, detail="Unsupported request. Use POST /ai/rewrite.")

    try:
        parsed = RewriteRequest(
            cv_content=cv_content,
            action=match.group(1).lower(),
            target_language=match.group(2).lower(),
            job_description=match.group(3).strip() or None,
        )
    except ValueError:
        raise HTTPException(status_code=400, detail="Unsupported request. Use POST /ai/rewrite.") from None

    async with ai_errors("improve"):
        result = await rewrite_cv(parsed.cv_content, parsed.action, parsed.target_language, parsed.job_description)
    return {"improved_text": json.dumps(result, ensure_ascii=False)}


@router.post("/cover-letter")
async def ai_cover_letter(req: CoverLetterRequest, user: User = Depends(enforce_ai_quota)):
    async with ai_errors("cover letter"):
        result = await generate_cover_letter(req.cv_content, req.job_description, req.language)
    return {"cover_letter": result}


@router.post("/ats")
async def ai_ats(req: ATSRequest, user: User = Depends(enforce_ai_quota)):
    async with ai_errors("ATS"):
        result = await simulate_ats(req.cv_content, req.job_description, req.language)
    return result


@router.post("/import", response_model=ImportResponse)
async def ai_import(
    req: ImportRequest,
    request: Request,
    user: User = Depends(get_current_user_obj),
    db: AsyncSession = Depends(get_db),
):
    """Turns the text of a resume (PDF text or an unknown structured format) into a CV."""
    allowance = await reserve_import(request.url.path, user, db)
    try:
        async with ai_errors("import"):
            try:
                result = await import_cv(req.text, req.source, req.language)
            except EmptyImportError:
                raise HTTPException(
                    status_code=422,
                    detail="No CV content could be read from this document.",
                ) from None
    except HTTPException:
        # An import that produced nothing does not count against the user's allowance
        await db.execute(delete(AIRequest).where(AIRequest.id == allowance.request_id))
        await db.commit()
        raise

    return ImportResponse(cv=result, remaining_free_imports=allowance.remaining)
