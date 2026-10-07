from datetime import UTC, datetime, timedelta
from typing import Literal

from src.models.user import User

# Promo codes use this many days (or more) to mean "lifetime"
LIFETIME_DAYS = 9999

Plan = Literal["free", "sprint", "active", "lifetime"]

# What each purchasable plan grants: (days of Pro, premium level). None = lifetime.
#   Sprint Pass   7 days of Pro
#   Active Hunt  30 days of Pro, premium
#   Lifetime     Pro for ever, premium
PLAN_GRANTS: dict[str, tuple[int | None, bool]] = {
    "7": (7, False),
    "30": (30, True),
    "lifetime": (None, True),
}


def _now() -> datetime:
    return datetime.now(UTC)


def is_lifetime(user: User) -> bool:
    return bool(user.is_pro and user.pro_expires_at is None)


def is_premium(user: User, now: datetime | None = None) -> bool:
    """Premium features (e.g. mock interviews): Active Hunt while it lasts, and Lifetime."""
    now = now or _now()
    if is_lifetime(user):
        return True
    return bool(user.is_pro and user.premium_until and user.premium_until > now)


def plan_of(user: User, now: datetime | None = None) -> Plan:
    if not user.is_pro:
        return "free"
    if is_lifetime(user):
        return "lifetime"
    return "active" if is_premium(user, now) else "sprint"


def apply_expiry(user: User, now: datetime | None = None) -> bool:
    """Downgrades the user if their pass has run out. Returns True if something changed."""
    now = now or _now()
    changed = False
    if user.is_pro and user.pro_expires_at and user.pro_expires_at < now:
        user.is_pro = False
        user.pro_expires_at = None
        changed = True
    # Premium never outlives Pro, and lifetime does not need a date
    if user.premium_until and (not user.is_pro or is_lifetime(user) or user.premium_until <= now):
        user.premium_until = None
        changed = True
    return changed


def grant_pro(user: User, days: int | None, now: datetime | None = None, premium: bool = False) -> None:
    """
    Grants Pro access. `days=None` (or >= LIFETIME_DAYS) means lifetime.
    Timed grants extend the remaining time; they never shorten it and never downgrade lifetime.
    With `premium=True` the same number of days is added to the premium level.
    """
    now = now or _now()
    apply_expiry(user, now)

    if days is None or days >= LIFETIME_DAYS:
        user.is_pro = True
        user.pro_expires_at = None
        user.premium_until = None
        return

    if is_lifetime(user):
        return

    base = user.pro_expires_at if (user.is_pro and user.pro_expires_at) else now
    user.is_pro = True
    user.pro_expires_at = base + timedelta(days=days)
    if premium:
        user.premium_until = (user.premium_until or now) + timedelta(days=days)


def revoke_grant(user: User, days: int | None, now: datetime | None = None, premium: bool = False) -> None:
    """Takes back a previous grant (e.g. after a refund)."""
    now = now or _now()

    if days is None or days >= LIFETIME_DAYS:
        user.is_pro = False
        user.pro_expires_at = None
        user.premium_until = None
        return

    if not user.is_pro or user.pro_expires_at is None:
        # Not Pro, or lifetime from another grant: nothing to take back
        return

    user.pro_expires_at = user.pro_expires_at - timedelta(days=days)
    if premium and user.premium_until:
        user.premium_until = user.premium_until - timedelta(days=days)
    apply_expiry(user, now)
