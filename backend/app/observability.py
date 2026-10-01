"""Observability & perlindungan API (Fase 9).

- Correlation ID: header `X-Request-ID` diterima/dibuat, ditempel ke log &
  respons, sehingga satu request dapat dilacak lintas service.
- Metrik: counter + histogram sederhana dengan eksposisi Prometheus text
  di `GET /metrics` (tanpa dependensi tambahan).
- Rate limit: sliding window per identitas (token/IP) untuk endpoint API.
"""

import hashlib
import logging
import threading
import time
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse, PlainTextResponse

from app.context import request_id_ctx

logger = logging.getLogger("app.observability")

_HISTOGRAM_BUCKETS = (0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)
_MAX_SAMPLES = 2000


class Metrics:
    """Registry metrik in-process (counter + histogram)."""

    def __init__(self) -> None:
        self._counters: dict[tuple[str, tuple[tuple[str, str], ...]], float] = defaultdict(float)
        self._hist: dict[tuple[str, tuple[tuple[str, str], ...]], list[float]] = defaultdict(list)
        self._lock = threading.Lock()

    @staticmethod
    def _label_key(labels: dict[str, str] | None) -> tuple[tuple[str, str], ...]:
        return tuple(sorted((labels or {}).items()))

    def inc(self, name: str, labels: dict[str, str] | None = None, value: float = 1.0) -> None:
        with self._lock:
            self._counters[(name, self._label_key(labels))] += value

    def observe(self, name: str, value: float, labels: dict[str, str] | None = None) -> None:
        with self._lock:
            samples = self._hist[(name, self._label_key(labels))]
            samples.append(value)
            if len(samples) > _MAX_SAMPLES:
                del samples[: len(samples) - _MAX_SAMPLES]

    @staticmethod
    def _fmt_labels(labels: tuple[tuple[str, str], ...], extra: str = "") -> str:
        if not labels and not extra:
            return ""
        parts = [f'{k}="{v}"' for k, v in labels]
        if extra:
            parts.append(extra)
        return "{" + ",".join(parts) + "}"

    def render(self) -> str:
        """Eksposisi format teks Prometheus."""
        lines: list[str] = []
        with self._lock:
            for (name, labels), value in sorted(self._counters.items()):
                lines.append(f"# TYPE {name} counter")
                lines.append(f"{name}{self._fmt_labels(labels)} {value:g}")
            for (name, labels), samples in sorted(self._hist.items()):
                base_labels = labels
                lines.append(f"# TYPE {name} histogram")
                lines.append(
                    f"{name}_count{self._fmt_labels(base_labels)} {len(samples)}"
                )
                total = sum(samples)
                lines.append(f"{name}_sum{self._fmt_labels(base_labels)} {total:.6f}")
                for bucket in _HISTOGRAM_BUCKETS:
                    count = sum(1 for s in samples if s <= bucket)
                    lines.append(
                        f"{name}_bucket"
                        f"{self._fmt_labels(base_labels, f'le=\"{bucket}\"')} {count}"
                    )
                lines.append(
                    f"{name}_bucket{self._fmt_labels(base_labels, 'le=\"+Inf\"')} {len(samples)}"
                )
        lines.append("# TYPE app_info gauge")
        lines.append("app_info 1")
        return "\n".join(lines) + "\n"

    def reset(self) -> None:
        with self._lock:
            self._counters.clear()
            self._hist.clear()


metrics = Metrics()

# --- Rate limit (sliding window per identitas) ---

_rate_hits: dict[str, deque[float]] = defaultdict(deque)
_rate_lock = threading.Lock()


def _identity(request: Request) -> str:
    """Identitas rate limit: hash token bearer, else IP klien."""
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return "token:" + hashlib.sha256(auth[7:].strip().encode()).hexdigest()[:16]
    client = request.client.host if request.client else "unknown"
    return f"ip:{client}"


def rate_limit_allow(identity: str, limit: int, burst: int = 0) -> bool:
    """True bila permintaan masih dalam kuota per menit."""
    if limit <= 0:
        return True
    now = time.monotonic()
    with _rate_lock:
        window = _rate_hits[identity]
        while window and now - window[0] > 60.0:
            window.popleft()
        if len(window) >= limit + max(0, burst):
            return False
        window.append(now)
        return True


def reset_rate_limits() -> None:
    """Bersihkan window rate limit (test/operasi)."""
    with _rate_lock:
        _rate_hits.clear()


def _route_label(request: Request) -> str:
    """Label route bertemplat (hindari kardinalitas UUID di path)."""
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    return str(path or request.url.path)


def install_middlewares(app: FastAPI) -> None:
    """Pasang middleware correlation ID, metrik, dan rate limit."""

    @app.middleware("http")
    async def observability_middleware(
        request: Request, call_next: Callable[[Request], Awaitable[Any]]
    ) -> Any:
        from ai_asistent_core.config import get_settings

        s = get_settings()
        rid = request.headers.get(s.request_id_header) or uuid4().hex
        token = request_id_ctx.set(rid)
        start = time.perf_counter()
        try:
            # Rate limit hanya untuk API (health & metrics tetap bebas).
            if request.url.path.startswith("/api/"):
                identity = _identity(request)
                if not rate_limit_allow(
                    identity, s.api_rate_limit_per_min, s.api_rate_limit_burst
                ):
                    metrics.inc(
                        "http_rate_limited_total", {"route": _route_label(request)}
                    )
                    logger.warning(
                        "rate limit terlampaui identity=%s path=%s",
                        identity,
                        request.url.path,
                    )
                    response = JSONResponse(
                        {"detail": "Rate limit terlampaui"},
                        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    )
                    response.headers["Retry-After"] = "60"
                else:
                    response = await call_next(request)
            else:
                response = await call_next(request)
        except Exception:
            elapsed = time.perf_counter() - start
            metrics.observe(
                "http_request_duration_seconds",
                elapsed,
                {"method": request.method, "route": _route_label(request), "status": "500"},
            )
            metrics.inc(
                "http_requests_total",
                {"method": request.method, "route": _route_label(request), "status": "500"},
            )
            request_id_ctx.reset(token)
            raise

        elapsed = time.perf_counter() - start
        labels = {
            "method": request.method,
            "route": _route_label(request),
            "status": str(response.status_code),
        }
        metrics.observe("http_request_duration_seconds", elapsed, labels)
        metrics.inc("http_requests_total", labels)
        response.headers[s.request_id_header] = rid
        request_id_ctx.reset(token)
        return response


def metrics_response() -> PlainTextResponse:
    """Respons `GET /metrics` (teks Prometheus)."""
    return PlainTextResponse(metrics.render(), media_type="text/plain; version=0.0.4")
