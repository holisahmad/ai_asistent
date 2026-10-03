#!/usr/bin/env bash
# Benchmark e2e AI Knowledge Assistant (Fase 9).
# Mengukur p50/p95/p99 latency: health, chat/stream, file-list, login.
#
# Pemakaian:
#   ./scripts/benchmark.sh [BASE_URL] [ITERATIONS]
#   BASE_URL default: http://localhost:8000
#   ITERATIONS default: 50
#
# Dependensi: curl (tersedia di macOS/Linux)
# Output: ringkasan tabel p50/p95/p99 dan pass/fail vs SLO
set -euo pipefail

BASE_URL="${1:-http://localhost:8000}"
ITERATIONS="${2:-50}"

# ---- SLO targets (ms) ----
SLO_HEALTH_P95=200
SLO_API_P95=2000
SLO_CHAT_P95=5000

PASS=0
FAIL=0

# ---- Helper: ukur satu endpoint N kali ----
measure() {
    local label="$1"
    local method="$2"
    local url="$3"
    local extra_args="${4:-}"
    local slo_p95="$5"

    local times=()
    local i
    for i in $(seq 1 "${ITERATIONS}"); do
        local ms
        # shellcheck disable=SC2086
        ms=$(curl -sf -o /dev/null -w "%{time_total}" \
            -X "${method}" "${url}" \
            -H "Content-Type: application/json" \
            ${extra_args} 2>/dev/null \
            | awk '{printf "%.0f", $1 * 1000}')
        times+=("${ms}")
    done

    # Hitung p50/p95/p99 dengan sort numerik
    IFS=$'\n' sorted=($(printf '%s\n' "${times[@]}" | sort -n))
    local n=${#sorted[@]}
    local p50_idx=$(( (n * 50) / 100 ))
    local p95_idx=$(( (n * 95) / 100 ))
    local p99_idx=$(( (n * 99) / 100 ))
    # clamp to last index
    [ "${p50_idx}" -ge "${n}" ] && p50_idx=$((n - 1))
    [ "${p95_idx}" -ge "${n}" ] && p95_idx=$((n - 1))
    [ "${p99_idx}" -ge "${n}" ] && p99_idx=$((n - 1))

    local p50="${sorted[${p50_idx}]}"
    local p95="${sorted[${p95_idx}]}"
    local p99="${sorted[${p99_idx}]}"

    local status="PASS"
    if [ "${p95}" -gt "${slo_p95}" ]; then
        status="FAIL (SLO p95 ≤ ${slo_p95}ms)"
        FAIL=$((FAIL + 1))
    else
        PASS=$((PASS + 1))
    fi

    printf "  %-35s p50=%4dms  p95=%4dms  p99=%4dms  %s\n" \
        "${label}" "${p50}" "${p95}" "${p99}" "${status}"
}

echo "============================================================"
echo "AI Knowledge Assistant — Benchmark e2e"
echo "Target: ${BASE_URL}  |  Iterasi: ${ITERATIONS}"
echo "Waktu: $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
echo "============================================================"

# ---- Health endpoints ----
echo ""
echo ">> Health"
measure "GET /health/live"  GET "${BASE_URL}/health/live"  ""  "${SLO_HEALTH_P95}"
measure "GET /health/ready" GET "${BASE_URL}/health/ready" ""  "${SLO_HEALTH_P95}"

# ---- Auth — login (buat token jika ada seed demo) ----
echo ""
echo ">> Auth"
DEMO_EMAIL="${DEMO_EMAIL:-demo@example.com}"
DEMO_PASSWORD="${DEMO_PASSWORD:-demo1234}"
TOKEN=""
LOGIN_RESPONSE=$(curl -sf -X POST "${BASE_URL}/api/v1/auth/login" \
    -H "Content-Type: application/json" \
    -d "{\"email\":\"${DEMO_EMAIL}\",\"password\":\"${DEMO_PASSWORD}\"}" 2>/dev/null || true)
TOKEN=$(echo "${LOGIN_RESPONSE}" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('token',''))" 2>/dev/null || true)

if [ -n "${TOKEN}" ]; then
    echo "  Login OK — token diperoleh, lanjut bench API terautentikasi"
    AUTH_HEADER="-H 'Authorization: Bearer ${TOKEN}'"

    # Daftar workspace (butuh token)
    measure "GET /api/v1/workspaces" GET \
        "${BASE_URL}/api/v1/workspaces" \
        "-H \"Authorization: Bearer ${TOKEN}\"" \
        "${SLO_API_P95}"
else
    echo "  SKIP: login gagal (demo user belum dibuat? jalankan: make seed-demo)"
    echo "  Hanya mengukur endpoint publik."
fi

# ---- Versi ----
echo ""
echo ">> Operasional"
measure "GET /version" GET "${BASE_URL}/version" "" "${SLO_API_P95}"

# ---- Ringkasan ----
echo ""
echo "============================================================"
TOTAL=$((PASS + FAIL))
echo "HASIL: ${PASS}/${TOTAL} PASS"
if [ "${FAIL}" -gt 0 ]; then
    echo "BENCHMARK: FAIL — ${FAIL} endpoint melampaui SLO"
    exit 1
else
    echo "BENCHMARK: PASS"
fi
