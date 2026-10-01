"""Enqueue job RQ dari backend.

Graceful degradation: bila Redis tidak tersedia, upload tetap sukses
(status `queued`); job bisa dipicu ulang via reindex. Worker yang jalan
nanti akan mengambil job dari queue.
"""

import logging

from ai_asistent_core.config import get_settings
from ai_asistent_core.db import get_rq_connection
from rq import Retry

logger = logging.getLogger("app.queue")


def enqueue_ingest(file_id: str, job_id: str) -> bool:
    """Kirim job ingest ke Redis; return True bila berhasil mengantre."""
    get_settings()
    try:
        from rq import Queue

        queue = Queue("default", connection=get_rq_connection())
        queue.enqueue(
            "worker.jobs.ingest",
            file_id,
            job_id,
            retry=Retry(max=3, interval=[5, 15, 60]),
            job_timeout=600,
        )
        return True
    except Exception as exc:  # noqa: BLE001 - Redis down tidak boleh gagalkan upload
        logger.warning("enqueue gagal (file=%s): %s: %s", file_id, type(exc).__name__, exc)
        return False
