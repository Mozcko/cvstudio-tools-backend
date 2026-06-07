from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator
from typing import Optional

class Settings(BaseSettings):
    PROJECT_NAME: str = "CV Studio Tools API"
    ENVIRONMENT: str = "development"
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
    CLERK_API_KEY: Optional[str] = None
    
    # Stripe
    STRIPE_API_KEY: Optional[str] = None
    STRIPE_WEBHOOK_SECRET: Optional[str] = None
    STRIPE_PRICE_7D: Optional[str] = None
    STRIPE_PRICE_30D: Optional[str] = None
    STRIPE_PRICE_LIFETIME: Optional[str] = None
    
    # AI (DeepSeek & OpenAI)
    DEEPSEEK_API_KEY: Optional[str] = None
    DEEPSEEK_BASE_URL: str = "https://api.deepseek.com"
    OPENAI_API_KEY: Optional[str] = None

    # Frontend
    FRONTEND_URL: str = "http://localhost:4321"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()
