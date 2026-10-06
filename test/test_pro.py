from datetime import UTC, datetime, timedelta

from src.models.user import User
from src.services.pro import apply_expiry, grant_pro, revoke_grant

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def make_user(is_pro=False, expires=None):
    return User(id="u", is_pro=is_pro, pro_expires_at=expires)


def test_grant_to_free_user_starts_now():
    user = make_user()
    grant_pro(user, 7, NOW)
    assert user.is_pro and user.pro_expires_at == NOW + timedelta(days=7)


def test_grant_extends_remaining_time():
    user = make_user(True, NOW + timedelta(days=20))
    grant_pro(user, 7, NOW)
    assert user.pro_expires_at == NOW + timedelta(days=27)


def test_grant_after_expiry_starts_from_now():
    user = make_user(True, NOW - timedelta(days=3))
    grant_pro(user, 30, NOW)
    assert user.is_pro and user.pro_expires_at == NOW + timedelta(days=30)


def test_timed_grant_never_downgrades_lifetime():
    user = make_user(True, None)
    grant_pro(user, 7, NOW)
    assert user.is_pro and user.pro_expires_at is None


def test_lifetime_grant():
    for days in (None, 9999):
        user = make_user(True, NOW + timedelta(days=5))
        grant_pro(user, days, NOW)
        assert user.is_pro and user.pro_expires_at is None


def test_apply_expiry():
    expired = make_user(True, NOW - timedelta(seconds=1))
    assert apply_expiry(expired, NOW) is True
    assert not expired.is_pro and expired.pro_expires_at is None

    active = make_user(True, NOW + timedelta(days=1))
    assert apply_expiry(active, NOW) is False and active.is_pro

    lifetime = make_user(True, None)
    assert apply_expiry(lifetime, NOW) is False and lifetime.is_pro


def test_revoke_timed_grant():
    user = make_user(True, NOW + timedelta(days=37))
    revoke_grant(user, 30, NOW)
    assert user.is_pro and user.pro_expires_at == NOW + timedelta(days=7)

    revoke_grant(user, 30, NOW)
    assert not user.is_pro and user.pro_expires_at is None


def test_revoke_lifetime_grant():
    user = make_user(True, None)
    revoke_grant(user, None, NOW)
    assert not user.is_pro


def test_revoking_timed_grant_keeps_lifetime():
    user = make_user(True, None)
    revoke_grant(user, 7, NOW)
    assert user.is_pro and user.pro_expires_at is None
