from pydantic import BaseModel
from typing import Optional

class PromoRedeemRequest(BaseModel):
    code: str

class PromoRedeemResponse(BaseModel):
    success: bool
    message: str
    granted_days: int = 0
