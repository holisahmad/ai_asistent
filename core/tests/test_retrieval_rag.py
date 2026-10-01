"""Test unit Fase 6: fusi retrieval, LLM stub, prompt grounded.

Fusi & pipeline penuh dengan DB diuji di backend/tests/test_chat.py;
di sini fokus logika murni tanpa infrastruktur.
"""

from ai_asistent_core.embeddings import LocalHashEmbedding, _tokens
from ai_asistent_core.llm import (
    NO_ANSWER,
    LocalStubLLM,
    OpenAILLM,
    build_grounded_prompt,
)
from ai_asistent_core.retrieval import RetrievedChunk, _fuse


def _chunk(
    cid: str, *, dense: float = 0.0, kw: float = 0.0, content: str = "isi"
) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=cid,
        file_id="f1",
        filename="doc.md",
        content=content,
        locator_type="page",
        locator_start=1,
        locator_end=1,
        dense_score=dense,
        keyword_score=kw,
        score=0.0,
    )


def test_tokens_filters_short_and_non_alnum() -> None:
    assert _tokens("Kebijakan Cuti 12 hari! a b xyz") == [
        "kebijakan",
        "cuti",
        "12",
        "hari",
        "xyz",
    ]


def test_local_embedding_shared_tokens_score_high() -> None:
    p = LocalHashEmbedding(dim=384)
    q = p.embed(["berapa hari cuti tahunan"])[0]
    relevan = p.embed(["jumlah hari cuti tahunan adalah 12 hari kerja"])[0]
    tak_relevan = p.embed(["harga tiket pesawat murah ke bali"])[0]

    def cos(a: list[float], b: list[float]) -> float:
        return sum(x * y for x, y in zip(a, b, strict=True))

    # Noise dasar BoW-384 (collision bucket acak) ≈ 0.2 untuk teks disjoint;
    # yang penting sinyal shared-token jauh di atas noise itu.
    assert cos(q, relevan) > 0.4
    assert cos(q, tak_relevan) < 0.25
    # Deterministik & ternormalisasi
    assert p.embed(["sama"])[0] == p.embed(["sama"])[0]
    assert abs(sum(x * x for x in q) - 1.0) < 1e-6


def test_fuse_combines_dense_and_keyword_and_sorts() -> None:
    dense = [_chunk("a", dense=0.9), _chunk("b", dense=0.6)]
    keyword = [_chunk("b", kw=1.0), _chunk("c", kw=0.5)]
    fused = _fuse(dense, keyword, min_score=0.0)
    ids = [c.chunk_id for c in fused]
    # b ada di kedua sumber → naik; a kuat di dense; c hanya keyword lemah
    assert set(ids) == {"a", "b", "c"}
    assert fused[0].chunk_id in {"a", "b"}
    scores = {c.chunk_id: c.score for c in fused}
    assert scores["c"] < scores["a"]
    assert scores["c"] < scores["b"]


def test_fuse_threshold_drops_weak_candidates() -> None:
    dense = [_chunk("kuat", dense=0.8), _chunk("lemah", dense=0.01)]
    fused = _fuse(dense, [], min_score=0.05)
    assert [c.chunk_id for c in fused] == ["kuat"]


def test_fuse_empty_inputs() -> None:
    assert _fuse([], [], min_score=0.05) == []


def test_retrieved_chunk_snippet_truncates() -> None:
    c = _chunk("x", content="kata " * 200)
    snip = c.snippet(max_chars=50)
    assert len(snip) <= 51
    assert snip.endswith("…")


def test_llm_stub_answers_from_matching_context() -> None:
    llm = LocalStubLLM()
    result = llm.generate(
        "berapa hari cuti tahunan?",
        ["Kebijakan gaji: dibayar tiap tanggal 25.", "Jumlah hari cuti tahunan adalah 12 hari."],
    )
    assert result.no_answer is False
    assert "[2]" in result.text
    assert "12 hari" in result.text


def test_llm_stub_no_answer_when_context_irrelevant() -> None:
    llm = LocalStubLLM()
    result = llm.generate("berapa hari cuti?", ["Resep masakan rendang padang."])
    assert result.no_answer is True
    assert result.text == NO_ANSWER

    empty = llm.generate("apa itu dokumen?", [])
    assert empty.no_answer is True


def test_build_grounded_prompt_rules() -> None:
    msgs = build_grounded_prompt("q?", ["konteks satu"])
    assert msgs[0]["role"] == "system"
    assert "NO_ANSWER" in msgs[0]["content"]
    assert "[1] konteks satu" in msgs[1]["content"]
    assert "q?" in msgs[1]["content"]


def test_openai_llm_requires_dependency_guard() -> None:
    """Konstruksi OpenAILLM tanpa library openai → RuntimeError jelas.

    Kita tidak memanggil API; hanya memastikan adapter punya guard.
    (Bila openai terinstal di env, konstruksi tetap aman tanpa network.)
    """
    try:
        import openai  # noqa: F401

        provider = OpenAILLM(api_key="test-key", model="gpt-4o-mini")
        assert provider is not None
    except ImportError:
        try:
            OpenAILLM(api_key="test-key", model="gpt-4o-mini")
        except RuntimeError as exc:
            assert "openai" in str(exc).lower()
        else:  # pragma: no cover
            raise AssertionError("seharusnya raise RuntimeError tanpa library openai")
