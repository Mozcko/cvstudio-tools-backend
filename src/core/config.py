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
    # Voice for the mock interview
    OPENAI_STT_MODEL: str = "gpt-4o-mini-transcribe"
    OPENAI_TTS_MODEL: str = "gpt-4o-mini-tts"
    OPENAI_TTS_VOICE: str = "sage"

    # Error reporting (optional). Without a DSN nothing is sent anywhere.
    SENTRY_DSN: str | None = None

    # Plans
    FREE_CV_LIMIT: int = 3
    # AI-assisted CV imports a non-Pro user gets in total (0 disables them)
    FREE_IMPORT_LIMIT: int = 2
    # Enhance / Optimize runs a non-Pro user gets per rolling 7 days (0 disables them)
    FREE_AI_WEEKLY_LIMIT: int = 3
    # Mock interviews a premium user may start (rolling 24 hours / 30 days; 0 disables that window)
    INTERVIEW_DAILY_LIMIT: int = 3
    INTERVIEW_MONTHLY_LIMIT: int = 30
    # Public links a non-Pro user may have switched on at once
    FREE_PUBLIC_LINK_LIMIT: int = 1
    # Key for the anonymous visitor identifier in view statistics. Optional: without it a
    # random key is used until the next restart, which only makes "unique visitors" less exact
    VIEW_HASH_SECRET: str | None = None

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
