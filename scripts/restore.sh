#!/usr/bin/env bash
# Restore AI Knowledge Assistant (Fase 9).
#
# Pemakaian:
#   ./scripts/restore.sh <backup_dir> [TARGET_DB]
#
# TARGET_DB default = POSTGRES_DB (menimpa database aplikasi).
# Gunakan database terpisah untuk drill (lihat scripts/restore_drill.sh).
set -euo pipefail

BACKUP_DIR="${1:?Pemakaian: ./scripts/restore.sh <backup_dir> [TARGET_DB]}"
TARGET_DB="${2:-${POSTGRES_DB:-ai_assistant}}"
PG_CONTAINER="${PG_CONTAINER:-aiassistant-postgres}"
MINIO_CONTAINER="${MINIO_CONTAINER:-aiassistant-minio}"
PG_USER="${POSTGRES_USER:-ai_assistant}"
MINIO_DATA_PATH="${MINIO_DATA_PATH:-/bitnami/minio/data}"

test -s "${BACKUP_DIR}/postgres.dump" || { echo "FATAL: ${BACKUP_DIR}/postgres.dump tidak ada"; exit 1; }

echo "==> Restore database ke ${TARGET_DB}"
docker exec -i "${PG_CONTAINER}" pg_restore -U "${PG_USER}" -d "${TARGET_DB}" \
  --clean --if-exists --no-owner --single-transaction < "${BACKUP_DIR}/postgres.dump"

if [ -d "${BACKUP_DIR}/minio" ]; then
  echo "==> Restore object storage ke ${MINIO_CONTAINER}:${MINIO_DATA_PATH}"
  docker cp "${BACKUP_DIR}/minio/." "${MINIO_CONTAINER}:${MINIO_DATA_PATH}/"
else
  echo "PERINGATAN: tidak ada direktori minio pada backup; objek dilewati"
fi

echo "==> Restore selesai untuk ${TARGET_DB}"
