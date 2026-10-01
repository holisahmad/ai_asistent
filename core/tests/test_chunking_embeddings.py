"""Test chunking & embeddings."""


from ai_asistent_core.chunking import chunk_sections
from ai_asistent_core.embeddings import LocalHashEmbedding
from ai_asistent_core.parsers import Section


def test_small_sections_merge_into_one_chunk() -> None:
    sections = [
        Section(text=f"bagian {i}", locator_type="page", locator_start=1, locator_end=1)
        for i in range(3)
    ]
    chunks = chunk_sections(sections)
    assert len(chunks) >= 1
    assert "bagian 0" in chunks[0].content
    assert "bagian 2" in chunks[-1].content


def test_large_section_split_with_overlap() -> None:
    big_text = "\n".join(f"paragraf {i} " + "x " * 40 for i in range(60))
    chunks = chunk_sections(
        [Section(text=big_text, locator_type="page", locator_start=1, locator_end=1)]
    )
    assert len(chunks) > 1
    # Overlap: akhir chunk sebelumnya muncul di awal chunk berikutnya
    assert chunks[1].content.startswith(("paragraf", "x"))


def test_locator_preserved() -> None:
    chunks = chunk_sections(
        [Section(text="isi penting", locator_type="slide", locator_start=3, locator_end=3)]
    )
    assert chunks[0].locator_type == "slide"
    assert chunks[0].locator_start == 3


def test_no_empty_chunks() -> None:
    sections = [
        Section(text="   ", locator_type="page", locator_start=1, locator_end=1),
        Section(text="nyata", locator_type="page", locator_start=1, locator_end=1),
    ]
    assert all(c.content.strip() for c in chunk_sections(sections))


def test_local_embedding_deterministic_and_normalized() -> None:
    provider = LocalHashEmbedding(dim=384)
    v1 = provider.embed(["teks yang sama"])[0]
    v2 = provider.embed(["teks yang sama"])[0]
    assert v1 == v2
    assert len(v1) == 384
    assert abs(sum(x * x for x in v1) - 1.0) < 1e-6
    different = provider.embed(["teks lain sama sekali"])[0]
    assert different != v1


def test_embed_batch_respects_dim() -> None:
    from ai_asistent_core.embeddings import embed_batch

    vectors = embed_batch(["a", "b", "c"] * 10)
    assert len(vectors) == 30
    assert all(len(v) == 384 for v in vectors)
