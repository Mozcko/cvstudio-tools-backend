import logging
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_current_user_obj, get_db
from src.api.routers.ai import ai_errors
from src.models.screening import Screening, ScreeningCandidate
from src.models.user import User
from src.schemas.screening_schemas import (
    MAX_CANDIDATES,
    CandidateAdded,
    CandidateCreate,
    CandidateOut,
    CandidateUpdate,
    ScreeningCreate,
    ScreeningDetail,
    ScreeningSummary,
    ScreeningUpdate,
)
from src.services.ai.screening import (
    blind_copy,
    build_rubric,
    clean_rubric,
    evaluate_candidate,
    looks_like_instructions,
    text_hash,
)
from src.services.recruiter_plans import entitlement, release_evaluation, reserve_evaluation

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/recruiter/screenings", tags=["Recruiter"])

TOP = 5
# Building a rubric costs an AI call but no allowance: bound how many a user starts per day
MAX_SCREENINGS_PER_DAY = 20
FALLBACK_NAMES = {"es": "Candidato", "en": "Candidate", "pt": "Candidato"}


async def purge_expired(db: AsyncSession) -> int:
    """Deletes screenings past their retention date, with every candidate in them."""
    result = await db.execute(delete(Screening).where(Screening.expires_at < datetime.now(UTC)))
    await db.commit()
    return result.rowcount or 0


async def _own_screening(screening_id: uuid.UUID, user: User, db: AsyncSession) -> Screening:
    result = await db.execute(
        select(Screening).where(
            Screening.id == screening_id,
            Screening.user_id == user.id,
            # Expired data is gone as far as anyone can tell, even before the purge has run
            Screening.expires_at > datetime.now(UTC),
        )
    )
    screening = result.scalar_one_or_none()
    if not screening:
        # Also what someone else's screening looks like
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Screening not found")
    return screening


async def _candidates(screening_id: uuid.UUID, db: AsyncSession) -> list[ScreeningCandidate]:
    """In ranking order: best score first; among equals, fewer must-haves missing, then earliest."""
    result = await db.execute(
        select(ScreeningCandidate)
        .where(ScreeningCandidate.screening_id == screening_id)
        .order_by(
            ScreeningCandidate.score.desc(),
            ScreeningCandidate.missing_musts,
            ScreeningCandidate.created_at,
            ScreeningCandidate.id,
        )
    )
    return list(result.scalars())


def _candidate_out(candidate: ScreeningCandidate, rank: int) -> CandidateOut:
    return CandidateOut(
        id=candidate.id,
        rank=rank,
        top=rank <= TOP,
        display_name=candidate.display_name,
        file_name=candidate.file_name,
        contact=candidate.contact,
        score=candidate.score,
        missing_musts=candidate.missing_musts,
        flagged=candidate.flagged,
        result=candidate.result,
        note=candidate.note,
        created_at=candidate.created_at,
    )


def _summary_fields(screening: Screening, count: int, top_score: int | None) -> dict:
    return {
        "id": screening.id,
        "title": screening.title,
        "language": screening.language,
        "candidates": count,
        "top_score": top_score,
        "created_at": screening.created_at,
        "expires_at": screening.expires_at,
    }


async def _detail(screening: Screening, db: AsyncSession) -> ScreeningDetail:
    ranked = await _candidates(screening.id, db)
    return ScreeningDetail(
        **_summary_fields(screening, len(ranked), ranked[0].score if ranked else None),
        job_description=screening.job_description,
        rubric=screening.rubric,
        rubric_locked=bool(ranked),
        ranking=[_candidate_out(candidate, position + 1) for position, candidate in enumerate(ranked)],
    )


