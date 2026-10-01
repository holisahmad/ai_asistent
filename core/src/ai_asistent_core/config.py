"""Konfigurasi bersama (workspace-level) untuk backend & worker."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_ROOT_ENV = Path(__file__).resolve().parents[3] / ".env"


class CoreSettings(BaseSettings):
    """Konfigurasi inti yang dipakai API & worker."""

    model_config = SettingsConfigDict(
        env_file=_ROOT_ENV if _ROOT_ENV.exists() else None,
        env_prefix="APP_",
        extra="ignore",
    )

    environment: str = "development"
    log_level: str = "INFO"
    database_url: str = "postgresql+psycopg://ai_assistant:ai_assistant@localhost:5433/ai_assistant"
    redis_url: str = "redis://localhost:6380/0"
    queue_name: str = "default"

    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_bucket: str = "ai-assistant"
    minio_secure: bool = False

    max_upload_bytes: int = 100 * 1024 * 1024
    presign_expiry_seconds: int = 900

    # CORS untuk frontend (CSV origin; dipakai backend)
    cors_origins_csv: str = "http://localhost:3000"

    # File JSONL backup untuk audit trail (opsional; kosong = disable)
    audit_log_file: str | None = None

    # Fase 4/5: pipeline ingestion & indexing
    chunk_target_tokens: int = 512
    chunk_overlap_tokens: int = 64
    embedding_dim: int = 384
    embedding_batch_size: int = 32
    embedding_provider: str = "local"  # local | openai
    openai_api_key: str | None = None
    openai_embedding_model: str = "text-embedding-3-small"

    # Fase 6: retrieval & RAG
    retrieval_top_k: int = 6
    retrieval_candidates: int = 24
    retrieval_min_score: float = 0.05
    llm_provider: str = "local"  # local | openai | openai_compat
    openai_chat_model: str = "gpt-4o-mini"
    # Endpoint OpenAI-compatible (vLLM/Combo/gateway lokal); kosong = api.openai.com
    openai_base_url: str | None = None
    openai_timeout_seconds: float = 60.0
    rag_max_context_chars: int = 6000

    # Fase 7: web fallback
    web_fallback_mode: str = "internal_only"  # internal_only | internal_plus_web
    web_search_provider: str = "none"  # none | duckduckgo | searx | tavily
    web_search_base_url: str | None = None  # untuk searx (mis. http://searx:8080)
    tavily_api_key: str | None = None
    web_search_timeout_seconds: float = 8.0
    web_search_max_results: int = 5
    web_search_rate_limit_per_min: int = 10
    # CSV domain (kosong = semua diizinkan); denylist menang atas allowlist
    web_search_domain_allowlist_csv: str = ""
    web_search_domain_denylist_csv: str = ""

    @property
    def database_url_sync(self) -> str:
        """Alias kompatibilitas (psycopg sync dipakai langsung)."""
        return self.database_url


@lru_cache
def get_settings() -> CoreSettings:
    """Return cached settings singleton."""
    return CoreSettings()  # pragma: no cover - trivial


def csv_list(value: str) -> list[str]:
    """Pecah CSV sederhana menjadi list bersih (untuk allowlist/denylist)."""
    return [item.strip().lower() for item in value.split(",") if item.strip()]
