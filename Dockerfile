# Dockerfile utama untuk Railway deployment — AI Knowledge Assistant Backend
# Multi-stage: builder (uv install) → runtime (slim)

# ---- Builder ----
FROM python:3.12-slim AS builder

WORKDIR /app

# Install uv
RUN pip install --no-cache-dir uv==0.4.29

# Copy dependency files (cache layer)
COPY pyproject.toml uv.lock ./
COPY core/ ./core/
COPY backend/ ./backend/
COPY worker/ ./worker/

# Install semua dependencies ke /app/.venv (eksplisit via UV_PROJECT_ENVIRONMENT)
ENV UV_PROJECT_ENVIRONMENT=/app/.venv
RUN uv sync --locked --no-dev

# Verifikasi uvicorn ada (gagal build bila tidak ada)
RUN /app/.venv/bin/uvicorn --version

# ---- Runtime ----
FROM python:3.12-slim AS runtime

# Keamanan: jalankan sebagai user non-root
RUN groupadd -r appuser && useradd -r -g appuser appuser

WORKDIR /app

# Salin venv, source, dan entrypoint dari builder
COPY --from=builder /app/.venv    /app/.venv
COPY --from=builder /app/core     /app/core
COPY --from=builder /app/backend  /app/backend
COPY docker-entrypoint.sh         /app/docker-entrypoint.sh

RUN chmod +x /app/docker-entrypoint.sh

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH="/app/core/src" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

USER appuser

WORKDIR /app/backend

EXPOSE 8000

ENTRYPOINT ["/app/docker-entrypoint.sh"]
