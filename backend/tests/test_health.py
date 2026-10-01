"""Contract tests for health endpoints (no infra required)."""

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture(name="client")
def client_fixture() -> TestClient:
    return TestClient(create_app())


def test_health_live_returns_alive(client: TestClient) -> None:
    resp = client.get("/health/live")
    assert resp.status_code == 200
    assert resp.json() == {"status": "alive"}


def test_health_ready_reports_check_status(client: TestClient) -> None:
    resp = client.get("/health/ready")
    assert resp.status_code in (200, 503)
    body = resp.json()
    assert set(body["checks"]) == {"database", "redis"}