@router.post("", response_model=ScreeningDetail, status_code=status.HTTP_201_CREATED)
async def create_screening(
    body: ScreeningCreate, user: User = Depends(get_current_user_obj), db: AsyncSession = Depends(get_db)
):
    """Opens a vacancy and derives its rubric from the job description."""
    allowed = await entitlement(db, user)
    if not allowed.can_evaluate:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=allowed.reason)

    recent = await db.execute(
        select(func.count())
        .select_from(Screening)
        .where(Screening.user_id == user.id, Screening.created_at >= datetime.now(UTC) - timedelta(days=1))
    )
    if recent.scalar_one() >= MAX_SCREENINGS_PER_DAY:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many screenings started today. Please try again tomorrow.",
            headers={"Retry-After": "3600"},
        )

    async with ai_errors("screening rubric"):
        rubric = await build_rubric(body.job_description, body.language)

    now = datetime.now(UTC)
    screening = Screening(
        id=uuid.uuid4(),
        user_id=user.id,
        title=body.title,
        job_description=body.job_description,
        language=body.language,
        rubric=rubric,
        created_at=now,
        expires_at=now + timedelta(days=allowed.retention_days),
    )
    db.add(screening)
    await db.commit()
    return await _detail(screening, db)


@router.get("", response_model=list[ScreeningSummary])
async def list_screenings(user: User = Depends(get_current_user_obj), db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Screening, func.count(ScreeningCandidate.id), func.max(ScreeningCandidate.score))
        .outerjoin(ScreeningCandidate, ScreeningCandidate.screening_id == Screening.id)
        .where(Screening.user_id == user.id, Screening.expires_at > datetime.now(UTC))
        .group_by(Screening.id)
        .order_by(Screening.created_at.desc())
    )
    return [ScreeningSummary(**_summary_fields(screening, count, top)) for screening, count, top in result]


@router.get("/{screening_id}", response_model=ScreeningDetail)
async def get_screening(
    screening_id: uuid.UUID, user: User = Depends(get_current_user_obj), db: AsyncSession = Depends(get_db)
):
    return await _detail(await _own_screening(screening_id, user, db), db)


@router.put("/{screening_id}", response_model=ScreeningDetail)
async def update_screening(
    screening_id: uuid.UUID,
    body: ScreeningUpdate,
    user: User = Depends(get_current_user_obj),
    db: AsyncSession = Depends(get_db),
):
    """Renames a screening, or adjusts its rubric before any candidate has been evaluated."""
    screening = await _own_screening(screening_id, user, db)

    if body.title is not None:
        if not body.title.strip():
            raise HTTPException(status_code=422, detail="The title is empty.")
        screening.title = body.title.strip()

    if body.rubric is not None:
        evaluated = await db.execute(
            select(ScreeningCandidate.id).where(ScreeningCandidate.screening_id == screening.id).limit(1)
        )
        if evaluated.first():
            # Candidates already judged against one rubric cannot be compared with others
            # judged against a different one
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="The rubric cannot change once candidates have been evaluated.",
            )
        rubric = clean_rubric(body.rubric)
        if not rubric:
            raise HTTPException(status_code=422, detail="The rubric needs at least one requirement.")
        screening.rubric = rubric

    await db.commit()
    return await _detail(screening, db)


@router.delete("/{screening_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_screening(
    screening_id: uuid.UUID, user: User = Depends(get_current_user_obj), db: AsyncSession = Depends(get_db)
):
    await db.delete(await _own_screening(screening_id, user, db))
    await db.commit()


