"""Unit tests untuk registry job (tanpa infra)."""

from worker.jobs import JOBS, ping


def test_ping_returns_ok() -> None:
    result = ping("job-123")
    assert result == {"ok": True, "job_id": "job-123"}


def test_ping_is_idempotent_shape() -> None:
    # Bentuk output stabil — syarat job idempotent di roadmap.
    assert ping() == {"ok": True, "job_id": None}


def test_registry_contains_ping() -> None:
    assert "worker.jobs.ping" in JOBS
