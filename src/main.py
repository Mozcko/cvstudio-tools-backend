from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from src.core.config import settings
from src.api.routers import cv, webhooks, ai, billing, users
from src.db.database import engine, Base
from src.models import user, cv as cv_model, promo # Import models to register them with Base

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create tables on startup
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield

app = FastAPI(
    title=settings.PROJECT_NAME, 
    lifespan=lifespan,
    docs_url="/docs" if settings.ENVIRONMENT != "production" else None,
    redoc_url="/redoc" if settings.ENVIRONMENT != "production" else None,
    openapi_url="/openapi.json" if settings.ENVIRONMENT != "production" else None
)
# CORS Configuration
origins = [
    settings.FRONTEND_URL,
    "http://localhost:4321",
    "http://127.0.0.1:4321",
    "http://[::1]:4321",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
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

@app.get("/health")
async def health_check():
    return {"status": "healthy", "project": settings.PROJECT_NAME}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
