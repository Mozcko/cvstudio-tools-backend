import logging
import math
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_db, require_premium
from src.api.routers.ai import ai_errors
from src.core.config import settings
from src.models.interview import InterviewSession
from src.models.user import User
from src.schemas.interview_schemas import (
    MAX_ANSWER_CHARS,
    AnswerResponse,
    AnswerText,
    InterviewCreate,
    SessionDetail,
    SessionSummary,
    Turn,
)
from src.services.ai.interview import (
    CLOSINGS,
    NothingHeardError,
    greeting,
    plan_interview,
    recruiter_reply,
    synthesize,
    transcribe,
    write_report,
)

logger = logging.getLogger(__name__)

# Premium only (Active Hunt and Lifetime): every route costs real money to serve
router = APIRouter(prefix="/interviews", tags=["Mock interview"], dependencies=[Depends(require_premium)])

AUDIO_TYPES = {"audio/webm", "audio/ogg", "audio/mp4", "audio/x-m4a", "audio/mpeg", "audio/wav", "audio/x-wav"}
MAX_AUDIO_BYTES = 5 * 1024 * 1024
# An interview left open cannot be continued after this long
SESSION_TTL = timedelta(hours=2)
HISTORY_LIMIT = 50

DAY = timedelta(hours=24)
MONTH = timedelta(days=30)


async def interviews_started(user: User, db: AsyncSession, window: timedelta) -> tuple[int, datetime | None]:
    """Interviews the user started in the window, and when the oldest of them leaves it."""
    since = datetime.now(UTC) - window
    result = await db.execute(
        select(func.count(), func.min(InterviewSession.created_at)).where(
            InterviewSession.user_id == user.id, InterviewSession.created_at >= since
        )
    )
    used, oldest = result.one()
    return used, (oldest + window if oldest else None)


async def _check_caps(user: User, db: AsyncSession) -> None:
    for window, limit, detail in (
        (DAY, settings.INTERVIEW_DAILY_LIMIT, "Daily interview limit reached. Come back tomorrow."),
        (MONTH, settings.INTERVIEW_MONTHLY_LIMIT, "Monthly interview limit reached."),
    ):
        if limit <= 0:
            continue
        used, resets_at = await interviews_started(user, db, window)
        if used >= limit:
            wait = (resets_at - datetime.now(UTC)).total_seconds() if resets_at else 3600
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=detail,
                headers={"Retry-After": str(max(1, math.ceil(wait)))},
            )


def _turn(role: str, kind: str, question: int, text: str) -> dict:
    return {"role": role, "kind": kind, "question": question, "text": text, "at": datetime.now(UTC).isoformat()}


def _progress(session: InterviewSession) -> tuple[int, bool]:
    """(index of the question being asked, whether the recruiter has finished)."""
    last = next((t for t in reversed(session.turns) if t["role"] == "recruiter"), None)
    done = session.status == "completed" or (last is not None and last["kind"] == "closing")
    if done:
        return len(session.questions), True
    return (last["question"] if last else 0), False


def _summary_fields(session: InterviewSession) -> dict:
    report = session.report or {}
    return {
        "id": session.id,
        "title": session.title,
        "language": session.language,
        "status": session.status,
        "question_count": len(session.questions),
        "overall_score": report.get("overall_score") if session.report else None,
        "created_at": session.created_at,
        "completed_at": session.completed_at,
    }


def _detail(session: InterviewSession) -> SessionDetail:
    current, done = _progress(session)
    return SessionDetail(
        **_summary_fields(session),
        current_question=current,
        done=done,
        questions=[question["text"] for question in session.questions[: current + 1]],
        turns=[Turn(index=i, **turn) for i, turn in enumerate(session.turns)],
        report=session.report,
    )


async def _own_session(session_id: uuid.UUID, user: User, db: AsyncSession, lock: bool = False) -> InterviewSession:
    query = select(InterviewSession).where(InterviewSession.id == session_id, InterviewSession.user_id == user.id)
    if lock:
        query = query.with_for_update()
    session = (await db.execute(query.execution_options(populate_existing=True))).scalar_one_or_none()
    if not session:
        # Also what someone else's session looks like
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Interview not found")
    return session


async def _read_audio(request: Request) -> bytes:
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_AUDIO_BYTES:
        raise HTTPException(status_code=413, detail="The recording is too large.")

    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_AUDIO_BYTES:
            raise HTTPException(status_code=413, detail="The recording is too large.")
        chunks.append(chunk)
    if size == 0:
        raise HTTPException(status_code=422, detail="The recording is empty.")
    return b"".join(chunks)


@router.post("", response_model=SessionDetail, status_code=status.HTTP_201_CREATED)
async def start_interview(
    req: InterviewCreate, user: User = Depends(require_premium), db: AsyncSession = Depends(get_db)
):
    """Prepares the questions from the CV and the job posting and opens the interview."""
    await _check_caps(user, db)

    # The session is only stored (and counted) once the questions exist
    async with ai_errors("interview plan"):
        plan = await plan_interview(req.cv_content, req.job_description, req.language, req.question_count)

    questions = [question.model_dump() for question in plan.questions]
    opening = f"{greeting(req.language, req.cv_content)} {questions[0]['text']}"
    session = InterviewSession(
        id=uuid.uuid4(),
        user_id=user.id,
        title=plan.title,
        language=req.language,
        job_description=req.job_description,
        status="active",
        questions=questions,
        turns=[_turn("recruiter", "question", 0, opening)],
        audio_count=0,
        created_at=datetime.now(UTC),
    )
    db.add(session)
    await db.commit()
    return _detail(session)


