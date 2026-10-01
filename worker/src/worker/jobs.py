"""Registry job RQ — fungsi dipanggil worker dengan nama string."""

import json
import logging
from collections.abc import Callable
from typing import Any

from ai_asistent_core.db import get_session_factory

logger = logging.getLogger("worker.jobs")

JOBS = ["worker.jobs.ingest"]


def ingest(file_id: str, job_id: str) -> dict[str, Any]:
    """Job RQ: jalankan pipeline ingestion dengan session sendiri."""
    session = get_session_factory()()
    try:
        status = _run_ingest(session, file_id, job_id)
        session.commit()
        return {"file_id": file_id, "job_id": job_id, "status": status}
    finally:
        session.close()


def _run_ingest(session: Any, file_id: str, job_id: str) -> str:
    from worker.pipeline import ingest_file

    return ingest_file(session, file_id, job_id)


def audit_log(action: str, **payload: Any) -> None:
    """Backup audit JSONL dari worker (opsional, untuk operasi)."""
    logger.info("audit %s %s", action, json.dumps(payload, default=str))


def get_callable(name: str) -> Callable[..., Any]:
    """Resolve nama job → fungsi (mencegah import arbitrer)."""
    registry: dict[str, Callable[..., Any]] = {"worker.jobs.ingest": ingest}
    fn = registry.get(name)
    if fn is None:
        raise KeyError(f"Unknown job: {name}")
    return fn
