from pydantic import BaseModel
from typing import Optional, Literal

class RedeemRequest(BaseModel):
    code: str

class RedeemResponse(BaseModel):
    success: bool
    message: str
    is_pro: bool

class CheckoutRequest(BaseModel):
    plan_type: Literal['7', '30', 'lifetime']

class CheckoutResponse(BaseModel):
    url: str
