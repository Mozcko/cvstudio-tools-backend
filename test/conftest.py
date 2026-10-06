import os

# Settings are read at import time, so the environment must be ready before `src` is imported.
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/cvstudio_test")
os.environ.setdefault("CLERK_ISSUER", "https://clerk.test.example")
os.environ.setdefault("CLERK_WEBHOOK_SECRET", "whsec_MfKQ9r8GKYqrTwjUPD8ILPZIo2LaLaSw")
os.environ.setdefault("STRIPE_WEBHOOK_SECRET", "whsec_test")
os.environ.setdefault("OPENAI_API_KEY", "sk-test")

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

import src.models  # noqa: F401
from src.api.dependencies import get_db
from src.core.config import settings
from src.core.security import get_current_user_id
from src.db.database import Base
from src.main import app

TEST_USER_ID = "user_test_1"


@pytest_asyncio.fixture
async def session_factory():
    """Fresh schema per test on the database in DATABASE_URL. Skips if it is unreachable."""
    engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
    except Exception as exc:  # pragma: no cover - depends on the environment
        await engine.dispose()
        pytest.skip(f"PostgreSQL not available: {exc}")

    yield async_sessionmaker(bind=engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def db(session_factory):
    async with session_factory() as session:
        yield session


@pytest.fixture
def current_user():
    """Mutable holder: tests can switch the authenticated user with current_user['id'] = ..."""
    return {"id": TEST_USER_ID}


@pytest_asyncio.fixture
async def client(session_factory, current_user):
    async def override_get_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user_id] = lambda: current_user["id"]

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()
