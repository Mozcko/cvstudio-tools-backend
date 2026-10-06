import json
from pydantic import BaseModel, Field, field_validator, model_validator
from typing import Dict, Any, Literal, Optional

MAX_JOB_DESCRIPTION_CHARS = 20_000
MAX_CV_JSON_CHARS = 200_000

Language = Literal["es", "en", "pt"]
RewriteAction = Literal["enhance", "optimize", "translate"]

def _check_cv_size(v: Dict[str, Any]) -> Dict[str, Any]:
    if len(json.dumps(v)) > MAX_CV_JSON_CHARS:
        raise ValueError("cv_content is too large")
    return v

class RewriteRequest(BaseModel):
    cv_content: Dict[str, Any]
    action: RewriteAction
    target_language: Language
    job_description: Optional[str] = Field(default=None, max_length=MAX_JOB_DESCRIPTION_CHARS)

    _cv_size = field_validator("cv_content")(_check_cv_size)

    @model_validator(mode="after")
    def optimize_needs_job_description(self):
        if self.action == "optimize" and not (self.job_description or "").strip():
            raise ValueError("job_description is required when action is 'optimize'")
        return self

class RewriteResponse(BaseModel):
    cv: Dict[str, Any]

class ImprovementRequest(BaseModel):
    """Deprecated: use RewriteRequest with POST /ai/rewrite."""
    text: str = Field(max_length=MAX_CV_JSON_CHARS)
    context: Optional[str] = Field(default="", max_length=MAX_JOB_DESCRIPTION_CHARS + 200)

class CoverLetterRequest(BaseModel):
    cv_content: Dict[str, Any]
    job_description: str = Field(min_length=1, max_length=MAX_JOB_DESCRIPTION_CHARS)
    language: Optional[Language] = None

    _cv_size = field_validator("cv_content")(_check_cv_size)

class ATSRequest(BaseModel):
    cv_content: Dict[str, Any]
    job_description: str = Field(min_length=1, max_length=MAX_JOB_DESCRIPTION_CHARS)
    language: Optional[Language] = None

    _cv_size = field_validator("cv_content")(_check_cv_size)
