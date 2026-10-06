from datetime import datetime

from pydantic import BaseModel, ConfigDict


class UserResponse(BaseModel):
    id: str
    is_pro: bool
    pro_expires_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)
