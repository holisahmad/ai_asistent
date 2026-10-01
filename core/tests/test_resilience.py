"""Test unit Fase 9 — retry/backoff & circuit breaker."""

import pytest

from ai_asistent_core.resilience import (
    CircuitBreaker,
    RetryPolicy,
    call_with_retry,
    get_breaker,
    reset_breakers,
)

FAST = RetryPolicy(attempts=3, base_delay=0.0, max_delay=0.0, jitter=0.0)


def test_retry_succeeds_after_transient_failures() -> None:
    calls = {"n": 0}

    def flaky() -> str:
        calls["n"] += 1
        if calls["n"] < 3:
            raise ValueError("sementara")
        return "ok"

    assert call_with_retry(flaky, policy=FAST, retry_on=(ValueError,)) == "ok"
    assert calls["n"] == 3


def test_retry_exhausts_and_raises_last_error() -> None:
    calls = {"n": 0}

    def always_fail() -> None:
        calls["n"] += 1
        raise RuntimeError("gagal")

    with pytest.raises(RuntimeError, match="gagal"):
        call_with_retry(always_fail, policy=FAST, retry_on=(RuntimeError,))
    assert calls["n"] == 3


def test_retry_does_not_swallow_unlisted_errors() -> None:
    def boom() -> None:
        raise KeyError("bukan transient")

    with pytest.raises(KeyError):
        call_with_retry(boom, policy=FAST, retry_on=(ValueError,))


def test_breaker_opens_after_threshold_and_blocks() -> None:
    breaker = CircuitBreaker("test", failure_threshold=2, recovery_seconds=1000)
    assert breaker.allow() is True
    breaker.record_failure()
    assert breaker.allow() is True  # belum mencapai threshold
    breaker.record_failure()
    assert breaker.state == "open"
    assert breaker.allow() is False  # fail fast
    breaker.record_failure()  # tetap open
    assert breaker.allow() is False


def test_breaker_stays_open_before_recovery_window() -> None:
    breaker = CircuitBreaker("slow", failure_threshold=1, recovery_seconds=1000)
    breaker.record_failure()
    assert breaker.state == "open"
    assert breaker.allow() is False


def test_breaker_allows_probe_after_recovery_then_success_closes() -> None:
    # recovery_seconds=0 → langsung half-open: satu percobaan diizinkan
    breaker = CircuitBreaker("fast", failure_threshold=1, recovery_seconds=0.0)
    breaker.record_failure()
    assert breaker.state == "half_open"
    assert breaker.allow() is True
    breaker.record_success()
    assert breaker.state == "closed"
    assert breaker.allow() is True


def test_breaker_registry_is_stable_and_resettable(monkeypatch: pytest.MonkeyPatch) -> None:
    reset_breakers()
    a = get_breaker("llm")
    assert get_breaker("llm") is a  # instance yang sama
    a.record_failure()
    assert a.allow() is True  # threshold default > 1
    reset_breakers()
    assert get_breaker("llm").state == "closed"
