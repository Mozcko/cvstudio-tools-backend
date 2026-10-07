import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, field_validator

from src.schemas.ai_schemas import (
    MAX_IMPORT_TEXT_CHARS,
    MAX_JOB_DESCRIPTION_CHARS,
    Language,
    _to_lines,
    _to_rows,
    _to_text,
)

MAX_REQUIREMENTS = 20
MAX_CANDIDATES = 500

RequirementKind = Literal["must", "nice"]
RequirementStatus = Literal["met", "partial", "missing"]


def _to_kind(value: Any) -> str:
    text = str(value).strip().lower() if isinstance(value, str) else ""
    return "nice" if text in ("nice", "nice-to-have", "nice_to_have", "optional", "preferred") else "must"


def _to_status(value: Any) -> str:
    text = str(value).strip().lower() if isinstance(value, str) else ""
    if text in ("met", "yes", "true"):
        return "met"
    return "partial" if text in ("partial", "partly", "partially") else "missing"


# --- Requests ---------------------------------------------------------------------------------


class ScreeningCreate(BaseModel):
    title: str = Field(min_length=1, max_length=150)
    job_description: str = Field(min_length=50, max_length=MAX_JOB_DESCRIPTION_CHARS)
    language: Language

    @field_validator("title")
    @classmethod
    def not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("title is empty")
        return v.strip()


class Requirement(BaseModel):
    """One line of the rubric. `id` is kept stable so evaluations can refer to it."""

    model_config = ConfigDict(extra="ignore")

    id: Annotated[str, _to_text(40)] = ""
    text: Annotated[str, _to_text(300)] = ""
    kind: Annotated[str, BeforeValidator(_to_kind)] = "must"


class ScreeningUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=150)
    rubric: list[Requirement] | None = Field(default=None, min_length=1, max_length=MAX_REQUIREMENTS)


class CandidateCreate(BaseModel):
    """A CV as text. Files are read in the recruiter's browser and never uploaded."""

    file_name: str = Field(default="", max_length=255)
    text: str = Field(min_length=1, max_length=MAX_IMPORT_TEXT_CHARS)

    @field_validator("text")
    @classmethod
    def enough_text(cls, v: str) -> str:
        if len(v.strip()) < 80:
            raise ValueError("the CV has too little text to evaluate")
        return v


class CandidateUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=120)
    note: str | None = Field(default=None, max_length=2000)


# --- What the models return (untrusted) -------------------------------------------------------


class _Generated(BaseModel):
    model_config = ConfigDict(extra="ignore")


class GeneratedRubric(_Generated):
    requirements: Annotated[list[Requirement], _to_rows(MAX_REQUIREMENTS)] = []


class GeneratedFinding(_Generated):
    id: Annotated[str, _to_text(40)] = ""
    status: Annotated[str, BeforeValidator(_to_status)] = "missing"
    # A sentence copied from the CV that shows it
    evidence: Annotated[str, _to_text(300)] = ""


class GeneratedEvaluation(_Generated):
    requirements: Annotated[list[GeneratedFinding], _to_rows(MAX_REQUIREMENTS)] = []
    strengths: Annotated[list[str], _to_lines(4, 200)] = []
    concerns: Annotated[list[str], _to_lines(4, 200)] = []
    summary: Annotated[str, _to_text(500)] = ""


# --- Responses --------------------------------------------------------------------------------


class Finding(BaseModel):
    id: str
    text: str
    kind: RequirementKind
    status: RequirementStatus
    evidence: str
    # Whether the quoted evidence was found in the CV. An unverified "met" counts as "partial"
    verified: bool


class CandidateResult(BaseModel):
    requirements: list[Finding]
    strengths: list[str]
    concerns: list[str]
    summary: str


class CandidateOut(BaseModel):
    id: uuid.UUID
    # Position in the ranking, from 1
    rank: int
    top: bool
    display_name: str
    file_name: str
    contact: dict[str, list[str]]
    score: int
    missing_musts: int
    flagged: bool
    result: CandidateResult
    note: str
    created_at: datetime


class CandidateAdded(BaseModel):
    candidate: CandidateOut
    # The same CV was already in this screening: nothing was evaluated or charged
    duplicate: bool


class ScreeningSummary(BaseModel):
    id: uuid.UUID
    title: str
    language: str
    candidates: int
    top_score: int | None
    created_at: datetime
    # When the screening and everything in it is deleted
    expires_at: datetime


class ScreeningDetail(ScreeningSummary):
    job_description: str
    rubric: list[Requirement]
    # The rubric can only change before the first candidate is evaluated
    rubric_locked: bool
    ranking: list[CandidateOut]
