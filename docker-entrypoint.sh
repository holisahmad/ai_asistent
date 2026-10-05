#!/bin/sh
# Entrypoint: jalankan uvicorn dengan $PORT dari Railway
set -e
export PATH="/app/.venv/bin:$PATH"
export PYTHONPATH="/app/core/src"
exec /app/.venv/bin/uvicorn app.main:app \
  --host 0.0.0.0 \
  --port "${PORT:-8000}" \
  --workers 1 \
  --loop uvloop \
  --access-log \
  --log-level info
