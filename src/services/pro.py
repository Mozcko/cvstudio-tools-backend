from datetime import UTC, datetime, timedelta

from src.models.user import User

# Promo codes use this many days (or more) to mean "lifetime"
LIFETIME_DAYS = 9999


def _now() -> datetime:
    return datetime.now(UTC)


def apply_expiry(user: User, now: datetime | None = None) -> bool:
    """Downgrades the user if their pass has run out. Returns True if something changed."""
    now = now or _now()
    if user.is_pro and user.pro_expires_at and user.pro_expires_at < now:
        user.is_pro = False
        user.pro_expires_at = None
        return True
    return False


def grant_pro(user: User, days: int | None, now: datetime | None = None) -> None:
    """
    Grants Pro access. `days=None` (or >= LIFETIME_DAYS) means lifetime.
    Timed grants extend the remaining time; they never shorten it and never downgrade lifetime.
    """
    now = now or _now()
    apply_expiry(user, now)

    if days is None or days >= LIFETIME_DAYS:
        user.is_pro = True
        user.pro_expires_at = None
        return

    if user.is_pro and user.pro_expires_at is None:
        # Already lifetime
        return

    base = user.pro_expires_at if (user.is_pro and user.pro_expires_at) else now
    user.is_pro = True
    user.pro_expires_at = base + timedelta(days=days)


def revoke_grant(user: User, days: int | None, now: datetime | None = None) -> None:
    """Takes back a previous grant (e.g. after a refund)."""
    now = now or _now()

    if days is None or days >= LIFETIME_DAYS:
        user.is_pro = False
        user.pro_expires_at = None
        return

    if not user.is_pro or user.pro_expires_at is None:
        # Not Pro, or lifetime from another grant: nothing to take back
        return

    user.pro_expires_at = user.pro_expires_at - timedelta(days=days)
    apply_expiry(user, now)
