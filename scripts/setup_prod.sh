#!/usr/bin/env bash
# setup_prod.sh — Setup produksi: push git, migrasi Supabase, set Vercel env vars, deploy
#
# Pemakaian:
#   export GITHUB_TOKEN="ghp_..."
#   export VERCEL_TOKEN="vcp_..."
#   export SUPABASE_DB_PASS="password_baru"
#   ./scripts/setup_prod.sh
#
# Semua credential dibaca dari env var — tidak ada hardcode di sini.
set -euo pipefail

# ---- Warna ----
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
ok()   { echo -e "  ${GREEN}✓${NC}  $1"; }
fail() { echo -e "  ${RED}✗${NC}  $1"; exit 1; }
info() { echo -e "  ${YELLOW}→${NC}  $1"; }

# ---- Validasi env vars ----
echo "============================================================"
echo "AI Knowledge Assistant — Production Setup"
echo "============================================================"
echo ""

: "${GITHUB_TOKEN:?Set GITHUB_TOKEN terlebih dahulu}"
: "${VERCEL_TOKEN:?Set VERCEL_TOKEN terlebih dahulu}"
: "${SUPABASE_DB_PASS:?Set SUPABASE_DB_PASS terlebih dahulu}"

VERCEL_PROJECT_ID="prj_hyjBdtjujwvxGrgNo8pt37zs3bd4"
SUPABASE_PROJECT_ID="nykffalzlxbmuatxgbhb"
SUPABASE_REGION="ap-northeast-1"
# Gunakan Supavisor pooler (IPv4) bukan direct host (IPv6-only di region ini)
# Session mode port 5432: kompatibel dengan Alembic migration
SUPABASE_POOLER_HOST="aws-0-ap-northeast-1.pooler.supabase.com"
SUPABASE_DB_URL="postgresql+psycopg://postgres.${SUPABASE_PROJECT_ID}:${SUPABASE_DB_PASS}@${SUPABASE_POOLER_HOST}:5432/postgres?sslmode=require"
SUPABASE_DB_URL_SYNC="${SUPABASE_DB_URL}"
export SUPABASE_DB_URL

ok "Semua env var tersedia"

# ---- 1. Push ke GitHub ----
echo ""
echo ">> 1. Push ke GitHub"
cd "$(dirname "$0")/.."

# Set remote dengan token
git remote set-url origin "https://${GITHUB_TOKEN}@github.com/holisahmad/ai_asistent.git"

# Push
git push origin main
ok "Push ke GitHub berhasil"

# Bersihkan token dari remote URL setelah push
git remote set-url origin "https://github.com/holisahmad/ai_asistent.git"

# ---- 2. Migrasi Alembic ke Supabase ----
echo ""
echo ">> 2. Migrasi database ke Supabase"
info "Koneksi: ${SUPABASE_POOLER_HOST}:5432 (IPv4 pooler, session mode)"

cd "$(dirname "$0")/../backend"
APP_DATABASE_URL="${SUPABASE_DB_URL}" uv run alembic upgrade head
ok "Migrasi Alembic selesai (0001 → 0006)"
cd ..

# ---- 3. Set env vars di Vercel ----
echo ""
echo ">> 3. Set environment variables di Vercel"

export VERCEL_PROJECT_ID="${VERCEL_PROJECT_ID}"
export SUPABASE_DB_URL="${SUPABASE_DB_URL}"

python3 "$(dirname "$0")/vercel_env_set.py"
ok "Env vars di Vercel selesai"

# ---- 4 & 5. Config project + trigger deploy ----
echo ""
echo ">> 4 & 5. Konfigurasi Vercel + Trigger Deploy"

python3 "$(dirname "$0")/vercel_deploy.py"

# ---- Ringkasan ----
echo ""
echo "============================================================"
echo "SELESAI"
echo ""
echo "  GitHub:   https://github.com/holisahmad/ai_asistent"
echo "  Vercel:   https://ai-asistent-nu.vercel.app"
echo "  Supabase: https://supabase.com/dashboard/project/${SUPABASE_PROJECT_ID}"
echo ""
echo "Langkah berikutnya:"
echo "  1. Pantau deploy: https://vercel.com/dashboard"
echo "  2. Setelah deploy sukses, cek: https://ai-asistent-nu.vercel.app"
echo "  3. Jalankan pilot check: ./scripts/pilot_check.sh https://ai-asistent-nu.vercel.app"
echo "============================================================"
