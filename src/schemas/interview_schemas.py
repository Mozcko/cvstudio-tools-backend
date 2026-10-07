import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, field_validator

from src.schemas.ai_schemas import MAX_JOB_DESCRIPTION_CHARS, Language, _check_cv_size, _to_lines, _to_rows, _to_text

MIN_QUESTIONS = 4
MAX_QUESTIONS = 8
MAX_ANSWER_CHARS = 4000

QuestionType = Literal["opening", "experience", "behavioral", "technical", "closing"]


class InterviewCreate(BaseModel):
    cv_content: dict[str, Any]
    job_description: str = Field(min_length=20, max_length=MAX_JOB_DESCRIPTION_CHARS)
    language: Language
    question_count: int = Field(default=6, ge=MIN_QUESTIONS, le=MAX_QUESTIONS)

    _cv_size = field_validator("cv_content")(_check_cv_size)


class AnswerText(BaseModel):
    """Typed answer, for when the microphone cannot be used."""

    text: str = Field(min_length=1, max_length=MAX_ANSWER_CHARS)

    @field_validator("text")
    @classmethod
    def not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("text is empty")
        return v.strip()


# --- What the models return (untrusted: trimmed and coerced, unknown keys dropped) ------------


class _Generated(BaseModel):
    model_config = ConfigDict(extra="ignore")


def _to_question_type(value: Any) -> str:
    text = str(value).strip().lower() if isinstance(value, str) else ""
    return text if text in ("opening", "experience", "behavioral", "technical", "closing") else "experience"


class GeneratedQuestion(_Generated):
    type: Annotated[str, BeforeValidator(_to_question_type)] = "experience"
    text: Annotated[str, _to_text(500)] = ""


class GeneratedPlan(_Generated):
    title: Annotated[str, _to_text(120)] = ""
    questions: Annotated[list[GeneratedQuestion], _to_rows(MAX_QUESTIONS)] = []


class GeneratedReply(_Generated):
    acknowledgement: Annotated[str, _to_text(300)] = ""
    follow_up: Annotated[str, _to_text(400)] = ""


def _to_score(maximum: int):
    def coerce(value: Any) -> int:
        try:
            number = round(float(value))
        except (TypeError, ValueError):
            return 0
        return max(0, min(maximum, number))

    return BeforeValidator(coerce)


class AnswerFeedback(_Generated):
    question: Annotated[int, _to_score(MAX_QUESTIONS)] = 0
    score: Annotated[int, _to_score(10)] = 0
    went_well: Annotated[str, _to_text(600)] = ""
    improve: Annotated[str, _to_text(600)] = ""
    sample_answer: Annotated[str, _to_text(1500)] = ""


class Report(_Generated):
    overall_score: Annotated[int, _to_score(100)] = 0
    summary: Annotated[str, _to_text(1200)] = ""
    strengths: Annotated[list[str], _to_lines(5, 300)] = []
    improvements: Annotated[list[str], _to_lines(5, 300)] = []
    tips: Annotated[list[str], _to_lines(3, 300)] = []
    answers: Annotated[list[AnswerFeedback], _to_rows(MAX_QUESTIONS)] = []


# --- Responses --------------------------------------------------------------------------------


class Turn(BaseModel):
    index: int
    role: Literal["recruiter", "candidate"]
    kind: Literal["question", "follow_up", "answer", "closing"]
    # Which prepared question this turn belongs to
    question: int
    text: str
    at: datetime


class SessionSummary(BaseModel):
    id: uuid.UUID
    title: str
    language: str
    status: Literal["active", "completed"]
    question_count: int
    overall_score: int | None = None
    created_at: datetime
    completed_at: datetime | None = None


class SessionDetail(SessionSummary):
    # Index of the question being asked; equals question_count once the interview is over
    current_question: int
    # True when the recruiter has said goodbye and only the report is left
    done: bool
    # The questions asked so far, as prepared (recruiter turns also carry greetings and
    # acknowledgements). Later questions are not revealed until they are reached.
    questions: list[str]
    turns: list[Turn]
    report: Report | None = None


class AnswerResponse(BaseModel):
    # What was understood from the answer (the transcript when it was spoken)
    answer: Turn
    reply: Turn
    current_question: int
    done: bool
