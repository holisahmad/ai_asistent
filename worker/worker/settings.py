"""Worker settings (independen dari backend agar dapat di-deploy terpisah)."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# .env di root project (../ dari worker/)
_ROOT_ENV = Path(__file__).resolve().parents[3] / ".env"


class Settings(BaseSettings):
    """Strongly-typed worker configuration."""

    model_config = SettingsConfigDict(
        env_file=_ROOT_ENV if _ROOT_ENV.exists() else None,
        env_prefix="APP_",
        extra="ignore",
    )

    environment: str = "development"
    log_level: str = "INFO"
    redis_url: str = "redis://localhost:6380/0"
    queue_name: str = "default"


@lru_cache
def get_settings() -> Settings:
    """Return cached settings singleton."""
    return Settings()
