#!/usr/bin/env bash
# Pemindai secret (Fase 9): mencari pola kredensial pada file yang di-track git.
#
# Bukan pengganti gitleaks/trufflehog, tapi cukup untuk CI cepat dan
# mencegah kebocoran paling umum. Jalankan: ./scripts/scan_secrets.sh
set -uo pipefail

cd "$(dirname "$0")/.."

# Nilai dev yang memang publik (dipakai docker-compose & .env.example).
ALLOWLIST='minioadmin|ai_assistant:ai_assistant|change-me|example|dummy'

PATTERNS=(
  'sk-[A-Za-z0-9_-]{16,}'                       # API key gaya OpenAI
  'AKIA[0-9A-Z]{16}'                            # AWS access key id
  'gh[pousr]_[A-Za-z0-9]{20,}'                  # GitHub token
  'xox[baprs]-[A-Za-z0-9-]{10,}'                # Slack token
  '-----BEGIN [A-Z ]*PRIVATE KEY-----'          # private key
  'eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.' # JWT
)

FOUND=0
for pattern in "${PATTERNS[@]}"; do
  # -I: lewati biner; hanya file yang di-track git
  MATCHES="$(git ls-files -z | xargs -0 grep -InE "${pattern}" 2>/dev/null \
    | grep -vE "${ALLOWLIST}" || true)"
  if [ -n "${MATCHES}" ]; then
    echo "POTENSI SECRET (pola: ${pattern}):"
    echo "${MATCHES}"
    FOUND=1
  fi
done

if [ "${FOUND}" -eq 0 ]; then
  echo "SECRET SCAN: PASS (tidak ada pola kredensial pada file tracked)"
else
  echo "SECRET SCAN: FAIL — hapus/rotasi nilai di atas sebelum commit"; exit 1
fi
