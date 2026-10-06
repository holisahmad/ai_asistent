# Dockerfile untuk Railway — single stage, pip install langsung
# Cache-bust: v4 (supabase S3 endpoint fix + version 0.2.0)
FROM python:3.12-slim

WORKDIR /app

# Install system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev curl \
    && rm -rf /var/lib/apt/lists/*

# Install uv
RUN pip install --no-cache-dir uv==0.4.29

# Cache-bust arg — ubah nilai ini untuk force rebuild layer install
ARG CACHE_BUST=v4

# Copy semua source
COPY pyproject.toml uv.lock ./
COPY core/ ./core/
COPY backend/ ./backend/
COPY worker/ ./worker/

# Install dependencies langsung ke system Python (tidak pakai venv)
# --system agar packages masuk ke /usr/local/lib/python3.12/site-packages
RUN uv pip install --system --no-cache \
    "fastapi>=0.115" \
    "uvicorn[standard]>=0.34" \
    "pydantic>=2.10" \
    "pydantic-settings>=2.7" \
    "psycopg[binary]>=3.2" \
    "sqlalchemy>=2.0" \
    "alembic>=1.14" \
    "redis>=5.2" \
    "python-multipart>=0.0.20" \
    "bcrypt>=4.2" \
    "email-validator>=2.2" \
    "pgvector>=0.3" \
    "rq>=2.1" \
    "pypdf>=5.1" \
    "python-docx>=1.1" \
    "python-pptx>=1.0" \
    "openpyxl>=3.1" \
    "httpx>=0.28" \
    "minio>=7.2" \
    "boto3>=1.34"

# Install core package
RUN pip install --no-cache-dir -e ./core

# Verifikasi uvicorn tersedia
RUN python -m uvicorn --version

ENV PYTHONPATH="/app/core/src" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app/backend

COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

ENTRYPOINT ["/docker-entrypoint.sh"]
