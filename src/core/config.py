from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator
from typing import List, Optional

class Settings(BaseSettings):
    PROJECT_NAME: str = "CV Studio Tools API"
    ENVIRONMENT: str = "development"
    DEBUG: bool = False
    DATABASE_URL: str

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def assemble_db_connection(cls, v: str) -> str:
        if v and v.startswith("postgres://"):
            return v.replace("postgres://", "postgresql+asyncpg://", 1)
        if v and v.startswith("postgresql://") and "+asyncpg" not in v:
            return v.replace("postgresql://", "postgresql+asyncpg://", 1)
        return v

    # Clerk
    # Frontend API URL of the Clerk instance, e.g. https://your-app.clerk.accounts.dev
    # Required: session tokens are verified against {CLERK_ISSUER}/.well-known/jwks.json
    CLERK_ISSUER: str
    CLERK_WEBHOOK_SECRET: Optional[str] = None
    # Comma-separated origins allowed in the token's `azp` claim. Defaults to the CORS origins.
    CLERK_AUTHORIZED_PARTIES: Optional[str] = None

    @field_validator("CLERK_ISSUER")
    @classmethod
    def normalize_issuer(cls, v: str) -> str:
        v = (v or "").strip().rstrip("/")
        if not v.startswith("https://"):
            raise ValueError("CLERK_ISSUER must be the https:// Frontend API URL of your Clerk instance")
        return v

    # Stripe
    STRIPE_API_KEY: Optional[str] = None
    STRIPE_WEBHOOK_SECRET: Optional[str] = None
    STRIPE_PRICE_7D: Optional[str] = None
    STRIPE_PRICE_30D: Optional[str] = None
    STRIPE_PRICE_LIFETIME: Optional[str] = None

    # AI
    OPENAI_API_KEY: Optional[str] = None
    OPENAI_MODEL: str = "gpt-4o-mini"
    AI_RATE_LIMIT_PER_HOUR: int = 20
    AI_RATE_LIMIT_PER_DAY: int = 100

    # Plans
    FREE_CV_LIMIT: int = 3

    # Frontend
    FRONTEND_URL: str = "http://localhost:4321"

    @property
    def allowed_origins(self) -> List[str]:
        origins = [
            self.FRONTEND_URL.rstrip("/"),
            "http://localhost:4321",
            "http://127.0.0.1:4321",
            "http://[::1]:4321",
        ]
        return list(dict.fromkeys(origins))

    @property
    def authorized_parties(self) -> List[str]:
        if self.CLERK_AUTHORIZED_PARTIES:
            return [p.strip().rstrip("/") for p in self.CLERK_AUTHORIZED_PARTIES.split(",") if p.strip()]
        return self.allowed_origins

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()
