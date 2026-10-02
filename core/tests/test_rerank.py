"""Test Fase 1 upgrade — reranker: determinisme, IDF, top_n, identitas."""

import pytest

from ai_asistent_core.config import get_settings
from ai_asistent_core.rerank import (
    LexicalReranker,
    NoReranker,
    get_reranker,
    rerank_candidates,
)
from ai_asistent_core.retrieval import RetrievedChunk


def _chunk(cid: str, content: str, score: float, filename: str = "dokumen.md") -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=cid,
        file_id=f"file-{cid}",
        filename=filename,
        content=content,
        locator_type="char",
        locator_start=0,
        locator_end=len(content),
        dense_score=score,
        keyword_score=0.0,
        score=score,
    )


def _enable(monkeypatch: pytest.MonkeyPatch, *, provider: str = "lexical", top_n: int = 0) -> None:
    monkeypatch.setattr(get_settings(), "reranker_enabled", True)
    monkeypatch.setattr(get_settings(), "reranker_provider", provider)
    monkeypatch.setattr(get_settings(), "reranker_top_n", top_n)


def test_disabled_keeps_original_order(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default nonaktif: urutan fusi tidak tersentuh sama sekali."""
    monkeypatch.setattr(get_settings(), "reranker_enabled", False)
    chunks = [
        _chunk("distractor", "biaya kantor karyawan", 0.9),
        _chunk("target", "biaya kesehatan karyawan ditanggung perusahaan jaminan", 0.5),
    ]
    out = rerank_candidates("biaya kesehatan", chunks)
    assert [c.chunk_id for c in out] == ["distractor", "target"]


def test_provider_none_is_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "reranker_enabled", True)
    monkeypatch.setattr(get_settings(), "reranker_provider", "none")
    chunks = [
        _chunk("distractor", "biaya kantor karyawan", 0.9),
        _chunk("target", "biaya kesehatan karyawan ditanggung perusahaan jaminan", 0.5),
    ]
    out = rerank_candidates("biaya kesehatan", chunks)
    assert [c.chunk_id for c in out] == ["distractor", "target"]


def test_lexical_reranker_prefers_rare_term_over_fusion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """IDF menang: dokumen dengan istilah jarah mengalahkan yang menumpuk kata umum.

    Distraktor memimpin di skor fusi (0.9 vs 0.5) tetapi hanya memuat kata umum
    (df tinggi), sedangkan target memuat `kesehatan` (df 1 → idf besar).
    """
    _enable(monkeypatch)
    chunks = [
        _chunk("distractor", "biaya kantor karyawan", 0.9),
        _chunk("target", "biaya kesehatan karyawan ditanggung perusahaan jaminan", 0.5),
    ]
    out = rerank_candidates("biaya kesehatan", chunks)
    assert [c.chunk_id for c in out] == ["target", "distractor"]


def test_scores_are_not_rewritten(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reranker hanya mengubah urutan; `score` tetap skor fusi retrieval."""
    _enable(monkeypatch)
    chunks = [
        _chunk("distractor", "biaya kantor karyawan", 0.9),
        _chunk("target", "biaya kesehatan karyawan ditanggung perusahaan jaminan", 0.5),
    ]
    out = rerank_candidates("biaya kesehatan", chunks)
    by_id = {c.chunk_id: c.score for c in out}
    assert by_id == {"distractor": 0.9, "target": 0.5}


def test_no_candidates_too_few_returns_same(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable(monkeypatch)
    single = [_chunk("only", "biaya kesehatan", 0.4)]
    assert rerank_candidates("biaya kesehatan", single) == single
    assert rerank_candidates("biaya kesehatan", []) == []


def test_ties_keep_original_order(monkeypatch: pytest.MonkeyPatch) -> None:
    """Skor identik → urutan asli dipertahankan (sort stabil, tanpa regresi)."""
    _enable(monkeypatch)
    same = "biaya kesehatan karyawan ditanggung perusahaan jaminan"
    chunks = [_chunk("a", same, 0.5), _chunk("b", same, 0.5), _chunk("c", same, 0.5)]
    out = rerank_candidates("biaya kesehatan", chunks)
    assert [c.chunk_id for c in out] == ["a", "b", "c"]


def test_top_n_limits_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    """reranker_top_n hanya mengurut ulang kepala; ekor tetap di posisinya."""
    _enable(monkeypatch, top_n=2)
    chunks = [
        _chunk("distractor", "biaya kantor karyawan", 0.9),
        _chunk("target", "biaya kesehatan karyawan ditanggung perusahaan jaminan", 0.5),
        _chunk("tail-a", "catatan penunjang", 0.4),
        _chunk("tail-b", "lampiran", 0.3),
    ]
    out = rerank_candidates("biaya kesehatan", chunks)
    ids = [c.chunk_id for c in out]
    # Kepala (2 pertama) tertukar, ekor tidak berubah.
    assert ids == ["target", "distractor", "tail-a", "tail-b"]
    assert len(ids) == len(chunks)


def test_reranker_factory(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "reranker_provider", "lexical")
    assert isinstance(get_reranker(), LexicalReranker)
    monkeypatch.setattr(get_settings(), "reranker_provider", "none")
    assert isinstance(get_reranker(), NoReranker)


def test_empty_query_is_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    """Kueri tanpa istilah bermakna tidak boleh mengacaukan urutan."""
    _enable(monkeypatch)
    chunks = [
        _chunk("distractor", "biaya kantor karyawan", 0.9),
        _chunk("target", "biaya kesehatan karyawan ditanggung perusahaan jaminan", 0.5),
    ]
    out = rerank_candidates("dan yang untuk", chunks)
    assert [c.chunk_id for c in out] == ["distractor", "target"]
