"""Test Fase 2 upgrade — mode jawaban: extractive, generative, auto.

Strategi:
- Semua test berjalan tanpa DB / jaringan / LLM nyata.
- Chunk dibuat manual, settings dimonkeypatch per test.
- LexicalConfidence dan _extractive_answer diuji langsung di sini.
- answer_question diuji via stub LLM + monkeypatch retrieve agar deterministik.
"""

from __future__ import annotations

import pytest

from ai_asistent_core.config import get_settings
from ai_asistent_core.rerank import LexicalConfidence, lexical_confidence
from ai_asistent_core.retrieval import RetrievedChunk

# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _chunk(
    cid: str,
    content: str,
    score: float = 0.5,
    filename: str = "dokumen.md",
) -> RetrievedChunk:
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


def _settings(
    monkeypatch: pytest.MonkeyPatch,
    *,
    mode: str = "generative",
    threshold: float = 0.55,
    margin: float = 0.10,
    max_chars: int = 600,
) -> None:
    s = get_settings()
    monkeypatch.setattr(s, "answer_mode", mode)
    monkeypatch.setattr(s, "answer_extractive_threshold", threshold)
    monkeypatch.setattr(s, "answer_min_margin", margin)
    monkeypatch.setattr(s, "answer_max_chars", max_chars)


# ---------------------------------------------------------------------------
# Test LexicalConfidence
# ---------------------------------------------------------------------------


class TestLexicalConfidence:
    def test_empty_candidates_returns_zero(self) -> None:
        lc = lexical_confidence("biaya kesehatan", [])
        assert lc.score == 0.0
        assert lc.total_terms == 0
        assert lc.matched_terms == []

    def test_empty_query_returns_zero(self) -> None:
        chunks = [_chunk("a", "biaya kesehatan karyawan")]
        lc = lexical_confidence("dan yang untuk", chunks, target_idx=0)
        assert lc.score == 0.0

    def test_perfect_match_score_close_to_one(self) -> None:
        """Semua istilah kueri ada di konten → skor mendekati 1."""
        chunks = [_chunk("a", "biaya kesehatan karyawan ditanggung perusahaan")]
        lc = lexical_confidence("biaya kesehatan karyawan", chunks, target_idx=0)
        assert lc.score > 0.90
        assert set(lc.matched_terms) >= {"biaya", "kesehatan", "karyawan"}

    def test_no_match_returns_zero(self) -> None:
        """Tidak ada tumpang tindih token → skor 0."""
        chunks = [_chunk("a", "kebijakan perjalanan dinas luar negeri")]
        lc = lexical_confidence("biaya kesehatan karyawan", chunks, target_idx=0)
        assert lc.score == 0.0
        assert lc.matched_terms == []

    def test_rare_term_weighted_higher(self) -> None:
        """Istilah unik (df=1) memberi kontribusi IDF lebih besar dari kata umum.

        Tiga chunk: dua memuat 'biaya' (df=2), satu memuat 'premi' (df=1).
        Kueri mengandung keduanya.  Chunk dengan 'premi' saja (idx=2) harus
        mendapat skor lebih tinggi dari chunk dengan 'biaya' saja (idx=0/1),
        karena IDF('premi') > IDF('biaya').
        """
        chunks = [
            _chunk("common1", "biaya gaji karyawan"),
            _chunk("common2", "biaya kantor operasional"),
            _chunk("rare", "premi asuransi jiwa"),
        ]
        # idx=0: hanya 'biaya' cocok (df=2, idf kecil)
        # idx=2: hanya 'premi' cocok (df=1, idf besar)
        lc_common = lexical_confidence("biaya premi", chunks, target_idx=0)
        lc_rare = lexical_confidence("biaya premi", chunks, target_idx=2)
        assert lc_rare.score > lc_common.score

    def test_idf_sum_equals_matched_plus_unmatched(self) -> None:
        """idf_sum harus ≥ idf_matched (penjumlahan semua istilah kueri)."""
        chunks = [_chunk("a", "biaya kesehatan")]
        lc = lexical_confidence("biaya kesehatan pensiun", chunks, target_idx=0)
        assert lc.idf_sum >= lc.idf_matched
        assert lc.total_terms == 3  # biaya, kesehatan, pensiun

    def test_score_is_normalized_between_zero_and_one(self) -> None:
        chunks = [
            _chunk("a", "kebijakan cuti tahunan karyawan perusahaan"),
            _chunk("b", "biaya kesehatan"),
            _chunk("c", "tunjangan hari raya"),
        ]
        for i in range(len(chunks)):
            lc = lexical_confidence("cuti kesehatan karyawan", chunks, target_idx=i)
            assert 0.0 <= lc.score <= 1.0

    def test_target_idx_selects_correct_chunk(self) -> None:
        chunks = [
            _chunk("a", "premi asuransi jiwa"),
            _chunk("b", "biaya gaji kantor"),
        ]
        lca = lexical_confidence("asuransi jiwa", chunks, target_idx=0)
        lcb = lexical_confidence("asuransi jiwa", chunks, target_idx=1)
        assert lca.score > lcb.score

    def test_dataclass_is_frozen(self) -> None:
        lc = LexicalConfidence(
            score=0.5,
            matched_terms=["a"],
            total_terms=2,
            idf_sum=1.0,
            idf_matched=0.5,
        )
        with pytest.raises(AttributeError):
            lc.score = 0.9  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Test _extractive_answer (via rag internals)
