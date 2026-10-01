"""Vector store adapter — pgvector di atas tabel document_chunks.

Isolasi penuh (roadmap Fase 5): bila nanti pindah ke Qdrant, cukup
tulis implementasi baru dari `VectorStoreProtocol` tanpa mengubah
pipeline worker maupun retrieval.
"""

from dataclasses import dataclass
from typing import Any, Protocol

from sqlalchemy import text
from sqlalchemy.orm import Session

from ai_asistent_core.config import get_settings


@dataclass(frozen=True)
class VectorMatch:
    """Hasil pencarian vektor (dengan filename untuk sitasi)."""

    chunk_id: str
    file_id: str
    document_id: str
    content: str
    locator_type: str
    locator_start: int
    locator_end: int
    distance: float
    filename: str = ""


class VectorStoreProtocol(Protocol):
    """Kontrak vector store."""

    def upsert(self, db: Session, rows: list[dict[str, Any]]) -> None: ...
    def search(
        self, db: Session, workspace_id: str, query_vector: list[float], top_k: int
    ) -> list[VectorMatch]: ...
    def delete_by_file(self, db: Session, file_id: str, version: int | None = None) -> int: ...


def _vec_literal(vector: list[float]) -> str:
    """Literal pgvector '[1,2,3]' dari list float."""
    return "[" + ",".join(f"{v:.7f}" for v in vector) + "]"


class PgVectorStore:
    """Implementasi pgvector."""

    def upsert(self, db: Session, rows: list[dict[str, Any]]) -> None:
        """Simpan embedding chunk (update yang ada, sisipkan baru)."""
        for row in rows:
            db.execute(
                text(
                    "UPDATE document_chunks SET embedding = CAST(:vec AS vector) "
                    "WHERE id = :chunk_id"
                ),
                {"vec": _vec_literal(row["embedding"]), "chunk_id": row["chunk_id"]},
            )

    def search(
        self, db: Session, workspace_id: str, query_vector: list[float], top_k: int
    ) -> list[VectorMatch]:
        """K-NN cosine distance dalam satu workspace (ACL di level query)."""
        rows = db.execute(
            text(
                """
                SELECT c.id, c.file_id, c.document_id, c.content, c.locator_type,
                       c.locator_start, c.locator_end,
                       c.embedding <=> CAST(:vec AS vector) AS distance,
                       COALESCE(f.filename, '') AS filename
                FROM document_chunks c
                LEFT JOIN files f ON f.id = c.file_id
                WHERE c.workspace_id = :ws_id AND c.embedding IS NOT NULL
                ORDER BY c.embedding <=> CAST(:vec AS vector)
                LIMIT :k
                """
            ),
            {"vec": _vec_literal(query_vector), "ws_id": workspace_id, "k": top_k},
        ).mappings().all()
        return [
            VectorMatch(
                chunk_id=r["id"],
                file_id=r["file_id"],
                document_id=r["document_id"],
                content=r["content"],
                locator_type=r["locator_type"],
                locator_start=r["locator_start"],
                locator_end=r["locator_end"],
                distance=float(r["distance"]),
                filename=r["filename"],
            )
            for r in rows
        ]

    def delete_by_file(self, db: Session, file_id: str, version: int | None = None) -> int:
        """Hapus embedding lama (dipakai saat reindex)."""
        sql = "DELETE FROM document_chunks WHERE file_id = :fid"
        params: dict[str, Any] = {"fid": file_id}
        if version is not None:
            sql += " AND version = :ver"
            params["ver"] = version
        result: Any = db.execute(text(sql), params)
        return int(result.rowcount or 0)


_store: PgVectorStore | None = None


def get_vector_store() -> PgVectorStore:
    """Singleton vector store (pgvector)."""
    global _store
    if _store is None:
        _ = get_settings()
        _store = PgVectorStore()
    return _store
