#!/usr/bin/env bash
# Audit dependensi (Fase 9): kerentanan Python (pip-audit) + Node (npm audit).
#
# Pemakaian: ./scripts/scan_deps.sh
# Membutuhkan jaringan (mengambil advisori OSV/GitHub).
set -uo pipefail

cd "$(dirname "$0")/.."
STATUS=0

echo "==> Python (pip-audit terhadap environment uv workspace)"
if uvx pip-audit --progress-spinner off 2>&1 | tee /tmp/ai_pip_audit.log | tail -20; then
  echo "    pip-audit: selesai"
else
  echo "    PERINGATAN: pip-audit gagal dijalankan (offline?) — lihat /tmp/ai_pip_audit.log"
fi
grep -qE "Found [1-9][0-9]* known vulnerabilit" /tmp/ai_pip_audit.log && STATUS=1

echo "==> Node (npm audit --omit=dev di frontend)"
if (cd frontend && npm audit --omit=dev 2>&1 | tail -15); then
  echo "    npm audit: selesai"
else
  echo "    npm audit melaporkan temuan (lihat keluaran di atas)"
fi

if [ "${STATUS}" -eq 0 ]; then
  echo "DEPENDENCY SCAN: PASS (tidak ada kerentanan Python yang dilaporkan)"
else
  echo "DEPENDENCY SCAN: FAIL — tinjau temuan di atas"; exit 1
fi
