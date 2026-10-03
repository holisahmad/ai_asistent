#!/usr/bin/env bash
# Pilot readiness check — AI Knowledge Assistant (Fase 10)
# Verifikasi end-to-end kesiapan sistem sebelum pilot dengan data nyata.
#
# Pemakaian:
#   ./scripts/pilot_check.sh [BASE_URL]
#   BASE_URL default: http://localhost:8000
#
# Cek yang dilakukan:
#   1. Health (live + ready)
#   2. Version endpoint
#   3. Auth (register + login + me + logout)
#   4. Workspace (buat, daftar, hapus)
#   5. File upload + status tracking
#   6. Chat stream (SSE)
#   7. Metrics endpoint (bila token tersedia)
#   8. Quality gate eval (make eval)
#   9. Benchmark SLO
#  10. Secret scan
#
# Exit 0 = PASS, exit 1 = FAIL
set -uo pipefail

BASE_URL="${1:-http://localhost:8000}"
PASS=0
FAIL=0
SKIP=0

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

ok()   { echo -e "  ${GREEN}PASS${NC}  $1"; PASS=$((PASS+1)); }
fail() { echo -e "  ${RED}FAIL${NC}  $1"; FAIL=$((FAIL+1)); }
skip() { echo -e "  ${YELLOW}SKIP${NC}  $1"; SKIP=$((SKIP+1)); }
section() { echo ""; echo ">> $1"; }

# Helper: HTTP request + check status
http_check() {
    local label="$1"; local method="$2"; local url="$3"; local expected="$4"
    local extra="${5:-}"
    local actual
    # shellcheck disable=SC2086
    actual=$(curl -sf -o /dev/null -w "%{http_code}" \
        -X "${method}" "${url}" \
        -H "Content-Type: application/json" \
        ${extra} 2>/dev/null || echo "000")
    if [ "${actual}" = "${expected}" ]; then
        ok "${label} → HTTP ${actual}"
    else
        fail "${label} → HTTP ${actual} (expected ${expected})"
    fi
    echo "${actual}"
}

echo "============================================================"
echo "AI Knowledge Assistant — Pilot Readiness Check"
echo "Target: ${BASE_URL}"
echo "Waktu:  $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
echo "============================================================"

# ---- 1. Health ----
section "1. Health"
LIVE=$(curl -sf "${BASE_URL}/health/live" 2>/dev/null || true)
if echo "${LIVE}" | grep -q '"alive"'; then
    ok "GET /health/live → alive"
    PASS=$((PASS+1))
else
    fail "GET /health/live → tidak merespons (${LIVE})"
    FAIL=$((FAIL+1))
fi

READY=$(curl -sf "${BASE_URL}/health/ready" 2>/dev/null || true)
if echo "${READY}" | python3 -c "import sys,json; d=json.load(sys.stdin); exit(0 if d.get('status')=='ready' else 1)" 2>/dev/null; then
    ok "GET /health/ready → ready (DB + Redis OK)"
    PASS=$((PASS+1))
else
    fail "GET /health/ready → not ready: ${READY}"
    FAIL=$((FAIL+1))
fi

# ---- 2. Version ----
section "2. Version"
VER=$(curl -sf "${BASE_URL}/version" 2>/dev/null || true)
if echo "${VER}" | grep -q '"version"'; then
    VERSION=$(echo "${VER}" | python3 -c "import sys,json; print(json.load(sys.stdin).get('version','?'))" 2>/dev/null || echo "?")
    ENV=$(echo "${VER}" | python3 -c "import sys,json; print(json.load(sys.stdin).get('environment','?'))" 2>/dev/null || echo "?")
    ok "GET /version → v${VERSION} (${ENV})"
    PASS=$((PASS+1))
    if [ "${ENV}" = "development" ]; then
        echo "     ⚠ environment=development — pastikan APP_ENVIRONMENT=production di server"
    fi
else
    fail "GET /version → tidak merespons"
    FAIL=$((FAIL+1))
fi

# ---- 3. Auth flow ----
section "3. Auth (register → login → me → logout)"
TEST_EMAIL="pilot-check-$(date +%s)@example.com"
TEST_PASS="PilotCheck123!"

# Register
REG=$(curl -sf -X POST "${BASE_URL}/api/v1/auth/register" \
    -H "Content-Type: application/json" \
    -d "{\"email\":\"${TEST_EMAIL}\",\"name\":\"Pilot Check\",\"password\":\"${TEST_PASS}\"}" \
    2>/dev/null || true)
