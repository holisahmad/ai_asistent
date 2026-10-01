"""Fixtures pytest backend.

APP_DATABASE_URL diarahkan ke DB `_test` via pytest-env (pyproject.toml).
Setiap test diakhiri TRUNCATE agar isolasi antar test terjaga.
"""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.db import get_engine
from app.main import create_app

_TABLES = (
    "audit_events",
    "auth_sessions",
    "memberships",
    "workspaces",
    "users",
    "ingestion_jobs",
    "file_versions",
    "files",
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
