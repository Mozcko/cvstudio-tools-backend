import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.routers import ai, billing, cv, interviews, users, webhooks
from src.api.routers import promo as promo_router
from src.core.config import settings
from src.core.observability import init_error_reporting

logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

init_error_reporting()

# The schema is managed by Alembic (`alembic upgrade head`), not created at startup.
app = FastAPI(
    title=settings.PROJECT_NAME,
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
app.include_router(promo_router.router, prefix="/api/v1")


@app.get("/health")
async def health_check():
    return {"status": "healthy", "project": settings.PROJECT_NAME}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