@router.get("", response_model=list[SessionSummary])
async def list_interviews(user: User = Depends(require_premium), db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(InterviewSession)
        .where(InterviewSession.user_id == user.id)
        .order_by(InterviewSession.created_at.desc())
        .limit(HISTORY_LIMIT)
    )
    return [SessionSummary(**_summary_fields(session)) for session in result.scalars()]


@router.get("/{session_id}", response_model=SessionDetail)
async def get_interview(
    session_id: uuid.UUID, user: User = Depends(require_premium), db: AsyncSession = Depends(get_db)
):
    return _detail(await _own_session(session_id, user, db))


@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_interview(
    session_id: uuid.UUID, user: User = Depends(require_premium), db: AsyncSession = Depends(get_db)
):
    await db.delete(await _own_session(session_id, user, db))
    await db.commit()


@router.post("/{session_id}/answer", response_model=AnswerResponse)
async def answer(
    session_id: uuid.UUID,
    request: Request,
    user: User = Depends(require_premium),
    db: AsyncSession = Depends(get_db),
):
    """
    The candidate's answer to the current question: a recording (the request body is the audio,
    `Content-Type: audio/webm` etc.) or typed text (`application/json`, `{"text": "..."}`).
    Returns what was understood and what the recruiter says next.
    """
    content_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if content_type != "application/json" and content_type not in AUDIO_TYPES:
        raise HTTPException(status_code=415, detail="Send a recording (audio/webm, audio/mp4, …) or JSON text.")

    session = await _own_session(session_id, user, db)
    question, done = _progress(session)
    if done:
        raise HTTPException(status_code=409, detail="This interview is over.")
    if datetime.now(UTC) - session.created_at > SESSION_TTL:
        raise HTTPException(status_code=409, detail="This interview has expired. Start a new one.")
    turns_before = len(session.turns)

    if content_type == "application/json":
        try:
            text = AnswerText.model_validate(await request.json()).text
        except (ValidationError, ValueError):
            raise HTTPException(status_code=422, detail='Send {"text": "your answer"}.') from None
    else:
        audio = await _read_audio(request)
        async with ai_errors("interview transcription"):
            try:
                text = (await transcribe(audio, content_type, session.language))[:MAX_ANSWER_CHARS]
            except NothingHeardError:
                raise HTTPException(status_code=422, detail="We could not hear an answer in that recording.") from None

    # At most one follow-up per question, so an interview has a known maximum length
    may_follow_up = not any(t["kind"] == "follow_up" and t["question"] == question for t in session.turns)
    async with ai_errors("interview reply"):
        reply = await recruiter_reply(session.questions[question]["text"], text, session.language, may_follow_up)

    if reply.follow_up:
        said = _turn("recruiter", "follow_up", question, f"{reply.acknowledgement} {reply.follow_up}")
    elif question + 1 < len(session.questions):
        next_question = session.questions[question + 1]["text"]
        said = _turn("recruiter", "question", question + 1, f"{reply.acknowledgement} {next_question}")
    else:
        said = _turn("recruiter", "closing", question, f"{reply.acknowledgement} {CLOSINGS[session.language]}")
    heard = _turn("candidate", "answer", question, text)

    # Nothing was written while the AI calls ran; refuse if another answer got in first
    session = await _own_session(session_id, user, db, lock=True)
    if len(session.turns) != turns_before:
        await db.rollback()
        raise HTTPException(status_code=409, detail="This question was already answered.")
    session.turns = [*session.turns, heard, said]
    await db.commit()

    current, done = _progress(session)
    return AnswerResponse(
        answer=Turn(index=turns_before, **heard),
        reply=Turn(index=turns_before + 1, **said),
        current_question=current,
        done=done,
    )


@router.get("/{session_id}/turns/{index}/audio")
async def turn_audio(
    session_id: uuid.UUID,
    index: int,
    user: User = Depends(require_premium),
    db: AsyncSession = Depends(get_db),
):
    """
    Speech (MP3) for something the recruiter said. Only text this server wrote can be spoken,
    and only a bounded number of times per interview.
    """
    session = await _own_session(session_id, user, db, lock=True)
    if index < 0 or index >= len(session.turns) or session.turns[index]["role"] != "recruiter":
        await db.rollback()
        raise HTTPException(status_code=404, detail="Nothing to play for that turn")

    spoken_turns = sum(1 for t in session.turns if t["role"] == "recruiter")
    if session.audio_count >= spoken_turns * 2:
        await db.rollback()
        raise HTTPException(status_code=429, detail="Audio limit reached for this interview.")
    session.audio_count += 1
    text = session.turns[index]["text"]
    await db.commit()

    async with ai_errors("interview speech"):
        audio = await synthesize(text)
    return Response(content=audio, media_type="audio/mpeg", headers={"Cache-Control": "private, max-age=3600"})


@router.post("/{session_id}/finish", response_model=SessionDetail)
async def finish_interview(
    session_id: uuid.UUID, user: User = Depends(require_premium), db: AsyncSession = Depends(get_db)
):
    """Ends the interview (at any point) and writes the report. Safe to call twice."""
    session = await _own_session(session_id, user, db)
    if session.status == "completed":
        return _detail(session)
    if not any(t["role"] == "candidate" for t in session.turns):
        raise HTTPException(status_code=400, detail="Answer at least one question to get a report.")

    async with ai_errors("interview report"):
        report = await write_report(session.questions, session.turns, session.job_description, session.language)

    session = await _own_session(session_id, user, db, lock=True)
    if session.status != "completed":
        session.report = report.model_dump()
        session.status = "completed"
        session.completed_at = datetime.now(UTC)
    await db.commit()
    return _detail(session)
