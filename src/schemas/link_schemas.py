import uuid
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field


class LinkWrite(BaseModel):
    slug: str = Field(min_length=1, max_length=80)
    is_active: bool = True
    show_email: bool = True
    show_phone: bool = False
    indexable: bool = False


class LinkOut(BaseModel):
    cv_id: uuid.UUID
    slug: str
    is_active: bool
    # Switched on, but not online because the plan allows fewer links
    paused: bool
    show_email: bool
    show_phone: bool
    indexable: bool
    views_total: int
    # Views since the owner last looked
    views_new: int
    created_at: datetime


class SlugCheck(BaseModel):
    slug: str
    available: bool
    # length | format | reserved | taken
    reason: str | None = None


class DailyViews(BaseModel):
    day: date
    views: int


class ReferrerViews(BaseModel):
    # None groups visits with no known origin (typed address, apps, private browsing)
    host: str | None
    views: int


class LinkStats(BaseModel):
    views_total: int
    visitors_total: int
    # Pro only; null on the free plan
    daily: list[DailyViews] | None = None
    referrers: list[ReferrerViews] | None = None


class PublicCV(BaseModel):
    """What anyone with the link can read. Nothing here identifies the account."""

    slug: str
    title: str
    language: str
    theme: str | None
    content: dict[str, Any]
    # Show "made with CVStudio" (the owner is on the free plan)
    badge: bool
    indexable: bool
    updated_at: datetime | None


class ViewIn(BaseModel):
    referrer: str | None = Field(default=None, max_length=2000)
