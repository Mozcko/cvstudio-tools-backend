import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.routers import (
    ai,
    billing,
    cv,
    interviews,
    links,
    public,
    recruiter_billing,
    screenings,
    users,
    webhooks,
)
from src.api.routers import promo as promo_router
from src.core.config import settings
from src.core.observability import init_error_reporting
from src.db.database import AsyncSessionLocal

logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

init_error_reporting()

logger = logging.getLogger(__name__)

# How often candidate data past its retention date is removed
PURGE_INTERVAL_SECONDS = 3600


async def purge_loop() -> None:
    """Removes expired screenings at start-up and then every hour, for as long as the API runs."""
    while True:
        try:
            async with AsyncSessionLocal() as session:
                removed = await screenings.purge_expired(session)
            if removed:
                logger.info("Removed %s expired screenings", removed)
        except Exception:
            # Never let a database hiccup end the loop: it would silently stop deleting data
            logger.exception("Could not purge expired screenings")
        await asyncio.sleep(PURGE_INTERVAL_SECONDS)


@asynccontextmanager
async def lifespan(_: FastAPI):
    task = asyncio.create_task(purge_loop())
    yield
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


# The schema is managed by Alembic (`alembic upgrade head`), not created at startup.
app = FastAPI(
    title=settings.PROJECT_NAME,
    lifespan=lifespan,
    docs_url="/docs" if settings.ENVIRONMENT != "production" else None,
    redoc_url="/redoc" if settings.ENVIRONMENT != "production" else None,
    openapi_url="/openapi.json" if settings.ENVIRONMENT != "production" else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

app.include_router(cv.router, prefix="/api/v1")
app.include_router(users.router, prefix="/api/v1")
app.include_router(webhooks.router, prefix="/api/v1")  # webhooks.router already has prefix="/webhooks"
app.include_router(ai.router, prefix="/api/v1")
app.include_router(billing.router, prefix="/api/v1")
app.include_router(interviews.router, prefix="/api/v1")
app.include_router(links.router, prefix="/api/v1")
app.include_router(public.router, prefix="/api/v1")
app.include_router(recruiter_billing.router, prefix="/api/v1")
app.include_router(screenings.router, prefix="/api/v1")
app.include_router(promo_router.router, prefix="/api/v1")


@app.get("/health")
async def health_check():
    return {"status": "healthy", "project": settings.PROJECT_NAME}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
