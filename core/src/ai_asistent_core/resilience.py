"""Ketahanan panggilan eksternal (Fase 9): retry/backoff + circuit breaker.

Dipakai untuk panggilan LLM dan web search agar gangguan sementara
(timeout, 5xx, 429) ditangani otomatis, sementara gangguan berkepanjangan
gagal cepat (fail fast) alih-alih menumpuk latensi.
"""

import logging
import random
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

logger = logging.getLogger("ai_asistent_core.resilience")


@dataclass(frozen=True)
class RetryPolicy:
    """Kebijakan retry: backoff eksponensial + jitter ±20%."""

    attempts: int = 3
    base_delay: float = 0.5
    max_delay: float = 8.0
    jitter: float = 0.2


def _delay_for(attempt: int, policy: RetryPolicy) -> float:
    """Delay eksponensial dengan jitter; attempt mulai dari 1."""
    raw = min(policy.base_delay * (2 ** (attempt - 1)), policy.max_delay)
    spread = raw * policy.jitter
    return float(max(0.0, raw + random.uniform(-spread, spread)))


def call_with_retry[T](
    fn: Callable[[], T],
    *,
    policy: RetryPolicy | None = None,
    retry_on: tuple[type[BaseException], ...] = (Exception,),
    on_retry: Callable[[int, BaseException], None] | None = None,
) -> T:
    """Panggil `fn` dengan retry; lempar error terakhir bila semua gagal."""
    p = policy or RetryPolicy()
    last: BaseException | None = None
    for attempt in range(1, max(1, p.attempts) + 1):
        try:
            return fn()
        except retry_on as exc:
            last = exc
            if attempt >= p.attempts:
                break
            if on_retry is not None:
                on_retry(attempt, exc)
            time.sleep(_delay_for(attempt, p))
    assert last is not None  # pragma: no cover - hanya bila attempts >= 1
    raise last


class CircuitBreaker:
    """Circuit breaker sederhana: closed → open → half-open.

    - `closed`: normal.
    - `open`: semua panggilan ditolak sampai `recovery_seconds` lewat.
    - `half_open`: satu percobaan diizinkan untuk menguji pemulihan.
    """

    def __init__(
        self, name: str, *, failure_threshold: int = 5, recovery_seconds: float = 60.0
    ) -> None:
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_seconds = recovery_seconds
        self._failures = 0
        self._opened_at: float | None = None
        self._lock = threading.Lock()

    @property
    def state(self) -> str:
        with self._lock:
            if self._opened_at is None:
                return "closed"
            if time.monotonic() - self._opened_at >= self.recovery_seconds:
                return "half_open"
            return "open"

    def allow(self) -> bool:
        """True bila panggilan boleh dilakukan sekarang."""
        with self._lock:
            if self._opened_at is None:
                return True
            if time.monotonic() - self._opened_at >= self.recovery_seconds:
                self._opened_at = None  # half-open: izinkan satu percobaan
                self._failures = self.failure_threshold - 1
                return True
            return False

    def record_success(self) -> None:
        with self._lock:
            self._failures = 0
            self._opened_at = None

    def record_failure(self) -> None:
        with self._lock:
            self._failures += 1
            if self._failures >= self.failure_threshold and self._opened_at is None:
                self._opened_at = time.monotonic()
                logger.warning(
                    "circuit breaker '%s' OPEN setelah %d kegagalan", self.name, self._failures
                )

    def reset(self) -> None:
        """Kembalikan ke kondisi normal (dipakai test & operasi manual)."""
        with self._lock:
            self._failures = 0
            self._opened_at = None


_breakers: dict[str, CircuitBreaker] = {}
_breakers_lock = threading.Lock()


def get_breaker(name: str) -> CircuitBreaker:
    """Registry breaker per nama komponen (llm, web_search, ...)."""
    from ai_asistent_core.config import get_settings

    with _breakers_lock:
        if name not in _breakers:
            s = get_settings()
            _breakers[name] = CircuitBreaker(
                name,
                failure_threshold=s.breaker_failure_threshold,
                recovery_seconds=s.breaker_recovery_seconds,
            )
        return _breakers[name]


def reset_breakers() -> None:
    """Reset semua breaker (test/operasi)."""
    with _breakers_lock:
        for b in _breakers.values():
            b.reset()
