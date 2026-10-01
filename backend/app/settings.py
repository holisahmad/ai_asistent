"""Application settings via pydantic-settings.

Semua config dibaca dari environment / file .env di root project.
Tidak ada secret yang di-commit.
"""

from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
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

    # File JSONL backup untuk audit trail (opsional; kosong = disable)
    audit_log_file: str | None = None

    # Batas upload (Fase 3)
    max_upload_bytes: int = 100 * 1024 * 1024  # 100 MB
    presign_expiry_seconds: int = 900  # umur signed URL: 15 menit

    @field_validator("max_upload_bytes", "presign_expiry_seconds")
    @classmethod
    def _positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("harus > 0")
        return v


@lru_cache
def get_settings() -> Settings:
    """Return cached settings singleton."""
    return Settings()
