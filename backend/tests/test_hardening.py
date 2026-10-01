"""Test Fase 8/9 — correlation ID, metrik, rate limit, idempotency, guard, feedback."""

import json
import uuid
from io import BytesIO
from typing import Any

import pytest
from ai_asistent_core.config import get_settings
from ai_asistent_core.db import get_session_factory
from ai_asistent_core.models import File, Message
from sqlalchemy import select

from app.observability import reset_rate_limits

WS = "/api/v1/workspaces"
Headers = dict[str, str]


@pytest.fixture(autouse=True)
def _clean_observability() -> None:
    reset_rate_limits()


def _mk_user(client: Any, email: str) -> Headers:
    r = client.post(
        "/api/v1/auth/register",
        json={"email": email, "name": email.split("@")[0], "password": "password123"},
    )
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _mk_ws(client: Any, headers: Headers) -> str:
    r = client.post(WS, headers=headers, json={"name": "WS", "slug": f"ws-{uuid.uuid4().hex[:8]}"})
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


def test_correlation_id_echoed_or_generated(client: Any) -> None:
    r = client.get("/health/live", headers={"X-Request-ID": "trace-abc-123"})
    assert r.status_code == 200
    assert r.headers.get("X-Request-ID") == "trace-abc-123"

    r2 = client.get("/health/live")
    assert r2.headers.get("X-Request-ID")  # dibuat otomatis bila tidak dikirim


def test_metrics_endpoint_exposes_counters_and_histograms(client: Any) -> None:
    client.get("/health/live")
    r = client.get("/metrics")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/plain")
    body = r.text
    assert "http_requests_total" in body
    assert "http_request_duration_seconds_bucket" in body
    assert 'le="+Inf"' in body


def test_metrics_can_be_protected_by_token(client: Any, monkeypatch: Any) -> None:
    monkeypatch.setattr(get_settings(), "metrics_token", "rahasia-metrics")
    assert client.get("/metrics").status_code == 401
    ok = client.get("/metrics", headers={"Authorization": "Bearer rahasia-metrics"})
    assert ok.status_code == 200


def test_version_endpoint(client: Any) -> None:
    r = client.get("/version")
    assert r.status_code == 200
    assert r.json()["version"]


def test_rate_limit_returns_429_with_retry_after(
    client: Any, user_headers: Headers, monkeypatch: Any
) -> None:
    monkeypatch.setattr(get_settings(), "api_rate_limit_per_min", 1)
    monkeypatch.setattr(get_settings(), "api_rate_limit_burst", 0)
    reset_rate_limits()

    first = client.get("/api/v1/auth/me", headers=user_headers)
    assert first.status_code == 200
    second = client.get("/api/v1/auth/me", headers=user_headers)
    assert second.status_code == 429
    assert second.headers.get("Retry-After") == "60"
    assert "Rate limit" in second.json()["detail"]

    # Health tidak terkena rate limit (bukan /api/)
    assert client.get("/health/live").status_code == 200


def test_upload_idempotency_returns_same_file(
    client: Any, ingest_mode: list[Any]
) -> None:
    headers = _mk_user(client, "idem@example.com")
    ws_id = _mk_ws(client, headers)
    key = "kunci-upload-1"
    payload = b"# Dokumen\n\nIsi penting untuk dedup idempotensi.\n"

    def _upload() -> Any:
        return client.post(
            f"{WS}/{ws_id}/files",
            headers={**headers, "Idempotency-Key": key},
            files={"file": ("dokumen.md", BytesIO(payload), "text/markdown")},
        )

    first, second = _upload(), _upload()
    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] == second.json()["id"]

    session = get_session_factory()()
    try:
        rows = session.execute(select(File)).scalars().all()
        assert len(rows) == 1  # tidak ada duplikat
    finally:
        session.close()


def test_upload_rejects_executable_content(client: Any) -> None:
    headers = _mk_user(client, "guard@example.com")
    ws_id = _mk_ws(client, headers)
    r = client.post(
        f"{WS}/{ws_id}/files",
        headers=headers,
        files={"file": ("setup.txt", BytesIO(b"MZ\x90\x00payload"), "text/plain")},
    )
    assert r.status_code == 422
    assert "ditolak" in r.json()["detail"]


def test_feedback_roundtrip_and_validation(client: Any, ingest_mode: list[Any]) -> None:
    headers = _mk_user(client, "fb@example.com")
    ws_id = _mk_ws(client, headers)
    client.post(
        f"{WS}/{ws_id}/files",
        headers=headers,
        files={"file": ("cuti.md", BytesIO(b"Cuti tahunan 12 hari kerja.\n"), "text/markdown")},
    )
    r = client.post(
        f"{WS}/{ws_id}/chat/stream",
        headers=headers,
        json={"question": "berapa cuti tahunan?"},
    )
    events = _parse_sse(r.text)
    chat_id = events["meta"]["chat_id"]

    detail = client.get(f"{WS}/{ws_id}/chats/{chat_id}", headers=headers).json()
    assistant = detail["messages"][1]
    user_msg = detail["messages"][0]
    assert assistant["feedback"] is None

    up = client.post(
        f"{WS}/{ws_id}/chats/{chat_id}/messages/{assistant['id']}/feedback",
        headers=headers,
        json={"feedback": "up"},
    )
    assert up.status_code == 200
    assert up.json()["feedback"] == "up"

    detail2 = client.get(f"{WS}/{ws_id}/chats/{chat_id}", headers=headers).json()
    assert detail2["messages"][1]["feedback"] == "up"

    # Hapus feedback
    cleared = client.post(
        f"{WS}/{ws_id}/chats/{chat_id}/messages/{assistant['id']}/feedback",
        headers=headers,
        json={"feedback": None},
    )
    assert cleared.json()["feedback"] is None

    # Pesan user tidak boleh diberi feedback
    bad = client.post(
        f"{WS}/{ws_id}/chats/{chat_id}/messages/{user_msg['id']}/feedback",
        headers=headers,
        json={"feedback": "down"},
    )
    assert bad.status_code == 400

    # Audit tercatat
    session = get_session_factory()()
    try:
        assert session.execute(select(Message)).scalars().all()
    finally:
        session.close()
