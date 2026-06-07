from pydantic import BaseModel
from typing import Dict, Any, Optional

class ImprovementRequest(BaseModel):
    text: str
    context: Optional[str] = "resume bullet point"

class CoverLetterRequest(BaseModel):
    cv_content: Dict[str, Any]
    job_description: str

class ATSRequest(BaseModel):
    cv_content: Dict[str, Any]
    job_description: str
