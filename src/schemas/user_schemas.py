from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class Quota(BaseModel):
    limit: int
    remaining: int
    # When the next use becomes available again (rolling windows only)
    resets_at: datetime | None = None


class Usage(BaseModel):
    """What a non-Pro user has left. Pro users are bound by the AI rate limit instead."""

    free_ai: Quota
    free_imports: Quota


class UserResponse(BaseModel):
    id: str
    is_pro: bool
    pro_expires_at: datetime | None = None
    plan: Literal["free", "sprint", "active", "lifetime"]
    is_premium: bool
    premium_until: datetime | None = None
    usage: Usage
