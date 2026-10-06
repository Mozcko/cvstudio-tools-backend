from pydantic import BaseModel
from typing import Literal

class CheckoutRequest(BaseModel):
    plan_type: Literal['7', '30', 'lifetime']

class CheckoutResponse(BaseModel):
    url: str
