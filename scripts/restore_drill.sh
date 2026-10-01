#!/usr/bin/env bash
# Restore drill (Fase 9): buktikan backup bisa dipulihkan & datanya utuh.
#
# Alur: backup → buat DB scratch → restore ke scratch → bandingkan jumlah
# baris beberapa tabel inti → drop scratch → laporkan PASS/FAIL.
set -euo pipefail

PG_CONTAINER="${PG_CONTAINER:-aiassistant-postgres}"
PG_USER="${POSTGRES_USER:-ai_assistant}"
PG_DB="${POSTGRES_DB:-ai_assistant}"
SCRATCH_DB="${SCRATCH_DB:-ai_assistant_restore_drill}"
BACKUP_DIR="${BACKUP_DIR:-./backups}"

echo "==> 1/5 Backup database sumber"
./scripts/backup.sh "${BACKUP_DIR}" >/dev/null
LATEST="$(ls -1dt "${BACKUP_DIR}"/*/ | head -1)"
echo "    backup: ${LATEST}"

echo "==> 2/5 Siapkan database scratch ${SCRATCH_DB}"
docker exec "${PG_CONTAINER}" psql -U "${PG_USER}" -d postgres -q \
  -c "DROP DATABASE IF EXISTS ${SCRATCH_DB};" \
  -c "CREATE DATABASE ${SCRATCH_DB};"

echo "==> 3/5 Restore ke scratch"
docker exec -i "${PG_CONTAINER}" pg_restore -U "${PG_USER}" -d "${SCRATCH_DB}" \
  --no-owner --single-transaction < "${LATEST}/postgres.dump"

TABLES="users workspaces files documents document_chunks chats messages citations audit_events"
echo "==> 4/5 Bandingkan jumlah baris sumber vs hasil restore"
FAILED=0
printf "    %-20s %10s %10s\n" "tabel" "sumber" "restore"
for t in ${TABLES}; do
  SRC="$(docker exec "${PG_CONTAINER}" psql -U "${PG_USER}" -d "${PG_DB}" -tAc "SELECT count(*) FROM ${t}" 2>/dev/null || echo 'n/a')"
  DST="$(docker exec "${PG_CONTAINER}" psql -U "${PG_USER}" -d "${SCRATCH_DB}" -tAc "SELECT count(*) FROM ${t}" 2>/dev/null || echo 'n/a')"
  printf "    %-20s %10s %10s\n" "${t}" "${SRC}" "${DST}"
  if [ "${SRC}" != "${DST}" ]; then FAILED=1; fi
done

echo "==> 5/5 Bersihkan scratch"
docker exec "${PG_CONTAINER}" psql -U "${PG_USER}" -d postgres -q -c "DROP DATABASE ${SCRATCH_DB};"

if [ "${FAILED}" -eq 0 ]; then
  echo "RESTORE DRILL: PASS (semua tabel cocok)"
else
  echo "RESTORE DRILL: FAIL (ada tabel tidak cocok)"; exit 1
fi
