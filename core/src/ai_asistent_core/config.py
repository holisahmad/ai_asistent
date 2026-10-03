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

    # Fase 9: ketahanan panggilan eksternal
    external_max_attempts: int = 3
    external_retry_base_seconds: float = 0.5
    external_retry_max_seconds: float = 8.0
    breaker_failure_threshold: int = 5
    breaker_recovery_seconds: float = 60.0

    # Fase 9: perlindungan API
    api_rate_limit_per_min: int = 120  # per user/token; 0 = nonaktif
    api_rate_limit_burst: int = 0  # tambahan kuota sekali jalan (0 = tanpa burst)
    metrics_token: str | None = None  # bila diset, /metrics butuh Bearer token ini
    request_id_header: str = "X-Request-ID"

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
    # Fase 1 upgrade: reranker penyusun ulang kandidat retrieval.
    # Aktif sejak terbukti menaikkan kualitas pada dataset headroom
    # (recall@5 0.9→1.0, MRR 0.80→0.88, sitasi 0.7→0.8) tanpa regresi di
    # dataset gate — lihat docs/UPGRADE_PLAN.md. Set false bila perlu
    # mengembalikan perilaku lama (urutan murni fusi).
    reranker_enabled: bool = True
    reranker_provider: str = "lexical"  # lexical | none
    reranker_top_n: int = 0  # batas kandidat depan yang diurut ulang; 0 = semua
    llm_provider: str = "local"  # local | openai | openai_compat
    openai_chat_model: str = "gpt-4o-mini"
    # Endpoint OpenAI-compatible (vLLM/Combo/gateway lokal); kosong = api.openai.com
    openai_base_url: str | None = None
    openai_timeout_seconds: float = 60.0
    rag_max_context_chars: int = 6000

    # Fase 2 upgrade: mode jawaban ekstraktif vs generatif.
    # answer_mode: "generative" (default lama) | "extractive" | "auto"
    #   - generative  : selalu pakai LLM untuk merangkum konteks (perilaku lama).
    #   - extractive  : bila kepercayaan leksikal cukup, kembalikan cuplikan
    #                   terbaik tanpa memanggil LLM (hemat token & latensi).
    #   - auto        : ekstraktif dulu; bila skor < answer_extractive_threshold
    #                   atau margin antar-kandidat < answer_min_margin, jatuh
    #                   ke generatif.
    answer_mode: str = "generative"
    # Ambang skor LexicalConfidence minimum agar mode ekstraktif aktif.
    answer_extractive_threshold: float = 0.55
    # Margin minimum antara skor chunk terbaik dan kedua terbaik; margin kecil
    # berarti dua dokumen sama-sama relevan → generatif lebih aman.
    answer_min_margin: float = 0.10
    # Panjang maksimum cuplikan ekstraktif (karakter); 0 = tidak dipotong.
    answer_max_chars: int = 600

    # Fase 3 upgrade: query rewriting berbasis aturan.
    # Buang frasa meta (carikan, tolong, di internet) + ekspansi sinonim.
    # Default: false (off) — uplift harus terukur sebelum diaktifkan.
    query_rewrite_enabled: bool = False

    # Fase 4 upgrade: SSRF-safe fetch + URL validation.
    # Validasi URL sebelum HTTP request: whitelist skema, tolak private IP,
    # validasi redirect, batas size/timeout/content-type.
    # Default: true (always on untuk web fallback).
    url_validation_enabled: bool = True
    # Max bytes untuk fetch page; default 200KB
    url_fetch_max_bytes: int = 200_000
    # Regex URL denylist (dipisah |); kosong = none
    url_denylist_regex: str = ""
    # Regex URL allowlist (dipisah |); kosong = all (setelah private IP check)
    url_allowlist_regex: str = ""

    # Fase 5 upgrade: external reader adapter (URL → content dengan provenance).
    # Provider: http (default, HttpReader + safefetch) | firecrawl (future) | jina (future)
    web_reader: str = "http"
    # Timeout untuk external reader fetch (seconds)
    web_reader_timeout_seconds: float = 8.0

    # Fase 6 upgrade: document parser gateway + optional Docling (conditional).
    # Parser: builtin (default, pypdf/python-docx/etc) | docling (layout analysis, heavy)
    # Docling is optional dependency; only loaded if explicitly enabled.
    # Requires: pip install docling (torch-based, ~500MB, not in default dependencies)
    document_parser: str = "builtin"
    # Fallback provider (reserved for future; currently unused)
    document_fallback: str | None = None

    # Fase 7: web fallback
    web_fallback_mode: str = "internal_only"  # internal_only | internal_plus_web
    web_search_provider: str = "none"  # none | bing_rss | duckduckgo | searx | tavily
    # Provider cadangan (CSV) yang dicoba bila provider utama error atau
    # hasilnya semua di bawah web_evidence_min_relevance — mesin pencari bisa
    # berubah-ubah per jaringan, jadi rantai ini menjaga fallback tetap berguna.
    web_search_fallback_providers_csv: str = ""
    web_search_base_url: str | None = None  # untuk searx (mis. http://searx:8080)
    tavily_api_key: str | None = None
    web_search_timeout_seconds: float = 8.0
    web_search_max_results: int = 5
    # Market/locale untuk Bing RSS (mkt + setlang) — membiaskan hasil ke
    # bahasa/negara kueri, penting untuk kueri Bahasa Indonesia.
    web_search_market: str = "id-ID"
    web_search_rate_limit_per_min: int = 10
    # CSV domain (kosong = semua diizinkan); denylist menang atas allowlist
    web_search_domain_allowlist_csv: str = ""
    web_search_domain_denylist_csv: str = ""
    # Ambang kecukupan bukti web (Fase 7/9): hanya hasil dengan skor relevansi
    # >= ambang yang dipakai, dan bila yang lolos < web_evidence_min_results,
    # fallback web dianggap tak cukup → no_answer (tidak menyuntik konteks lemah).
    web_evidence_min_relevance: float = 0.34
    web_evidence_min_results: int = 1

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