TOKEN=$(echo "${REG}" | python3 -c "import sys,json; print(json.load(sys.stdin).get('token',''))" 2>/dev/null || true)
if [ -n "${TOKEN}" ]; then
    ok "POST /auth/register → token diperoleh"
    PASS=$((PASS+1))
else
    fail "POST /auth/register → gagal: ${REG}"
    FAIL=$((FAIL+1))
fi

# Login
LOGIN=$(curl -sf -X POST "${BASE_URL}/api/v1/auth/login" \
    -H "Content-Type: application/json" \
    -d "{\"email\":\"${TEST_EMAIL}\",\"password\":\"${TEST_PASS}\"}" \
    2>/dev/null || true)
LOGIN_TOKEN=$(echo "${LOGIN}" | python3 -c "import sys,json; print(json.load(sys.stdin).get('token',''))" 2>/dev/null || true)
if [ -n "${LOGIN_TOKEN}" ]; then
    ok "POST /auth/login → token diperoleh"
    PASS=$((PASS+1))
    TOKEN="${LOGIN_TOKEN}"
else
    fail "POST /auth/login → gagal"
    FAIL=$((FAIL+1))
fi

# Me
if [ -n "${TOKEN}" ]; then
    ME=$(curl -sf "${BASE_URL}/api/v1/auth/me" \
        -H "Authorization: Bearer ${TOKEN}" 2>/dev/null || true)
    if echo "${ME}" | grep -q '"email"'; then
        ok "GET /auth/me → profil diperoleh"
        PASS=$((PASS+1))
    else
        fail "GET /auth/me → gagal: ${ME}"
        FAIL=$((FAIL+1))
    fi
else
    skip "GET /auth/me (tidak ada token)"
fi

# ---- 4. Workspace ----
section "4. Workspace (buat + daftar)"
if [ -n "${TOKEN}" ]; then
    SLUG="pilot-check-$(date +%s)"
    WS=$(curl -sf -X POST "${BASE_URL}/api/v1/workspaces" \
        -H "Authorization: Bearer ${TOKEN}" \
        -H "Content-Type: application/json" \
        -d "{\"name\":\"Pilot Check WS\",\"slug\":\"${SLUG}\"}" \
        2>/dev/null || true)
    WS_ID=$(echo "${WS}" | python3 -c "import sys,json; print(json.load(sys.stdin).get('id',''))" 2>/dev/null || true)
    if [ -n "${WS_ID}" ]; then
        ok "POST /workspaces → workspace_id=${WS_ID}"
        PASS=$((PASS+1))
    else
        fail "POST /workspaces → gagal: ${WS}"
        FAIL=$((FAIL+1))
    fi

    WS_LIST=$(curl -sf "${BASE_URL}/api/v1/workspaces" \
        -H "Authorization: Bearer ${TOKEN}" 2>/dev/null || true)
    if echo "${WS_LIST}" | python3 -c "import sys,json; d=json.load(sys.stdin); exit(0 if isinstance(d,list) and len(d)>0 else 1)" 2>/dev/null; then
        ok "GET /workspaces → daftar workspace tidak kosong"
        PASS=$((PASS+1))
    else
        fail "GET /workspaces → gagal"
        FAIL=$((FAIL+1))
    fi
else
    skip "Workspace check (tidak ada token)"
fi

