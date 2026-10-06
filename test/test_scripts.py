from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

import create_promo
from src.models.promo import PromoCode
from src.models.user import User
from src.scripts import upgrade_user as upgrade_script


@pytest.fixture(autouse=True)
def use_test_database(session_factory, monkeypatch):
    """The scripts open their own sessions; point them at the test database."""
    monkeypatch.setattr(upgrade_script, "AsyncSessionLocal", session_factory)
    monkeypatch.setattr(create_promo, "AsyncSessionLocal", session_factory)


async def get_user(db, user_id):
    result = await db.execute(select(User).where(User.id == user_id).execution_options(populate_existing=True))
    return result.scalar_one_or_none()


async def test_upgrade_creates_unknown_user_as_lifetime(db):
    assert await upgrade_script.upgrade_user(user_id="user_new") == 0

    user = await get_user(db, "user_new")
    assert user.is_pro and user.pro_expires_at is None


async def test_upgrade_with_days_extends_existing_time(db):
    expires = datetime.now(UTC) + timedelta(days=10)
    db.add(User(id="user_a", email="a@example.com", is_pro=True, pro_expires_at=expires))
    await db.commit()

    assert await upgrade_script.upgrade_user(email="a@example.com", days=5) == 0

    user = await get_user(db, "user_a")
    assert user.pro_expires_at == expires + timedelta(days=5)


async def test_upgrade_by_unknown_email_fails_without_creating_anything(db, capsys):
    assert await upgrade_script.upgrade_user(email="nobody@example.com") == 1
    assert "--user-id" in capsys.readouterr().out
    assert (await db.execute(select(User))).first() is None


async def test_upgrade_needs_an_identifier(capsys):
    assert await upgrade_script.upgrade_user() == 1
    assert "Must provide" in capsys.readouterr().out


async def test_create_promo_code(db, capsys):
    await create_promo.create_promo_code("LAUNCH", 10, 9999)

    promo = (await db.execute(select(PromoCode))).scalar_one()
    assert (promo.code, promo.max_uses, promo.granted_days, promo.used_count) == ("LAUNCH", 10, 9999, 0)
    assert "Lifetime" in capsys.readouterr().out

    # Codes are unique: a second attempt reports the failure instead of raising
    await create_promo.create_promo_code("LAUNCH", 1, 30)
    assert "Failed" in capsys.readouterr().out
