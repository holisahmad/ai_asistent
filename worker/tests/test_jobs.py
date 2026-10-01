"""Test worker: registry job & util pipeline (tanpa infra eksternal)."""

import pytest

from worker.jobs import get_callable


def test_registry_contains_ingest() -> None:
    fn = get_callable("worker.jobs.ingest")
    assert callable(fn)


def test_registry_rejects_unknown() -> None:
    with pytest.raises(KeyError):
        get_callable("os.system")


def test_chunk_to_embed_shapes() -> None:
    """Sanity: chunk dari section kecil → minimal 1 chunk."""
    from ai_asistent_core.chunking import chunk_sections
    from ai_asistent_core.parsers import Section

    chunks = chunk_sections(
        [Section(text="halo", locator_type="page", locator_start=1, locator_end=1)]
    )
    assert len(chunks) == 1
    assert chunks[0].content == "halo"
