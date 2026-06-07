from pydantic import BaseModel, ConfigDict
from typing import Dict, Any, Optional
from datetime import datetime
from uuid import UUID

class CVBase(BaseModel):
    title: str
    content: Dict[str, Any]
    language: Optional[str] = 'ES'

class CVCreate(CVBase):
    pass

class CVUpdate(BaseModel):
    title: Optional[str] = None
    content: Optional[Dict[str, Any]] = None
    language: Optional[str] = None

class CVResponse(CVBase):
    id: UUID
    user_id: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
