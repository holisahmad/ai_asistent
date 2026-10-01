#!/usr/bin/env python
"""Hitung ulang embedding seluruh chunk (Fase 9/10 — maintenance).

Dipakai ketika algoritma/provider embedding berubah (mis. dari hash lama ke
bag-of-words) agar skor dense retrieval tetap konsisten dengan query yang
di-embed memakai kode terbaru. File tidak di-parse ulang: cukup dari
`document_chunks.content`, sehingga cepat dan tidak butuh object storage.

Pemakaian:
    uv run --project backend python scripts/reembed.py --check
    uv run --project backend python scripts/reembed.py
    uv run --project backend python scripts/reembed.py --workspace <WS_ID> [--batch 64]
"""

import argparse
import math
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))


def _parse_vec(literal: str) -> list[float]:
    """Parse literal pgvector '[1,2,3]' menjadi list float."""
    return [float(x) for x in literal.strip().strip("[]").split(",") if x]


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)


def main() -> int:
    parser = argparse.ArgumentParser(description="Hitung ulang embedding chunk")
    parser.add_argument("--workspace", help="batasi ke satu workspace_id")
    parser.add_argument("--batch", type=int, default=None, help="ukuran batch embedding")
    parser.add_argument(
        "--check",
        action="store_true",
        help="hanya laporkan kesesuaian vektor lama vs baru (non-destruktif)",
    )
    args = parser.parse_args()

    from sqlalchemy import text

    from ai_asistent_core.config import get_settings
    from ai_asistent_core.db import get_session_factory
    from ai_asistent_core.embeddings import embed_batch
    from ai_asistent_core.vecstore import get_vector_store

    s = get_settings()
    batch_size = args.batch or s.embedding_batch_size

    sql = "SELECT id, content, embedding::text AS emb FROM document_chunks"
    params: dict[str, str] = {}
    if args.workspace:
        sql += " WHERE workspace_id = :ws"
        params["ws"] = args.workspace
    sql += " ORDER BY id"

    session = get_session_factory()()
    processed = 0
    try:
        rows = session.execute(text(sql), params).mappings().all()
        if not rows:
            print("Tidak ada chunk untuk diproses.")
            return 0

        if args.check:
            sims: list[float] = []
            for row in rows:
                if not row["emb"]:
                    sims.append(0.0)
                    continue
                fresh = embed_batch([row["content"]])[0]
                sims.append(_cosine(_parse_vec(row["emb"]), fresh))
            stale = sum(1 for v in sims if v < 0.99)
            print(
                f"CHECK embedding: {len(rows)} chunk, provider={s.embedding_provider}, "
                f"dim={s.embedding_dim}"
            )
            print(
                f"  cosine lama-vs-baru: min={min(sims):.4f} "
                f"mean={sum(sims) / len(sims):.4f} max={max(sims):.4f}"
            )
            print(f"  perlu reembed (cosine < 0.99): {stale}/{len(rows)}")
            return 1 if stale else 0

        store = get_vector_store()
        for i in range(0, len(rows), batch_size):
            part = rows[i : i + batch_size]
            vectors = embed_batch([row["content"] for row in part])
            store.upsert(
                session,
                [
                    {"chunk_id": row["id"], "embedding": vec}
                    for row, vec in zip(part, vectors, strict=True)
                ],
            )
            session.commit()
            processed += len(part)
        print(
            f"Reembed selesai: {processed} chunk (provider={s.embedding_provider}, "
            f"dim={s.embedding_dim})."
        )
    finally:
        session.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
