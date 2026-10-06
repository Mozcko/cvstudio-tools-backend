from pydantic import BaseModel, ConfigDict
from typing import Optional
from datetime import datetime

class UserResponse(BaseModel):
    id: str
    is_pro: bool
    pro_expires_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)
