"""Registry job worker.

Semua task ingestion yang berat (parsing, OCR, transkripsi, embedding,
indexing) didefinisikan di sini sebagai fungsi idempotent.

Fase 1: registry + satu job contoh untuk membuktikan jalurnya bekerja.
Fase 4-5 mengganti stub ini dengan parser dan indexer sungguhan.
"""

import logging
from typing import Any

logger = logging.getLogger("worker.jobs")

JOBS = ["worker.jobs.ping"]


def ping(job_id: str | None = None) -> dict[str, Any]:
    """Job contoh untuk smoke test queue: menerima argumen, mengembalikan hasil."""
    logger.info("ping job executed", extra={"job_id": job_id})
    return {"ok": True, "job_id": job_id}
