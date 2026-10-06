from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class CVBase(BaseModel):
    title: str
    content: dict[str, Any]
    language: str | None = "ES"
    theme: str | None = Field(default=None, max_length=64)


class CVCreate(CVBase):
    pass


class CVUpdate(BaseModel):
    title: str | None = None
    content: dict[str, Any] | None = None
    language: str | None = None
    theme: str | None = Field(default=None, max_length=64)


class CVResponse(CVBase):
    id: UUID
    user_id: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
