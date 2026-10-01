"""Fixtures pytest backend.

APP_DATABASE_URL diarahkan ke DB `_test` via pytest-env (pyproject.toml).
Setiap test diakhiri TRUNCATE agar isolasi antar test terjaga.
"""

from collections.abc import Iterator
from typing import Any

import pytest
from ai_asistent_core.db import get_engine, get_session_factory
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.main import create_app

_TABLES = (
    "audit_events",
    "web_search_logs",
    "idempotency_keys",
    "auth_sessions",
    "memberships",
    "workspaces",
    "users",
    "citations",
    "messages",
    "chats",
    "ingestion_jobs",
    "file_versions",
    "files",
    "document_chunks",
    "documents",
)


@pytest.fixture(autouse=True)
def clean_db() -> Iterator[None]:
    """Pastikan DB bersih sebelum & sesudah tiap test."""
    engine = get_engine()
    with engine.begin() as conn:
        for table in _TABLES:
            conn.execute(text(f"TRUNCATE TABLE {table} CASCADE"))
    yield
    with engine.begin() as conn:
        for table in _TABLES:
            conn.execute(text(f"TRUNCATE TABLE {table} CASCADE"))


@pytest.fixture(name="client")
def client_fixture() -> Iterator[TestClient]:
    with TestClient(create_app()) as c:
        yield c


@pytest.fixture(name="ingest_mode")
def ingest_mode_fixture(monkeypatch: Any) -> Any:
    """Arahkan enqueue ke eksekusi inline (fungsi ingest langsung).

    Dipakai test pipeline & test chat agar test deterministik tanpa
    menjalankan proses worker terpisah.
    """
    import app.queue as queue_mod

    calls: list[tuple[str, str]] = []

    def _inline(file_id: str, job_id: str) -> bool:
        calls.append((file_id, job_id))
        session = get_session_factory()()
        try:
            from ai_asistent_core.pipeline import ingest_file

            status = ingest_file(session, file_id, job_id)
            session.commit()
            return status == "indexed"
        finally:
            session.close()

    # Patch di titik pemakaian (files.py sudah meng-import simbol ini langsung).
    monkeypatch.setattr("app.api.routes.files.enqueue_ingest", _inline)
    monkeypatch.setattr(queue_mod, "enqueue_ingest", _inline)
    return calls


@pytest.fixture(name="user_headers")
def user_headers_fixture(client: TestClient) -> dict[str, str]:
    """User terdaftar + token siap pakai."""
    resp = client.post(
        "/api/v1/auth/register",
        json={"email": "alice@example.com", "name": "Alice", "password": "password123"},
    )
    token = resp.json()["token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(name="second_user_headers")
def second_user_headers_fixture(client: TestClient) -> dict[str, str]:
    """User kedua untuk tes isolasi antar user."""
    resp = client.post(
        "/api/v1/auth/register",
        json={"email": "bob@example.com", "name": "Bob", "password": "password123"},
    )
    token = resp.json()["token"]
    return {"Authorization": f"Bearer {token}"}
