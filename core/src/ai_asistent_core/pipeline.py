"""Pipeline ingestion file → documents → chunks → embeddings (Fase 4+5).

Idempoten: dijalankan ulang pada file yang sama menghapus dokumen &
chunk versi lama sebelum menulis ulang (roadmap: worker idempotent).
Modul ini di core agar backend (mode inline/test) dan worker (RQ)
menggunakan implementasi yang persis sama.
"""

import json
import logging
import re
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ai_asistent_core.chunking import chunk_sections
from ai_asistent_core.config import get_settings
from ai_asistent_core.embeddings import embed_batch
from ai_asistent_core.models import (
    Document,
    DocumentChunk,
    File,
    FileVersion,
    IngestionJob,
)
from ai_asistent_core.parsers import parse_file
from ai_asistent_core.storage import get_storage
from ai_asistent_core.vecstore import get_vector_store

logger = logging.getLogger("ai_asistent_core.pipeline")

# Karakter yang tidak boleh masuk PostgreSQL text field
_NUL_RE = re.compile(r"\x00")
_CONTROL_RE = re.compile(r"[\x01-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _sanitize_text(text: str) -> str:
    """Hapus NUL bytes dan karakter kontrol tidak valid dari teks.

    PostgreSQL text field menolak NUL (0x00). PDF/OCR kadang menghasilkan
    karakter kontrol lain yang juga tidak berguna untuk RAG.
    - \\x00 : NUL — dihapus sepenuhnya
    - \\x01-\\x08, \\x0b, \\x0c, \\x0e-\\x1f, \\x7f : kontrol C0 (bukan tab/LF/CR)
      → diganti spasi agar kata tidak menempel
    """
    text = _NUL_RE.sub("", text)
    text = _CONTROL_RE.sub(" ", text)
    # Normalisasi whitespace berlebih yang muncul akibat substitusi
    text = re.sub(r"  +", " ", text)
    return text


def _now() -> datetime:
    return datetime.now(UTC)


def _fail(db: Session, file_row: File, job: IngestionJob, message: str) -> None:
    """Tandai file & job gagal."""
    file_row.status = "failed"
    file_row.error = message[:500]
    job.status = "failed"
    job.error = message[:500]
    job.finished_at = _now()
    logger.warning("ingest failed: file=%s err=%s", file_row.id, message)


def ingest_file(db: Session, file_id: str, job_id: str) -> str:
    """Pipeline utama: parse → chunk → embed → index. Return status akhir."""
    get_settings()
    file_row = db.get(File, file_id)
    job = db.get(IngestionJob, job_id)
    if file_row is None or job is None:
        logger.error("file atau job tidak ditemukan: %s/%s", file_id, job_id)
        return "failed"

    # Cancelled oleh user sebelum sempat jalan?
    if file_row.status not in ("queued", "failed"):
        job.status = "cancelled"
        job.finished_at = _now()
        return "cancelled"

    file_row.status = "processing"
    job.status = "running"
    job.started_at = _now()
    db.commit()

    try:
        version_row = db.execute(
            select(FileVersion).where(
                FileVersion.file_id == file_id,
                FileVersion.version == file_row.current_version,
            )
        ).scalar_one()

        # 1) Ambil binary dari object storage
        data = get_storage().get(version_row.storage_key)

        # 2) Parse per format dengan locator
        parsed = parse_file(file_row.filename, data)

        # 3) Chunk token-aware
        chunks = chunk_sections(parsed.sections)

        # 4) Idempoten: hapus dokumen/chunk versi sebelumnya untuk file ini
        for old in db.execute(
            select(Document).where(Document.file_id == file_id)
        ).scalars().all():
            db.delete(old)
        db.flush()

        # 5) Simpan document + chunks (embedding menyusul batch)
        document = Document(
            file_id=file_id,
            version=file_row.current_version,
            workspace_id=file_row.workspace_id,
            source_format=parsed.source_format,
            title=_sanitize_text(parsed.title or file_row.filename),
            locator_type=(chunks[0].locator_type if chunks else "char"),
            char_count=sum(len(s.text) for s in parsed.sections),
            parser_meta_json=json.dumps(parsed.meta, ensure_ascii=False),
        )
        db.add(document)
        db.flush()

        chunk_rows = [
            DocumentChunk(
                document_id=document.id,
                workspace_id=file_row.workspace_id,
                file_id=file_id,
                version=file_row.current_version,
                seq=i,
                content=_sanitize_text(c.content),
                char_start=c.char_start,
                char_end=c.char_end,
                locator_type=c.locator_type,
                locator_start=c.locator_start,
                locator_end=c.locator_end,
            )
            for i, c in enumerate(chunks)
        ]
        db.add_all(chunk_rows)
        db.flush()

        # 6) Embedding batch + upsert ke pgvector — dilakukan per-batch
        #    agar tidak OOM pada file besar (PDF 10MB+ bisa 200+ chunks).
        if chunk_rows:
            EMBED_CHUNK = 8  # embed 8 chunks sekali, upsert langsung, bebaskan memory
            vs = get_vector_store()
            for batch_start in range(0, len(chunk_rows), EMBED_CHUNK):
                batch = chunk_rows[batch_start : batch_start + EMBED_CHUNK]
                vectors = embed_batch([c.content for c in batch])
                vs.upsert(
                    db,
                    [
                        {"chunk_id": row.id, "embedding": vec}
                        for row, vec in zip(batch, vectors, strict=True)
                    ],
                )
                # Commit per-batch agar tidak hold transaksi terlalu lama
                db.flush()

        # 7) Selesai
        file_row.status = "indexed"
        file_row.error = None
        job.status = "done"
        job.finished_at = _now()
        db.commit()
        logger.info(
            "ingested file=%s fmt=%s chunks=%d", file_id, parsed.source_format, len(chunk_rows)
        )
        return "indexed"

    except Exception as exc:  # noqa: BLE001 - worker tidak boleh crash
        db.rollback()
        # Re-attach setelah rollback untuk menandai gagal
        file_row = db.get(File, file_id)
        job = db.get(IngestionJob, job_id)
        if file_row is not None and job is not None:
            _fail(db, file_row, job, f"{type(exc).__name__}: {exc}")
            db.commit()
        return "failed"
