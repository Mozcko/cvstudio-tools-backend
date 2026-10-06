from typing import Literal

from pydantic import BaseModel


class CheckoutRequest(BaseModel):
    plan_type: Literal["7", "30", "lifetime"]


class CheckoutResponse(BaseModel):
    url: str
