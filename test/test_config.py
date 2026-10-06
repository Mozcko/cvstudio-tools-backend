import pytest
from pydantic import ValidationError

from src.core.config import Settings

BASE = {"DATABASE_URL": "postgresql+asyncpg://u:p@localhost/db", "CLERK_ISSUER": "https://clerk.example.com"}


def make(**overrides):
    # _env_file=None: only the values given here count, whatever .env exists on the machine
    return Settings(_env_file=None, **{**BASE, **overrides})


@pytest.mark.parametrize(
    "given",
    ["postgres://u:p@host/db", "postgresql://u:p@host/db", "postgresql+asyncpg://u:p@host/db"],
)
def test_database_url_is_rewritten_for_asyncpg(given):
    assert make(DATABASE_URL=given).DATABASE_URL == "postgresql+asyncpg://u:p@host/db"


def test_issuer_is_required(monkeypatch):
    monkeypatch.delenv("CLERK_ISSUER", raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, DATABASE_URL=BASE["DATABASE_URL"])


@pytest.mark.parametrize("bad", ["", "clerk.example.com", "http://clerk.example.com"])
def test_issuer_must_be_https(bad):
    with pytest.raises(ValidationError):
        make(CLERK_ISSUER=bad)


def test_issuer_is_normalised():
    assert make(CLERK_ISSUER=" https://clerk.example.com/ ").CLERK_ISSUER == "https://clerk.example.com"


def test_allowed_origins_include_frontend_and_localhost_once():
    origins = make(FRONTEND_URL="https://cvstudio.tools/").allowed_origins
    assert origins[0] == "https://cvstudio.tools"
    assert "http://localhost:4321" in origins
    assert len(origins) == len(set(origins))

    # The default FRONTEND_URL is one of the localhost entries: no duplicate
    assert make().allowed_origins.count("http://localhost:4321") == 1


def test_authorized_parties_default_to_origins_and_can_be_overridden():
    assert make().authorized_parties == make().allowed_origins
    custom = make(CLERK_AUTHORIZED_PARTIES="https://a.example/, https://b.example ,")
    assert custom.authorized_parties == ["https://a.example", "https://b.example"]
