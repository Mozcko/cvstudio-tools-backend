from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


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
    CLERK_WEBHOOK_SECRET: str | None = None
    # Comma-separated origins allowed in the token's `azp` claim. Defaults to the CORS origins.
    CLERK_AUTHORIZED_PARTIES: str | None = None

    @field_validator("CLERK_ISSUER")
    @classmethod
    def normalize_issuer(cls, v: str) -> str:
        v = (v or "").strip().rstrip("/")
        if not v.startswith("https://"):
            raise ValueError("CLERK_ISSUER must be the https:// Frontend API URL of your Clerk instance")
        return v

    # Stripe
    STRIPE_API_KEY: str | None = None
    STRIPE_WEBHOOK_SECRET: str | None = None
    STRIPE_PRICE_7D: str | None = None
    STRIPE_PRICE_30D: str | None = None
    STRIPE_PRICE_LIFETIME: str | None = None

    # AI
    OPENAI_API_KEY: str | None = None
    OPENAI_MODEL: str = "gpt-4o-mini"
    AI_RATE_LIMIT_PER_HOUR: int = 20
    AI_RATE_LIMIT_PER_DAY: int = 100

    # Error reporting (optional). Without a DSN nothing is sent anywhere.
    SENTRY_DSN: str | None = None

    # Plans
    FREE_CV_LIMIT: int = 3

    # Frontend
    FRONTEND_URL: str = "http://localhost:4321"

    @property
    def allowed_origins(self) -> list[str]:
        origins = [
            self.FRONTEND_URL.rstrip("/"),
            "http://localhost:4321",
            "http://127.0.0.1:4321",
            "http://[::1]:4321",
        ]
        return list(dict.fromkeys(origins))

    @property
    def authorized_parties(self) -> list[str]:
        if self.CLERK_AUTHORIZED_PARTIES:
            return [p.strip().rstrip("/") for p in self.CLERK_AUTHORIZED_PARTIES.split(",") if p.strip()]
        return self.allowed_origins

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
