"""Health & readiness endpoints (Fase 1 requirement).

/health/live  -> proses hidup (tidak cek dependensi).
/health/ready -> proses siap melayani; cek DB & Redis.
"""

from typing import Any

from fastapi import APIRouter, Response
from sqlalchemy import text

from app.dependencies import get_engine, get_redis

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live")
def live() -> dict[str, str]:
    """Liveness: process is up."""
    return {"status": "alive"}


@router.get("/ready")
def ready(response: Response) -> dict[str, Any]:
    """Readiness: DB and Redis reachable. Always returns 200 with per-check status."""
    checks: dict[str, str] = {}

    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:  # pragma: no cover - depends on infra
        checks["database"] = f"unavailable: {type(exc).__name__}"

    try:
        get_redis().ping()
        checks["redis"] = "ok"
    except Exception as exc:  # pragma: no cover - depends on infra
        checks["redis"] = f"unavailable: {type(exc).__name__}"

    ready_ok = all(v == "ok" for v in checks.values())
    response.status_code = 200 if ready_ok else 503
    return {"status": "ready" if ready_ok else "not_ready", "checks": checks}
