from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class RecruiterCheckoutRequest(BaseModel):
    plan: Literal["starter", "pro"]


class RecruiterUrl(BaseModel):
    url: str


class RecruiterStatus(BaseModel):
    # trial | starter | pro | enterprise
    plan: str
    # trial | active | past_due | canceled
    status: str
    can_evaluate: bool
    # CVs evaluated in the current period (or of the trial)
    used: int
    # null is unlimited
    limit: int | None
    remaining: int | None
    period_end: datetime | None
    # How long candidate data is kept
    retention_days: int
    # Why evaluating is refused, when it is
    reason: str | None
    # Whether "manage subscription" (the Stripe portal) is available
    has_billing: bool
