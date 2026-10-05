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

# Install semua dependencies ke /app/.venv (tanpa dev deps)
RUN uv sync --locked --no-dev

# ---- Runtime ----
FROM python:3.12-slim AS runtime

# Keamanan: jalankan sebagai user non-root
RUN groupadd -r appuser && useradd -r -g appuser appuser

WORKDIR /app

# Salin venv & source dari builder
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/core   /app/core
COPY --from=builder /app/backend /app/backend

# PATH ke venv
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH="/app/core/src" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

USER appuser

WORKDIR /app/backend

EXPOSE 8000

# Gunakan path eksplisit ke uvicorn di venv — sh -c tidak inherit ENV PATH
CMD ["sh", "-c", "/app/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1 --loop uvloop --access-log --log-level info"]
