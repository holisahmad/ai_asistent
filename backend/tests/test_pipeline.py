"""Test pipeline end-to-end (Fase 4+5): upload → ingest → chunks+embedding.

Memakai queue inline (rq:inline / local fallback) agar test deterministik
tanpa menjalankan proses worker terpisah.
"""

import uuid
from io import BytesIO
from typing import Any

import pytest
from ai_asistent_core.db import get_session_factory
from ai_asistent_core.models import Document, DocumentChunk
from sqlalchemy import select

WS = "/api/v1/workspaces"

Headers = dict[str, str]
OwnedWS = tuple[Headers, str]


def _mk_user(client: Any, email: str) -> Headers:
    r = client.post(
        "/api/v1/auth/register",
        json={"email": email, "name": email.split("@")[0], "password": "password123"},
    )
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _mk_ws(client: Any, headers: Headers) -> str:
    r = client.post(WS, headers=headers, json={"name": "WS", "slug": f"ws-{uuid.uuid4().hex[:8]}"})
    return r.json()["id"]


@pytest.fixture(name="ingest_mode")
def ingest_mode_fixture(monkeypatch: Any) -> Any:
    """Arahkan enqueue ke eksekusi inline (fungsi ingest langsung)."""
    import app.queue as queue_mod

    calls: list[tuple[str, str]] = []

    def _inline(file_id: str, job_id: str) -> bool:
        calls.append((file_id, job_id))
        session = get_session_factory()()
        try:
            from worker.pipeline import ingest_file

            status = ingest_file(session, file_id, job_id)
            session.commit()
            return status == "indexed"
        finally:
            session.close()

    # Patch di titik pemakaian (files.py sudah meng-import simbol ini langsung).
    monkeypatch.setattr("app.api.routes.files.enqueue_ingest", _inline)
    monkeypatch.setattr(queue_mod, "enqueue_ingest", _inline)
    return calls


def test_upload_to_indexed_pipeline(client: Any, ingest_mode: list[Any]) -> None:
    headers = _mk_user(client, "pipe@example.com")
    ws_id = _mk_ws(client, headers)

    content = b"# Laporan QA\n\nTemuan utama: sistem sehat.\n\nRekomendasi: lanjutkan."
    r = client.post(
        f"{WS}/{ws_id}/files",
        headers=headers,
        files={"file": ("laporan.md", BytesIO(content), "text/markdown")},
    )
    assert r.status_code == 201
    fid = r.json()["id"]

    # Pipeline inline sudah jalan saat upload (fixture)
    detail = client.get(f"{WS}/{ws_id}/files/{fid}", headers=headers)
    assert detail.status_code == 200
    assert detail.json()["status"] == "indexed"

    # Document & chunk tersimpan dengan locator
    session = get_session_factory()()
    try:
        doc = session.execute(select(Document).where(Document.file_id == fid)).scalar_one()
        assert doc.source_format == "md"
        assert doc.workspace_id == ws_id
        assert doc.char_count > 0

        chunks = session.execute(
            select(DocumentChunk)
            .where(DocumentChunk.document_id == doc.id)
            .order_by(DocumentChunk.seq)
        ).scalars().all()
        assert len(chunks) >= 1
        assert all(c.embedding is not None for c in chunks)
        assert all(len(c.embedding) == 384 for c in chunks)
        assert all(c.locator_type == "char" for c in chunks)
    finally:
        session.close()


def test_failed_parser_marks_file_failed(client: Any, ingest_mode: list[Any]) -> None:
    """Ekstensi diperbolehkan upload tapi tanpa parser → job gagal, status failed."""
    headers = _mk_user(client, "fail@example.com")
    ws_id = _mk_ws(client, headers)

    # .json di-allowlist upload tapi tidak ada parser → pipeline harus menandai failed
    r = client.post(
        f"{WS}/{ws_id}/files",
        headers=headers,
        files={"file": ("data.json", BytesIO(b'{"a": 1}'), "application/json")},
    )
    assert r.status_code == 201
    fid = r.json()["id"]

    detail = client.get(f"{WS}/{ws_id}/files/{fid}", headers=headers)
    assert detail.json()["status"] == "failed"
    assert detail.json()["error"]


def test_vector_search_respects_workspace_isolation(client: Any, ingest_mode: list[Any]) -> None:
    """Embedding tersimpan & query KNN tidak bocor lintas workspace."""
    from ai_asistent_core.embeddings import embed_batch
    from ai_asistent_core.vecstore import get_vector_store

    owner_a = _mk_user(client, "a-owner@example.com")
    ws_a = _mk_ws(client, owner_a)
    content = b"rahasia workspace A unik sekali"
    client.post(
        f"{WS}/{ws_a}/files",
        headers=owner_a,
        files={"file": ("rahasia-a.md", BytesIO(content), "text/markdown")},
    )

    owner_b = _mk_user(client, "b-owner@example.com")
    ws_b = _mk_ws(client, owner_b)

    session = get_session_factory()()
    try:
        vec = embed_batch(["rahasia workspace A unik sekali"])[0]
        matches_b = get_vector_store().search(session, ws_b, vec, top_k=5)
        matches_a = get_vector_store().search(session, ws_a, vec, top_k=5)
        assert matches_b == []          # tidak bocor ke workspace lain
        assert len(matches_a) >= 1      # dan ditemukan di workspace asal
        assert matches_a[0].locator_type == "char"
    finally:
        session.close()