# ---------------------------------------------------------------------------


class TestExtractiveAnswer:
    """Test langsung fungsi _extractive_answer."""

    def _get_fn(self):  # type: ignore[return]
        from ai_asistent_core.rag import _extractive_answer
        return _extractive_answer

    def test_returns_none_when_no_chunks(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _settings(monkeypatch, mode="extractive", threshold=0.3)
        fn = self._get_fn()
        assert fn("biaya kesehatan", []) is None

    def test_returns_extractive_answer_when_score_high(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _settings(monkeypatch, mode="extractive", threshold=0.3, margin=0.05)
        fn = self._get_fn()
        chunks = [
            _chunk("target", "biaya kesehatan karyawan ditanggung perusahaan asuransi", 0.8),
            _chunk("other", "kebijakan gaji bonus akhir tahun kantor", 0.4),
        ]
        result = fn("biaya kesehatan karyawan", chunks)
        assert result is not None
        assert result.answer_kind == "extractive"
        assert result.used_chunk_ids == ["target"]
        assert len(result.citations) == 1
        assert result.citations[0].chunk_id == "target"

    def test_returns_none_when_score_below_threshold(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Gunakan threshold default 0.55 tapi query dengan banyak term yang
        # tidak ada di chunk → skor rendah → None.
        _settings(monkeypatch, mode="extractive", threshold=0.55, margin=0.0)
        fn = self._get_fn()
        chunks = [
            # Hanya "biaya" yang cocok dari query; "kesehatan pensiun tunjangan"
            # tidak ada → skor IDF-weighted jauh di bawah 0.55
            _chunk("a", "biaya gaji administrasi pegawai", 0.8),
            _chunk("b", "kebijakan kantor umum", 0.4),
        ]
        result = fn("biaya kesehatan pensiun tunjangan asuransi jiwa", chunks)
        assert result is None

    def test_returns_none_when_margin_too_small(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Dua chunk sama-sama relevan → margin kecil → None."""
        _settings(monkeypatch, mode="auto", threshold=0.3, margin=0.50)
        fn = self._get_fn()
        # Dua chunk nyaris identik → skor confidence sangat dekat
        text = "biaya kesehatan karyawan ditanggung perusahaan asuransi"
        chunks = [
            _chunk("a", text + " jiwa", 0.8),
            _chunk("b", text + " gigi", 0.7),
        ]
        result = fn("biaya kesehatan karyawan", chunks)
        assert result is None

    def test_truncates_text_when_max_chars_set(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _settings(monkeypatch, mode="extractive", threshold=0.1, margin=0.0, max_chars=50)
        fn = self._get_fn()
        long_content = "biaya kesehatan karyawan " * 30  # > 50 chars
        chunks = [_chunk("a", long_content, 0.9)]
        result = fn("biaya kesehatan", chunks)
        assert result is not None
        assert len(result.text) <= 51  # 50 + "…"
        assert result.text.endswith("…")

    def test_no_truncation_when_max_chars_zero(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _settings(monkeypatch, mode="extractive", threshold=0.1, margin=0.0, max_chars=0)
        fn = self._get_fn()
        content = "biaya kesehatan karyawan " * 5
        chunks = [_chunk("a", content.strip(), 0.9)]
        result = fn("biaya kesehatan", chunks)
        assert result is not None
        assert not result.text.endswith("…")


# ---------------------------------------------------------------------------
# Test answer_question — mode routing (stub DB + LLM)
# ---------------------------------------------------------------------------


class TestAnswerQuestionModes:
    """answer_question diuji dengan retrieve di-mock dan LLM stub."""

    def _make_chunks(self) -> list[RetrievedChunk]:
        return [
            _chunk("target", "biaya kesehatan karyawan ditanggung perusahaan asuransi jiwa", 0.8),
            _chunk("other", "kebijakan kantor gaji bonus akhir tahun", 0.4),
        ]

    def _answer(
        self,
        monkeypatch: pytest.MonkeyPatch,
        question: str = "biaya kesehatan karyawan",
        *,
        mode: str,
        threshold: float = 0.3,
        margin: float = 0.05,
    ):
        from unittest.mock import MagicMock

        import ai_asistent_core.rag as rag_mod
        from ai_asistent_core.llm import LocalStubLLM
        from ai_asistent_core.rag import answer_question

        _settings(monkeypatch, mode=mode, threshold=threshold, margin=margin)
        monkeypatch.setattr(rag_mod, "retrieve", lambda *a, **kw: self._make_chunks())

        db = MagicMock()
        return answer_question(db, "ws-1", question, provider=LocalStubLLM())

    def test_generative_mode_returns_grounded(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ans = self._answer(monkeypatch, mode="generative")
        assert ans.answer_kind == "grounded"

    def test_extractive_mode_returns_extractive(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ans = self._answer(monkeypatch, mode="extractive", threshold=0.3, margin=0.05)
        assert ans.answer_kind == "extractive"

    def test_auto_mode_extractive_when_score_sufficient(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ans = self._answer(monkeypatch, mode="auto", threshold=0.3, margin=0.05)
        assert ans.answer_kind == "extractive"

    def test_auto_mode_falls_back_to_generative_when_low_score(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Threshold 0.55, query punya banyak term yang tidak ada di chunk → skor rendah → generatif."""
        from unittest.mock import MagicMock

        import ai_asistent_core.rag as rag_mod
        from ai_asistent_core.llm import LocalStubLLM
        from ai_asistent_core.rag import answer_question

        _settings(monkeypatch, mode="auto", threshold=0.55, margin=0.0)

        # Chunk hanya cocok sebagian kecil term query → skor < 0.55
        def low_score_chunks(*a, **kw):
            return [
                _chunk("a", "biaya gaji administrasi kantor", 0.6),
                _chunk("b", "kebijakan perjalanan dinas luar negeri", 0.4),
            ]

        monkeypatch.setattr(rag_mod, "retrieve", low_score_chunks)
        db = MagicMock()
        ans = answer_question(
            db, "ws-1",
            "biaya kesehatan pensiun tunjangan asuransi jiwa karyawan",
            provider=LocalStubLLM(),
        )
        assert ans.answer_kind == "grounded"

    def test_extractive_mode_no_answer_when_low_score(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """mode=extractive keras: skor leksikal rendah → no_answer, tanpa LLM."""
        from unittest.mock import MagicMock

        import ai_asistent_core.rag as rag_mod
        from ai_asistent_core.rag import answer_question

        _settings(monkeypatch, mode="extractive", threshold=0.55, margin=0.0)

        # Chunk tidak cocok dengan banyak term query → skor jauh < 0.55
        def low_score_chunks(*a, **kw):
            return [
                _chunk("a", "biaya gaji administrasi kantor", 0.6),
                _chunk("b", "kebijakan perjalanan dinas", 0.4),
            ]

        monkeypatch.setattr(rag_mod, "retrieve", low_score_chunks)

        # LLM TIDAK boleh dipanggil dalam mode extractive keras
        called = []

        class TrackingLLM:
            def generate(self, q, ctxs):
                called.append(True)
                from ai_asistent_core.llm import LLMResult
                return LLMResult(text="seharusnya tidak dipanggil", no_answer=False)

            def stream_generate(self, q, ctxs):
                called.append(True)
                yield ""

        db = MagicMock()
        ans = answer_question(
            db, "ws-1",
            "biaya kesehatan pensiun tunjangan asuransi jiwa karyawan",
            provider=TrackingLLM(),  # type: ignore[arg-type]
        )
        assert ans.answer_kind == "no_answer"
        assert called == [], "LLM tidak boleh dipanggil dalam mode extractive keras"

    def test_no_chunks_returns_no_answer(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from unittest.mock import MagicMock

        import ai_asistent_core.rag as rag_mod
        from ai_asistent_core.llm import LocalStubLLM
        from ai_asistent_core.rag import answer_question

        _settings(monkeypatch, mode="extractive")
        monkeypatch.setattr(rag_mod, "retrieve", lambda *a, **kw: [])
        db = MagicMock()
        ans = answer_question(db, "ws-1", "apa itu?", provider=LocalStubLLM())
        assert ans.answer_kind == "no_answer"


# ---------------------------------------------------------------------------
# Test answer_stream — mode routing
# ---------------------------------------------------------------------------


class TestAnswerStreamModes:
    def _make_chunks(self) -> list[RetrievedChunk]:
        return [
            _chunk("target", "biaya kesehatan karyawan ditanggung perusahaan asuransi jiwa", 0.8),
            _chunk("other", "kebijakan kantor gaji bonus akhir tahun", 0.4),
        ]

    def test_extractive_mode_yields_snippet_without_llm(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from unittest.mock import MagicMock

        import ai_asistent_core.rag as rag_mod
        from ai_asistent_core.rag import answer_stream

        _settings(monkeypatch, mode="extractive", threshold=0.3, margin=0.05)
        monkeypatch.setattr(rag_mod, "retrieve", lambda *a, **kw: self._make_chunks())

        called = []

        class TrackingLLM:
            def generate(self, q, ctxs):
                called.append(True)
                from ai_asistent_core.llm import LLMResult
                return LLMResult(text="", no_answer=True)

            def stream_generate(self, q, ctxs):
                called.append(True)
                yield ""

        db = MagicMock()
        stream = answer_stream(db, "ws-1", "biaya kesehatan karyawan", provider=TrackingLLM())  # type: ignore[arg-type]
        deltas = list(stream)
        final = stream.final()

        assert final.answer_kind == "extractive"
        assert called == [], "LLM tidak boleh dipanggil dalam mode extractive"
        assert "".join(deltas).strip() != ""

    def test_generative_mode_calls_llm_stream(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from unittest.mock import MagicMock

        import ai_asistent_core.rag as rag_mod
        from ai_asistent_core.llm import LocalStubLLM
        from ai_asistent_core.rag import answer_stream

        _settings(monkeypatch, mode="generative")
        monkeypatch.setattr(rag_mod, "retrieve", lambda *a, **kw: self._make_chunks())

        db = MagicMock()
        stream = answer_stream(db, "ws-1", "biaya kesehatan karyawan", provider=LocalStubLLM())
        deltas = list(stream)
        final = stream.final()

        assert final.answer_kind == "grounded"
        assert "".join(deltas).strip() != ""
