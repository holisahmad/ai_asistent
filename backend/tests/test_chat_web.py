"""Test Fase 7 — web fallback: mode, penandaan sumber eksternal, log, ACL domain.

Provider web & LLM dipalsukan agar test deterministik tanpa network:
- `rag.web_search`/`rag.fetch_page_text` di-monkeypatch untuk jalur search,
- `websearch.get_web_search_provider` di-monkeypatch untuk menguji ACL
  domain lewat jalur asli `web_search`.
"""

import json
import uuid
from io import BytesIO
from typing import Any

import pytest
from ai_asistent_core.config import get_settings
from ai_asistent_core.db import get_session_factory
from ai_asistent_core.llm import NO_ANSWER, LLMResult
from ai_asistent_core.models import Citation, WebSearchLog
from ai_asistent_core.websearch import WebResult
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


class _FakeLLM:
    """NO_ANSWER untuk konteks internal; menjawab bila ada konteks web."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def generate(self, question: str, contexts: list[str]) -> LLMResult:
        self.calls.append(contexts)
        if any("Sumber web" in c for c in contexts):
            return LLMResult(
                text="Menurut sumber web [1], nilai tukar diperbarui harian.",
                no_answer=False,
            )
        return LLMResult(text=NO_ANSWER, no_answer=True)

    def stream_generate(self, question: str, contexts: list[str]) -> Any:
        yield self.generate(question, contexts).text


@pytest.fixture(name="web_env")
def web_env_fixture(monkeypatch: Any) -> dict[str, Any]:
    """Mode internal_plus_web + provider palsu + fetch halaman palsu."""
    s = get_settings()
    monkeypatch.setattr(s, "web_fallback_mode", "internal_plus_web")
    monkeypatch.setattr(s, "web_search_provider", "duckduckgo")
    monkeypatch.setattr(s, "web_search_domain_allowlist_csv", "")
    monkeypatch.setattr(s, "web_search_domain_denylist_csv", "")
    fake_llm = _FakeLLM()
    monkeypatch.setattr("ai_asistent_core.rag.get_llm_provider", lambda: fake_llm)
    monkeypatch.setattr(
        "ai_asistent_core.rag.fetch_page_text", lambda url: "Isi halaman web contoh."
    )
    return {"llm": fake_llm}


class _RecordingProvider:
    """Provider web palsu yang merekam jumlah panggilan."""

    def __init__(self, results: list[WebResult]) -> None:
        self.results = results
        self.calls = 0

    def search(self, query: str, max_results: int) -> list[WebResult]:
        self.calls += 1
        return self.results[:max_results]


def test_web_fallback_marks_external_sources(
    client: Any, monkeypatch: Any, web_env: dict[str, Any]
) -> None:
    """Bukti internal tak cukup + allow_web → jawaban web bertanda source_type=web."""
    headers = _mk_user(client, "web1@example.com")
    ws_id = _mk_ws(client, headers)
    _upload(client, headers, ws_id, "internal.md", b"Prosedur internal: gunakan VPN kantor.\n")

    provider = _RecordingProvider(
        [WebResult(title="Bank Indonesia", url="https://bi.go.id/kurs", snippet="Kurs harian")]
    )
    monkeypatch.setattr(
        "ai_asistent_core.websearch.get_web_search_provider", lambda: provider
    )

    r = client.post(
        f"{WS}/{ws_id}/chat/stream",
        headers=headers,
        json={"question": "berapa kurs dolar hari ini?", "allow_web": True},
    )
    assert r.status_code == 200
    events = _parse_sse(r.text)
    assert events["done"]["answer_kind"] == "grounded_web"
    cits = events["done"]["citations"]
    assert cits and cits[0]["source_type"] == "web"
    assert cits[0]["url"] == "https://bi.go.id/kurs"
    assert provider.calls == 1

    # Tersimpan dengan provenance
    chat_id = events["meta"]["chat_id"]
    detail = client.get(f"{WS}/{ws_id}/chats/{chat_id}", headers=headers).json()
    assert detail["messages"][1]["citations"][0]["source_type"] == "web"

    session = get_session_factory()()
    try:
        cites = session.execute(select(Citation)).scalars().all()
        assert len(cites) == 1 and cites[0].chunk_id is None and cites[0].url
        logs = session.execute(select(WebSearchLog)).scalars().all()
        assert len(logs) == 1
        assert logs[0].results_count == 1
        assert logs[0].provider == "duckduckgo"
    finally:
        session.close()


def test_web_not_used_when_allow_web_false(
    client: Any, monkeypatch: Any, web_env: dict[str, Any]
) -> None:
    """Kontrol pengguna: allow_web=false → tidak ada pencarian web."""
    headers = _mk_user(client, "web2@example.com")
    ws_id = _mk_ws(client, headers)
    provider = _RecordingProvider([WebResult(title="T", url="https://bi.go.id", snippet="S")])
    monkeypatch.setattr(
        "ai_asistent_core.websearch.get_web_search_provider", lambda: provider
    )

    r = client.post(
        f"{WS}/{ws_id}/chat/stream",
        headers=headers,
        json={"question": "berapa kurs dolar?", "allow_web": False},
    )
    assert _parse_sse(r.text)["done"]["answer_kind"] == "no_answer"
    assert provider.calls == 0


def test_web_not_used_in_internal_only_mode(
    client: Any, monkeypatch: Any, web_env: dict[str, Any]
) -> None:
    """Mode internal_only menang walau klien meminta web."""
    monkeypatch.setattr(get_settings(), "web_fallback_mode", "internal_only")
    headers = _mk_user(client, "web3@example.com")
    ws_id = _mk_ws(client, headers)
    provider = _RecordingProvider([WebResult(title="T", url="https://bi.go.id", snippet="S")])
    monkeypatch.setattr(
        "ai_asistent_core.websearch.get_web_search_provider", lambda: provider
    )

    r = client.post(
        f"{WS}/{ws_id}/chat/stream",
        headers=headers,
        json={"question": "berapa kurs dolar?", "allow_web": True},
    )
    assert _parse_sse(r.text)["done"]["answer_kind"] == "no_answer"
    assert provider.calls == 0


def test_web_allowlist_blocks_domain_and_logs_attempt(
    client: Any, monkeypatch: Any, web_env: dict[str, Any]
) -> None:
    """Domain di luar allowlist dibuang; percobaan tetap tercatat di log."""
    monkeypatch.setattr(get_settings(), "web_search_domain_allowlist_csv", "internal.corp")
    headers = _mk_user(client, "web4@example.com")
    ws_id = _mk_ws(client, headers)
    provider = _RecordingProvider(
        [WebResult(title="Eksternal", url="https://blocked.example.com/x", snippet="S")]
    )
    monkeypatch.setattr(
        "ai_asistent_core.websearch.get_web_search_provider", lambda: provider
    )

    r = client.post(
        f"{WS}/{ws_id}/chat/stream",
        headers=headers,
        json={"question": "berapa kurs dolar?", "allow_web": True},
    )
    assert _parse_sse(r.text)["done"]["answer_kind"] == "no_answer"
    assert provider.calls == 1  # provider dipanggil, hasil difilter ACL

    session = get_session_factory()()
    try:
        logs = session.execute(select(WebSearchLog)).scalars().all()
        assert len(logs) == 1
        assert logs[0].results_count == 0  # tersaring habis
        assert "blocked.example.com" in (logs[0].log_json or "")
    finally:
        session.close()


def test_internal_grounded_answer_untouched_by_web(
    client: Any, monkeypatch: Any, web_env: dict[str, Any], ingest_mode: list[Any]
) -> None:
    """Bila bukti internal cukup, web tidak dipakai (internal-first)."""
    import ai_asistent_core.rag as rag_mod

    class _InternalLLM:
        def generate(self, question: str, contexts: list[str]) -> LLMResult:
            return LLMResult(text="Jawaban internal [1].", no_answer=False)

        def stream_generate(self, question: str, contexts: list[str]) -> Any:
            yield self.generate(question, contexts).text

    monkeypatch.setattr(rag_mod, "get_llm_provider", lambda: _InternalLLM())
    headers = _mk_user(client, "web5@example.com")
    ws_id = _mk_ws(client, headers)
    _upload(client, headers, ws_id, "kurs.md", b"Kurs internal perusahaan: 1 USD = 16.000 IDR.\n")
    provider = _RecordingProvider([WebResult(title="T", url="https://bi.go.id", snippet="S")])
    monkeypatch.setattr(
        "ai_asistent_core.websearch.get_web_search_provider", lambda: provider
    )

    r = client.post(
        f"{WS}/{ws_id}/chat/stream",
        headers=headers,
        json={"question": "berapa kurs dolar?", "allow_web": True},
    )
    done = _parse_sse(r.text)["done"]
    assert done["answer_kind"] == "grounded"
    assert provider.calls == 0
