"""Endpoint operasional (Fase 9): metrik Prometheus.

`GET /metrics` mengembalikan metrik in-process. Bila `APP_METRICS_TOKEN`
diset, endpoint mensyaratkan `Authorization: Bearer <token>` sehingga aman
diekspos di jaringan produksi.
"""

from typing import Annotated

from ai_asistent_core.config import get_settings
from fastapi import APIRouter, Header, HTTPException, status
from fastapi.responses import PlainTextResponse

from app import __version__
from app.observability import metrics_response

router = APIRouter(tags=["ops"])


@router.get("/metrics", response_class=PlainTextResponse)
def metrics(
    authorization: Annotated[str | None, Header()] = None,
) -> PlainTextResponse:
    """Metrik format Prometheus text exposition."""
    token = get_settings().metrics_token
    if token and authorization != f"Bearer {token}":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Metrics token tidak valid")
    return metrics_response()


@router.get("/version")
def version() -> dict[str, str]:
    """Versi aplikasi (untuk deployment & rollback tracking)."""
    return {"version": __version__, "environment": get_settings().environment}


@router.get("/config-check")
def config_check() -> dict[str, str]:
    """Non-sensitive runtime config (untuk troubleshoot deployment)."""
    s = get_settings()
    return {
        "llm_provider": s.llm_provider,
        "openai_chat_model": s.openai_chat_model,
        "openai_base_url": s.openai_base_url or "(not set)",
        "openai_api_key_set": "yes" if s.openai_api_key else "no",
        "embedding_provider": s.embedding_provider,
        "environment": s.environment,
    }
