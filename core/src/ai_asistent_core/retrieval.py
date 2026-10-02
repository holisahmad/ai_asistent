"""Retrieval hybrid (Fase 6): dense pgvector + keyword FTS, fusi skor.

ACL: setiap pencarian difilter `workspace_id` di level SQL — konteks tidak
pernah keluar dari workspace sebelum sampai ke LLM (roadmap: ACL sebelum
konteks diberikan ke LLM). Query rewriting opsional menyusul; fusi sederhana
deterministik (RRF + skor cosine) tanpa model eksternal, dilengkapi tahap
reranker opsional (`rerank.py`) yang menyusun ulang kandidat terfusi.
"""

import re
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session

from ai_asistent_core.config import get_settings
from ai_asistent_core.embeddings import embed_batch
from ai_asistent_core.rerank import rerank_candidates
from ai_asistent_core.vecstore import get_vector_store

# Bobot fusi: skor akhir = dense_weight * skor_dense_norm + keyword_weight * skor_kw_norm
DENSE_WEIGHT = 0.6
KEYWORD_WEIGHT = 0.4
RRF_K = 60  # konstanta Reciprocal Rank Fusion


@dataclass(frozen=True)
class RetrievedChunk:
    """Satu kandidat hasil retrieval dengan skor terfusi."""

    chunk_id: str
    file_id: str
    filename: str
    content: str
    locator_type: str
    locator_start: int
    locator_end: int
    dense_score: float  # 1 - cosine distance (0..1)
    keyword_score: float  # 0..1 (ts_rank/ILIKE dinormalisasi)
    score: float  # gabungan terbobot

    def snippet(self, max_chars: int = 280) -> str:
        """Potongan awal konteks untuk ditampilkan di sitasi."""
        flat = " ".join(self.content.split())
        if len(flat) <= max_chars:
            return flat
        return flat[:max_chars].rstrip() + "…"


def _keywords(query: str) -> list[str]:
    """Token kueri untuk keyword search (lowercase, panjang >= 2)."""
    return [t for t in re.findall(r"[a-z0-9]+", query.lower()) if len(t) >= 2]


def _keyword_search(
    db: Session, workspace_id: str, query: str, limit: int
) -> list[RetrievedChunk]:
    """FTS websearch_to_tsquery (fallback ILIKE OR). ACL: filter workspace_id."""
    kw = _keywords(query)
    if not kw:
        return []
    rows = db.execute(
        text(
            """
            SELECT c.id, c.file_id, COALESCE(f.filename, '') AS filename,
                   c.content, c.locator_type, c.locator_start, c.locator_end,
                   ts_rank(to_tsvector('simple', c.content),
                           websearch_to_tsquery('simple', :q)) AS rank
            FROM document_chunks c
            LEFT JOIN files f ON f.id = c.file_id
            WHERE c.workspace_id = :ws_id
              AND (
                to_tsvector('simple', c.content) @@ websearch_to_tsquery('simple', :q)
                OR c.content ILIKE :like
              )
            ORDER BY rank DESC, c.id
            LIMIT :limit
            """
        ),
        {"q": " OR ".join(kw), "like": f"%{kw[0]}%", "ws_id": workspace_id, "limit": limit},
    ).mappings().all()
    max_rank = max((float(r["rank"]) for r in rows), default=0.0)
    return [
        RetrievedChunk(
            chunk_id=r["id"],
            file_id=r["file_id"],
            filename=r["filename"],
            content=r["content"],
            locator_type=r["locator_type"],
            locator_start=r["locator_start"],
            locator_end=r["locator_end"],
            dense_score=0.0,
            keyword_score=(float(r["rank"]) / max_rank if max_rank > 0 else 0.0),
            score=0.0,
        )
        for r in rows
    ]


def _fuse(
    dense: list[RetrievedChunk], keyword: list[RetrievedChunk], min_score: float
) -> list[RetrievedChunk]:
    """Fusi deterministik: RRF per sumber + skor cosine dinormalisasi."""
    by_id: dict[str, RetrievedChunk] = {}
    for c in (*dense, *keyword):
        by_id[c.chunk_id] = c

    rrf_dense: dict[str, float] = {}
    rrf_kw: dict[str, float] = {}
    for pos, c in enumerate(dense):
        rrf_dense[c.chunk_id] = rrf_dense.get(c.chunk_id, 0.0) + 1.0 / (RRF_K + pos + 1)
    for pos, c in enumerate(keyword):
        rrf_kw[c.chunk_id] = rrf_kw.get(c.chunk_id, 0.0) + 1.0 / (RRF_K + pos + 1)
    max_rrf = max(
        max(rrf_dense.values(), default=0.0), max(rrf_kw.values(), default=0.0)
    ) or 1.0

    fused: list[RetrievedChunk] = []
    for cid, c in by_id.items():
        kw_norm = rrf_kw.get(cid, 0.0) / max_rrf
        score = DENSE_WEIGHT * c.dense_score + KEYWORD_WEIGHT * kw_norm
        if score >= min_score:
            fused.append(
                RetrievedChunk(
                    chunk_id=c.chunk_id,
                    file_id=c.file_id,
                    filename=c.filename,
                    content=c.content,
                    locator_type=c.locator_type,
                    locator_start=c.locator_start,
                    locator_end=c.locator_end,
                    dense_score=c.dense_score,
                    keyword_score=c.keyword_score,
                    score=score,
                )
            )
    fused.sort(key=lambda c: (-c.score, c.chunk_id))
    return fused


def retrieve(
    db: Session, workspace_id: str, question: str, top_k: int | None = None
) -> list[RetrievedChunk]:
    """Hybrid retrieval: dense + keyword → fusi → threshold → top_k."""
    s = get_settings()
    k = top_k if top_k is not None else s.retrieval_top_k
    n_candidates = s.retrieval_candidates

    # 1) Dense: embed pertanyaan, KNN cosine (ACL di SQL via vecstore).
    dense_matches = get_vector_store().search(
        db, workspace_id, embed_batch([question])[0], n_candidates
    )
    dense = [
        RetrievedChunk(
            chunk_id=m.chunk_id,
            file_id=m.file_id,
            filename=m.filename,
            content=m.content,
            locator_type=m.locator_type,
            locator_start=m.locator_start,
            locator_end=m.locator_end,
            dense_score=max(0.0, 1.0 - m.distance),
            keyword_score=0.0,
            score=0.0,
        )
        for m in dense_matches
    ]

    # 2) Keyword: FTS Postgres pada tabel chunk (ACL di SQL).
    keyword = _keyword_search(db, workspace_id, question, n_candidates)

    # 3) Fusi + threshold.
    fused = _fuse(dense, keyword, s.retrieval_min_score)

    # 4) Fallback deterministik: bila semua di bawah threshold tapi ada
    #    kandidat, ambil terbaik agar jelukan "hampir relevan" tetap ikut
    #    (LLM tetap bisa menyatakan NO_ANSWER bila isinya tak menjawab).
    if not fused and (dense or keyword):
        best = max(
            (dense or keyword),
            key=lambda c: c.score or c.dense_score or c.keyword_score,
        )
        fused = [best]

    # 5) Reranker opsional (Fase 1): urut ulang kandidat terfusi sebelum top_k.
    fused = rerank_candidates(question, fused)

    return fused[:k]
