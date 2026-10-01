"""Test Fase 6 — chat RAG: relevansi retrieval, isolasi tenant, no-answer,
sitasi, dan penyimpanan riwayat (chats/messages/citations).

Fixture `ingest_mode` (conftest) menjalankan pipeline inline sehingga
file yang diupload langsung ter-index dan bisa di-retrieval.
"""

import json
import uuid
from io import BytesIO
from typing import Any

from ai_asistent_core.db import get_session_factory
from ai_asistent_core.models import Citation, Message
from sqlalchemy import select

WS = "/api/v1/workspaces"

Headers = dict[str, str]


def _mk_user(client: Any, email: str) -> Headers:
    r = client.post(
        "/api/v1/auth/register",
        json={"email": email, "name": email.split("@")[0], "password": "password123"},
    )
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _mk_ws(client: Any, headers: Headers) -> str:
    r = client.post(WS, headers=headers, json={"name": "WS", "slug": f"ws-{uuid.uuid4().hex[:8]}"})
    return r.json()["id"]


def _upload(client: Any, headers: Headers, ws_id: str, filename: str, content: bytes) -> str:
    r = client.post(
        f"{WS}/{ws_id}/files",
        headers=headers,
        files={"file": (filename, BytesIO(content), "text/markdown")},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _parse_sse(text: str) -> dict[str, dict[str, Any]]:
    """Ubah body SSE menjadi {event: data} (satu event per nama di test ini)."""
    events: dict[str, dict[str, Any]] = {}
    for block in text.strip().split("\n\n"):
        name: str | None = None
        data: dict[str, Any] = {}
        for line in block.split("\n"):
            if line.startswith("event: "):
                name = line.removeprefix("event: ").strip()
            elif line.startswith("data: "):
                data = json.loads(line.removeprefix("data: "))
        if name:
            events[name] = data
    return events


def test_chat_grounded_with_citations(client: Any, ingest_mode: list[Any]) -> None:
    headers = _mk_user(client, "rag@example.com")
    ws_id = _mk_ws(client, headers)
    _upload(
        client,
        headers,
        ws_id,
        "kebijakan.md",
        b"# Kebijakan Cuti\n\nJumlah hari cuti tahunan adalah 12 hari kerja.\n",
    )

    r = client.post(
        f"{WS}/{ws_id}/chat/stream",
        headers=headers,
        json={"question": "berapa hari cuti tahunan?"},
    )
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")

    events = _parse_sse(r.text)
    assert set(events) == {"meta", "delta", "done"}
    done = events["done"]
    assert done["answer_kind"] == "grounded"
    assert "cuti" in done["citations"][0]["snippet"].lower()
    assert done["citations"][0]["idx"] == 1
    assert done["citations"][0]["filename"] == "kebijakan.md"
    # Teks jawaban dari stub merujuk sitasi [1] (delta di-split per kata,
    # jadi cek lewat riwayat tersimpan, bukan event delta tunggal).

    # Riwayat tersimpan lengkap
    chats = client.get(f"{WS}/{ws_id}/chats", headers=headers)
    assert chats.status_code == 200
    assert len(chats.json()) == 1
    chat_id = chats.json()[0]["id"]
    assert chats.json()[0]["message_count"] == 2

    detail = client.get(f"{WS}/{ws_id}/chats/{chat_id}", headers=headers)
    assert detail.status_code == 200
    msgs = detail.json()["messages"]
    assert [m["role"] for m in msgs] == ["user", "assistant"]
    assert msgs[1]["answer_kind"] == "grounded"
    assert "[1]" in msgs[1]["content"]
    assert len(msgs[1]["citations"]) == 1
    cit = msgs[1]["citations"][0]
    assert cit["locator_type"] in {"char", "page", "slide", "sheet", "row"}
    assert cit["chunk_id"] and cit["file_id"]

    # Sitasi tersimpan di tabel citations
    session = get_session_factory()()
    try:
        rows = session.execute(select(Citation)).scalars().all()
        assert len(rows) == 1
        assert rows[0].message_id == msgs[1]["id"]
        assert "cuti" in rows[0].snippet.lower()
    finally:
        session.close()


def test_chat_no_answer_when_no_evidence(client: Any, ingest_mode: list[Any]) -> None:
    """Dokumen ada tapi pertanyaan tak berhubungan → jawaban no_answer."""
    headers = _mk_user(client, "noans@example.com")
    ws_id = _mk_ws(client, headers)
    _upload(client, headers, ws_id, "cuti.md", b"Kebijakan cuti tahunan 12 hari.\n")

    r = client.post(
        f"{WS}/{ws_id}/chat/stream",
        headers=headers,
        json={"question": "berapa harga tiket pesawat ke bali?"},
    )
    assert r.status_code == 200
    done = _parse_sse(r.text)["done"]
    assert done["answer_kind"] == "no_answer"
    assert done["citations"] == []

    detail = client.get(f"{WS}/{ws_id}/chats", headers=headers)
    chat_id = detail.json()[0]["id"]
    msgs = client.get(f"{WS}/{ws_id}/chats/{chat_id}", headers=headers).json()["messages"]
    assert msgs[1]["answer_kind"] == "no_answer"
    assert "belum tersedia" in msgs[1]["content"].lower()
    assert msgs[1]["citations"] == []


def test_chat_no_answer_when_workspace_empty(client: Any) -> None:
    """Tanpa dokumen sama sekali → no_answer, bukan error."""
    headers = _mk_user(client, "empty@example.com")
    ws_id = _mk_ws(client, headers)
    r = client.post(
        f"{WS}/{ws_id}/chat/stream",
        headers=headers,
        json={"question": "apa saja kebijakan?"},
    )
    assert r.status_code == 200
    done = _parse_sse(r.text)["done"]
    assert done["answer_kind"] == "no_answer"
    assert done["citations"] == []


def test_chat_tenant_isolation(client: Any, ingest_mode: list[Any]) -> None:
    """Chat+retrieval hanya melihat dokumen workspace sendiri:
    pertanyaan spesifik milik tenant lain → no_answer (bukan bocoran)."""
    owner_a = _mk_user(client, "tenanta@example.com")
    ws_a = _mk_ws(client, owner_a)
    owner_b = _mk_user(client, "tenantb@example.com")
    ws_b = _mk_ws(client, owner_b)

    _upload(
        client,
        owner_a,
        ws_a,
        "rahasia-a.md",
        b"Password server produksi workspace A adalah zmurgo-777.\n",
    )

    # Owner A bertanya di workspace-nya sendiri → grounded dari dokumennya.
    r_a = client.post(
        f"{WS}/{ws_a}/chat/stream",
        headers=owner_a,
        json={"question": "password server produksi"},
    )
    done_a = _parse_sse(r_a.text)["done"]
    assert done_a["answer_kind"] == "grounded"

    # Tenant B bertanya pertanyaan yang sama di workspace-nya (tanpa dokumen)
    # → tidak boleh terjawab dari knowledge base tenant A.
    r = client.post(
        f"{WS}/{ws_b}/chat/stream",
        headers=owner_b,
        json={"question": "password server produksi"},
    )
    done = _parse_sse(r.text)["done"]
    assert done["answer_kind"] == "no_answer"
    assert "zmurgo" not in r.text

    # Non-anggota → 404 anti enumeration
    r2 = client.post(
        f"{WS}/{ws_a}/chat/stream",
        headers=owner_b,
        json={"question": "password server produksi"},
    )
    assert r2.status_code == 404

    # Chat milik ws_a tidak terlihat via ws_b
    chat_a_id = client.get(f"{WS}/{ws_a}/chats", headers=owner_a).json()[0]["id"]
    assert (
        client.get(f"{WS}/{ws_b}/chats/{chat_a_id}", headers=owner_b).status_code == 404
    )


def test_chat_requires_membership_and_role(client: Any) -> None:
    """Unauthenticated → 401; workspace tak dikenal → 404 (bukan 403)."""
    headers = _mk_user(client, "rbac@example.com")
    r = client.post(
        f"{WS}/00000000-0000-0000-0000-000000000000/chat/stream",
        headers=headers,
        json={"question": "halo"},
    )
    assert r.status_code == 404
    r2 = client.post(
        f"{WS}/x/chat/stream",
        json={"question": "halo"},
    )
    assert r2.status_code in (401, 403)


def test_chat_persists_multi_turn_history(client: Any, ingest_mode: list[Any]) -> None:
    """chat_id lanjutan: pesan menumpuk di chat yang sama."""
    headers = _mk_user(client, "multi@example.com")
    ws_id = _mk_ws(client, headers)
    _upload(client, headers, ws_id, "sla.md", b"SLA respons insiden kritis adalah 15 menit.\n")

    r1 = client.post(
        f"{WS}/{ws_id}/chat/stream",
        headers=headers,
        json={"question": "berapa SLA insiden kritis?"},
    )
    chat_id = _parse_sse(r1.text)["meta"]["chat_id"]
    r2 = client.post(
        f"{WS}/{ws_id}/chat/stream",
        headers=headers,
        json={"question": "siapa penanggung jawabnya?", "chat_id": chat_id},
    )
    assert _parse_sse(r2.text)["meta"]["chat_id"] == chat_id

    msgs = client.get(f"{WS}/{ws_id}/chats/{chat_id}", headers=headers).json()["messages"]
    assert [m["role"] for m in msgs] == ["user", "assistant", "user", "assistant"]


def test_no_answer_message_still_saves_metadata(client: Any) -> None:
    """answer_meta_json terisi pada jawaban grounded maupun no_answer."""
    headers = _mk_user(client, "meta@example.com")
    ws_id = _mk_ws(client, headers)
    r = client.post(
        f"{WS}/{ws_id}/chat/stream", headers=headers, json={"question": "apa itu foobar?"}
    )
    chat_id = _parse_sse(r.text)["meta"]["chat_id"]
    session = get_session_factory()()
    try:
        assistant = session.execute(
            select(Message).where(Message.role == "assistant")
        ).scalar_one()
        assert assistant.answer_kind == "no_answer"
        meta = json.loads(assistant.answer_meta_json or "{}")
        assert meta["answer_kind"] == "no_answer"
        assert meta["used_chunk_ids"] == []
        assert assistant.chat_id == chat_id
    finally:
        session.close()
