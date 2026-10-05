#!/usr/bin/env bash
# scripts/migrate_prod.sh
# Jalankan migrasi Alembic ke database production (Supabase / managed Postgres).
#
# Pemakaian:
#   APP_DATABASE_URL="postgresql+psycopg://postgres:PASS@db.PROJECT.supabase.co:5432/postgres?sslmode=require" \
#     ./scripts/migrate_prod.sh
#
# Atau cukup set APP_DATABASE_URL di environment / .env.prod lalu:
#   ./scripts/migrate_prod.sh
#
# Di Railway: tambahkan sebagai Deploy Command:
#   ./scripts/migrate_prod.sh

set -euo pipefail

# ── Warna output ─────────────────────────────────────────────────────────────
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
info()  { echo -e "${GREEN}[migrate]${NC} $*"; }
warn()  { echo -e "${YELLOW}[migrate]${NC} $*"; }
error() { echo -e "${RED}[migrate]${NC} $*"; exit 1; }

# ── Validasi APP_DATABASE_URL ─────────────────────────────────────────────────
if [ -z "${APP_DATABASE_URL:-}" ]; then
  error "APP_DATABASE_URL tidak diset. Export dulu sebelum menjalankan skrip ini."
fi

info "Target: ${APP_DATABASE_URL%%@*}@*** (URL disembunyikan)"

# ── Pastikan kita di root project ─────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

# ── Cek apakah uv tersedia ────────────────────────────────────────────────────
if ! command -v uv &>/dev/null; then
  warn "uv tidak ditemukan, mencoba dengan python langsung..."
  # Fallback: jalankan via python di venv (Docker/Railway path)
  if [ -d "/app/.venv" ]; then
    export PATH="/app/.venv/bin:$PATH"
    RUNNER="python -m alembic"
  else
    error "uv dan /app/.venv keduanya tidak tersedia."
  fi
else
  RUNNER="uv run alembic"
fi

# ── Jalankan migrasi ───────────────────────────────────────────────────────────
info "Menjalankan: alembic upgrade head"
cd backend
${RUNNER} upgrade head

info "✅ Migrasi selesai."
