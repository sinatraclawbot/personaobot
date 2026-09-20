from functools import lru_cache
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str = "postgresql+psycopg://platform:platform@localhost:5432/platform"
    app_url: str = "http://localhost:8000"
    environment: str = "development"
    cookie_secure: bool = False
    telegram_bot_token: str = ""
    telegram_webhook_secret: str = ""
    openai_api_key: str = ""
    openai_base_url: str = "https://openrouter.ai/api/v1"
    openai_model: str = "gpt-4.1-mini"
    vision_model: str = "openai/gpt-4o-mini"
    moderation_model: str = "omni-moderation-latest"
    session_hours: int = Field(default=12, ge=1, le=72)
    retention_days: int = Field(default=30, ge=1, le=365)
    job_max_attempts: int = Field(default=6, ge=1, le=20)
    worker_lease_seconds: int = Field(default=600, ge=300, le=3600)
    whatsapp_enabled: bool = False
    whatsapp_webhook_secret: str = ""
    whatsapp_bridge_url: str = "http://localhost:3001"

    @model_validator(mode="after")
    def production(self):
        for prefix in ("postgres://", "postgresql://"):
            if self.database_url.startswith(prefix):
                self.database_url = "postgresql+psycopg://" + self.database_url[len(prefix):]
                break
        if self.environment == "production":
            if not self.cookie_secure or not self.app_url.startswith("https://"):
                raise ValueError("Production requires HTTPS and secure cookies")
            if len(self.telegram_webhook_secret) < 32 or not self.telegram_bot_token or not self.openai_api_key:
                raise ValueError(
                    "Production requires Telegram and OpenAI credentials, and a 32+ character webhook secret"
                )
            if not self.database_url.startswith("postgresql"):
                raise ValueError("Production requires PostgreSQL")
        return self


@lru_cache
def settings():
    return Settings()
