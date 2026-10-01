"""Konteks request (Fase 9): correlation ID untuk log, audit, dan metrik."""

from contextvars import ContextVar

request_id_ctx: ContextVar[str] = ContextVar("request_id", default="-")


def current_request_id() -> str:
    """Request ID aktif (dipakai log & audit)."""
    return request_id_ctx.get()