@router.post("/{screening_id}/candidates", response_model=CandidateAdded)
async def add_candidate(
    screening_id: uuid.UUID,
    body: CandidateCreate,
    user: User = Depends(get_current_user_obj),
    db: AsyncSession = Depends(get_db),
):
    """Evaluates one CV against the screening's rubric and adds it to the ranking."""
    screening = await _own_screening(screening_id, user, db)
    rubric, language = screening.rubric, screening.language
    digest = text_hash(body.text)

    async def ranked(candidate_id: uuid.UUID, duplicate: bool) -> CandidateAdded:
        for position, candidate in enumerate(await _candidates(screening_id, db)):
            if candidate.id == candidate_id:
                return CandidateAdded(candidate=_candidate_out(candidate, position + 1), duplicate=duplicate)
        raise HTTPException(status_code=404, detail="Candidate not found")  # pragma: no cover

    existing = await db.execute(
        select(ScreeningCandidate.id).where(
            ScreeningCandidate.screening_id == screening_id, ScreeningCandidate.text_hash == digest
        )
    )
    already = existing.scalar_one_or_none()
    if already:
        # The same CV uploaded twice: nothing to evaluate, nothing to charge
        return await ranked(already, duplicate=True)

    count = await db.execute(
        select(func.count()).select_from(ScreeningCandidate).where(ScreeningCandidate.screening_id == screening_id)
    )
    if count.scalar_one() >= MAX_CANDIDATES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A screening holds up to {MAX_CANDIDATES} candidates. Start another one for more.",
        )

    blind, name, contact = blind_copy(body.text, body.file_name)
    usage_id = await reserve_evaluation(db, user)
    try:
        async with ai_errors("candidate evaluation"):
            score, missing_musts, result = await evaluate_candidate(rubric, blind, language)
    except HTTPException:
        # An evaluation that produced nothing does not use up the allowance
        await release_evaluation(db, usage_id)
        raise

    candidate = ScreeningCandidate(
        id=uuid.uuid4(),
        screening_id=screening_id,
        display_name=name or FALLBACK_NAMES.get(language, "Candidate"),
        file_name=body.file_name.strip()[:255],
        contact=contact,
        text_hash=digest,
        score=score,
        missing_musts=missing_musts,
        flagged=looks_like_instructions(body.text),
        result=result,
        note="",
        created_at=datetime.now(UTC),
    )
    db.add(candidate)
    try:
        await db.commit()
    except IntegrityError:
        # The same CV arrived twice at once and the other request won
        await db.rollback()
        await release_evaluation(db, usage_id)
        winner = await db.execute(
            select(ScreeningCandidate.id).where(
                ScreeningCandidate.screening_id == screening_id, ScreeningCandidate.text_hash == digest
            )
        )
        return await ranked(winner.scalar_one(), duplicate=True)
    return await ranked(candidate.id, duplicate=False)


async def _own_candidate(
    screening_id: uuid.UUID, candidate_id: uuid.UUID, user: User, db: AsyncSession
) -> ScreeningCandidate:
    await _own_screening(screening_id, user, db)
    result = await db.execute(
        select(ScreeningCandidate).where(
            ScreeningCandidate.id == candidate_id, ScreeningCandidate.screening_id == screening_id
        )
    )
    candidate = result.scalar_one_or_none()
    if not candidate:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Candidate not found")
    return candidate


@router.put("/{screening_id}/candidates/{candidate_id}", response_model=CandidateOut)
async def update_candidate(
    screening_id: uuid.UUID,
    candidate_id: uuid.UUID,
    body: CandidateUpdate,
    user: User = Depends(get_current_user_obj),
    db: AsyncSession = Depends(get_db),
):
    """The recruiter's own corrections: the name shown, and their notes. Never the score."""
    candidate = await _own_candidate(screening_id, candidate_id, user, db)
    if body.display_name is not None:
        if not body.display_name.strip():
            raise HTTPException(status_code=422, detail="The name is empty.")
        candidate.display_name = body.display_name.strip()
    if body.note is not None:
        candidate.note = body.note.strip()
    await db.commit()

    for position, ranked in enumerate(await _candidates(screening_id, db)):
        if ranked.id == candidate_id:
            return _candidate_out(ranked, position + 1)
    raise HTTPException(status_code=404, detail="Candidate not found")  # pragma: no cover


@router.delete("/{screening_id}/candidates/{candidate_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_candidate(
    screening_id: uuid.UUID,
    candidate_id: uuid.UUID,
    user: User = Depends(get_current_user_obj),
    db: AsyncSession = Depends(get_db),
):
    await db.delete(await _own_candidate(screening_id, candidate_id, user, db))
    await db.commit()
