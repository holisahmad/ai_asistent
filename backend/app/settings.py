"""Application settings via pydantic-settings.

Semua config dibaca dari environment / file .env di root project.
Tidak ada secret yang di-commit.
"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# .env di root project (../ dari backend/)
_ROOT_ENV = Path(__file__).resolve().parents[3] / ".env"


class Settings(BaseSettings):
    """Strongly-typed application configuration."""

    model_config = SettingsConfigDict(
        env_file=_ROOT_ENV if _ROOT_ENV.exists() else None,
        env_prefix="APP_",
        extra="ignore",
    )

    environment: str = "development"
    log_level: str = "INFO"

    database_url: str = "postgresql+psycopg://ai_assistant:ai_assistant@localhost:5433/ai_assistant"
    redis_url: str = "redis://localhost:6380/0"

    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_bucket: str = "ai-assistant"
    minio_secure: bool = False


@lru_cache
def get_settings() -> Settings:
    """Return cached settings singleton."""
    return Settings()
