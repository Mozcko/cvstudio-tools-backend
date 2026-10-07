import json
import re
from typing import Annotated, Any, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, field_validator, model_validator

MAX_JOB_DESCRIPTION_CHARS = 20_000
MAX_CV_JSON_CHARS = 200_000
MAX_IMPORT_TEXT_CHARS = 60_000

Language = Literal["es", "en", "pt"]
RewriteAction = Literal["enhance", "optimize", "translate"]


def _check_cv_size(v: dict[str, Any]) -> dict[str, Any]:
    if len(json.dumps(v)) > MAX_CV_JSON_CHARS:
        raise ValueError("cv_content is too large")
    return v


class RewriteRequest(BaseModel):
    cv_content: dict[str, Any]
    action: RewriteAction
    target_language: Language
    job_description: str | None = Field(default=None, max_length=MAX_JOB_DESCRIPTION_CHARS)

    _cv_size = field_validator("cv_content")(_check_cv_size)

    @model_validator(mode="after")
    def optimize_needs_job_description(self):
        if self.action == "optimize" and not (self.job_description or "").strip():
            raise ValueError("job_description is required when action is 'optimize'")
        return self


class RewriteResponse(BaseModel):
    cv: dict[str, Any]


class ImprovementRequest(BaseModel):
    """Deprecated: use RewriteRequest with POST /ai/rewrite."""

    text: str = Field(max_length=MAX_CV_JSON_CHARS)
    context: str | None = Field(default="", max_length=MAX_JOB_DESCRIPTION_CHARS + 200)


class CoverLetterRequest(BaseModel):
    cv_content: dict[str, Any]
    job_description: str = Field(min_length=1, max_length=MAX_JOB_DESCRIPTION_CHARS)
    language: Language | None = None

    _cv_size = field_validator("cv_content")(_check_cv_size)


class ATSRequest(BaseModel):
    cv_content: dict[str, Any]
    job_description: str = Field(min_length=1, max_length=MAX_JOB_DESCRIPTION_CHARS)
    language: Language | None = None

    _cv_size = field_validator("cv_content")(_check_cv_size)


# --- CV import --------------------------------------------------------------------------------


class ImportRequest(BaseModel):
    """Text of a document (extracted in the browser) to turn into a structured CV."""

    text: str = Field(min_length=1, max_length=MAX_IMPORT_TEXT_CHARS)
    source: Literal["pdf", "structured"] = "pdf"
    language: Language | None = None

    @field_validator("text")
    @classmethod
    def not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("text is empty")
        return v


class ImportResponse(BaseModel):
    cv: dict[str, Any]
    # Imports a free user has left; null for Pro
    remaining_free_imports: int | None = None


MONTH_RE = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])")
YEAR_ONLY_RE = re.compile(r"^(?:19|20)\d{2}$")


def _to_text(limit: int):
    def coerce(value: Any) -> str:
        if value is None or isinstance(value, dict | list | bool):
            return ""
        return str(value).strip()[:limit]

    return BeforeValidator(coerce)


def _to_month(value: Any) -> str:
    """'YYYY-MM' or ''. A bare year becomes January of that year."""
    text = str(value).strip() if isinstance(value, str | int) and not isinstance(value, bool) else ""
    match = MONTH_RE.match(text)
    if match:
        return f"{match.group(1)}-{match.group(2)}"
    return f"{text}-01" if YEAR_ONLY_RE.match(text) else ""


def _to_rows(limit: int):
    """Keeps only objects, at most `limit` of them."""

    def coerce(value: Any) -> list:
        if not isinstance(value, list):
            return []
        return [item for item in value if isinstance(item, dict)][:limit]

    return BeforeValidator(coerce)


def _to_lines(limit: int, length: int):
    """A list of non-empty strings; a single string is split on line breaks."""

    def coerce(value: Any) -> list[str]:
        if isinstance(value, str):
            value = value.splitlines()
        if not isinstance(value, list):
            return []
        lines = [str(v).strip().lstrip("•-*· ").strip()[:length] for v in value if isinstance(v, str | int | float)]
        return [line for line in lines if line][:limit]

    return BeforeValidator(coerce)


Short = Annotated[str, _to_text(300)]
Long = Annotated[str, _to_text(4000)]
Month = Annotated[str, BeforeValidator(_to_month)]
Bullets = Annotated[list[str], _to_lines(30, 1000)]
Flag = Annotated[bool, BeforeValidator(lambda v: v is True)]


class _Imported(BaseModel):
    # The model's output is untrusted: unknown keys are dropped, wrong types become empty values
    model_config = ConfigDict(extra="ignore")


class ImportedSocial(_Imported):
    network: Short = ""
    username: Short = ""
    url: Short = ""


class ImportedPersonal(_Imported):
    name: Short = ""
    role: Short = ""
    email: Short = ""
    phone: Short = ""
    city: Short = ""
    summary: Long = ""
    socials: Annotated[list[ImportedSocial], _to_rows(10)] = []


class ImportedExperience(_Imported):
    company: Short = ""
    role: Short = ""
    location: Short = ""
    startDate: Month = ""
    endDate: Month = ""
    isCurrent: Flag = False
    description: Bullets = []


class ImportedEducation(_Imported):
    institution: Short = ""
    degree: Short = ""
    startDate: Month = ""
    endDate: Month = ""
    isCurrent: Flag = False


class ImportedSkill(_Imported):
    category: Short = ""
    items: Annotated[str, _to_text(1000)] = ""


class ImportedProject(_Imported):
    name: Short = ""
    role: Short = ""
    startDate: Month = ""
    endDate: Month = ""
    url: Short = ""
    description: Bullets = []


def _to_cv_language(value: Any) -> str | None:
    code = value.strip().upper()[:2] if isinstance(value, str) else ""
    return code if code in ("ES", "EN", "PT") else None


class ImportedCV(_Imported):
    """Shape of `CVData` in the frontend (`src/types/cv.ts`), without ids."""

    personal: Annotated[ImportedPersonal, BeforeValidator(lambda v: v if isinstance(v, dict) else {})] = (
        ImportedPersonal()
    )
    experience: Annotated[list[ImportedExperience], _to_rows(40)] = []
    education: Annotated[list[ImportedEducation], _to_rows(20)] = []
    skills: Annotated[list[ImportedSkill], _to_rows(30)] = []
    certifications: Annotated[list[ImportedSkill], _to_rows(30)] = []
    projects: Annotated[list[ImportedProject], _to_rows(30)] = []
    languages: Annotated[str, _to_text(1000)] = ""
    interests: Annotated[str, _to_text(1000)] = ""
    # Language the document is written in
    language: Annotated[str | None, BeforeValidator(_to_cv_language)] = None

    def is_empty(self) -> bool:
        return not (self.personal.name or self.personal.summary or self.experience or self.education or self.skills)