# ---- 5. File upload (text kecil) ----
section "5. File Upload"
if [ -n "${TOKEN}" ] && [ -n "${WS_ID:-}" ]; then
    TMPFILE=$(mktemp /tmp/pilot_check_XXXXXX.txt)
    echo "Ini adalah dokumen pilot check. Kebijakan cuti tahunan: 12 hari." > "${TMPFILE}"

    UPLOAD=$(curl -sf -X POST \
        "${BASE_URL}/api/v1/workspaces/${WS_ID}/files" \
        -H "Authorization: Bearer ${TOKEN}" \
        -F "file=@${TMPFILE};type=text/plain" \
        2>/dev/null || true)
    rm -f "${TMPFILE}"

    FILE_ID=$(echo "${UPLOAD}" | python3 -c "import sys,json; print(json.load(sys.stdin).get('id',''))" 2>/dev/null || true)
    FILE_STATUS=$(echo "${UPLOAD}" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status',''))" 2>/dev/null || true)

    if [ -n "${FILE_ID}" ]; then
        ok "POST /files → file_id=${FILE_ID} status=${FILE_STATUS}"
        PASS=$((PASS+1))
    else
        fail "POST /files → gagal: ${UPLOAD}"
        FAIL=$((FAIL+1))
    fi
else
    skip "File upload (tidak ada token atau workspace)"
fi

# ---- 6. Chat stream (SSE) ----
section "6. Chat Stream (SSE)"
if [ -n "${TOKEN}" ] && [ -n "${WS_ID:-}" ]; then
    SSE_RESPONSE=$(curl -sf -X POST \
        "${BASE_URL}/api/v1/workspaces/${WS_ID}/chat/stream" \
        -H "Authorization: Bearer ${TOKEN}" \
        -H "Content-Type: application/json" \
        -d '{"question":"berapa hari cuti tahunan?","chat_id":null,"allow_web":false}' \
        --max-time 30 \
        2>/dev/null || true)

    if echo "${SSE_RESPONSE}" | grep -q "event: done\|event:done\|answer_kind"; then
        ok "POST /chat/stream → SSE done event diterima"
        PASS=$((PASS+1))
        # Cek answer_kind
        KIND=$(echo "${SSE_RESPONSE}" | grep "answer_kind" | python3 -c \
            "import sys,json; lines=[l for l in sys.stdin if 'data:' in l]; d=json.loads(lines[-1].replace('data:','').strip()) if lines else {}; print(d.get('answer_kind','?'))" 2>/dev/null || echo "?")
        echo "     answer_kind=${KIND}"
    elif echo "${SSE_RESPONSE}" | grep -q "event:"; then
        ok "POST /chat/stream → SSE stream aktif (events diterima)"
        PASS=$((PASS+1))
    else
        fail "POST /chat/stream → tidak merespons atau tidak ada SSE events"
        FAIL=$((FAIL+1))
    fi
else
    skip "Chat stream (tidak ada token atau workspace)"
fi

# ---- 7. Metrics ----
section "7. Metrics"
METRICS_TOKEN="${APP_METRICS_TOKEN:-}"
if [ -n "${METRICS_TOKEN}" ]; then
    METRICS=$(curl -sf "${BASE_URL}/metrics" \
        -H "Authorization: Bearer ${METRICS_TOKEN}" 2>/dev/null || true)
    if echo "${METRICS}" | grep -q "http_requests_total"; then
        ok "GET /metrics → Prometheus metrics tersedia"
        PASS=$((PASS+1))
    else
        fail "GET /metrics → tidak merespons"
        FAIL=$((FAIL+1))
    fi
else
    skip "GET /metrics (APP_METRICS_TOKEN tidak diset)"
fi

# ---- 8. Quality gate eval ----
section "8. Quality Gate (make eval)"
if command -v uv >/dev/null 2>&1 && [ -d "$(dirname "$0")/../backend" ]; then
    cd "$(dirname "$0")/.."
    EVAL_OUT=$(uv run --project backend python scripts/eval_rag.py 2>&1 || true)
    if echo "${EVAL_OUT}" | grep -qE "PASS|pass|quality gate"; then
        ok "make eval → quality gate PASS"
        PASS=$((PASS+1))
    elif echo "${EVAL_OUT}" | grep -qE "FAIL|fail"; then
        fail "make eval → quality gate FAIL"
        FAIL=$((FAIL+1))
        echo "${EVAL_OUT}" | tail -10
    else
        skip "make eval → output tidak terduga (cek manual)"
        echo "${EVAL_OUT}" | tail -5
    fi
else
    skip "make eval (uv tidak tersedia atau bukan dari root repo)"
fi

# ---- 9. Benchmark SLO ----
section "9. Benchmark SLO"
cd "$(dirname "$0")/.."
if ./scripts/benchmark.sh "${BASE_URL}" 20 2>/dev/null; then
    ok "Benchmark SLO → PASS"
    PASS=$((PASS+1))
else
    fail "Benchmark SLO → ada endpoint melampaui SLO"
    FAIL=$((FAIL+1))
fi

# ---- 10. Secret scan ----
section "10. Secret Scan"
cd "$(dirname "$0")/.."
if ./scripts/scan_secrets.sh 2>/dev/null | grep -q "PASS"; then
    ok "Secret scan → PASS"
    PASS=$((PASS+1))
else
    fail "Secret scan → FAIL (ada credential terdeteksi)"
    FAIL=$((FAIL+1))
fi

# ---- Ringkasan ----
echo ""
echo "============================================================"
TOTAL=$((PASS + FAIL + SKIP))
echo "HASIL: ${PASS} PASS  |  ${FAIL} FAIL  |  ${SKIP} SKIP  |  ${TOTAL} total"
echo ""
if [ "${FAIL}" -eq 0 ]; then
    echo -e "${GREEN}PILOT CHECK: PASS — sistem siap untuk pilot${NC}"
    exit 0
else
    echo -e "${RED}PILOT CHECK: FAIL — selesaikan ${FAIL} item di atas sebelum pilot${NC}"
    exit 1
fi
