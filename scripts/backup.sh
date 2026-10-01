#!/usr/bin/env bash
# Backup AI Knowledge Assistant (Fase 9): PostgreSQL + object storage (MinIO).
#
# Pemakaian:
#   ./scripts/backup.sh [BACKUP_DIR]        # default ./backups
#
# Menghasilkan:
#   <BACKUP_DIR>/<timestamp>/postgres.dump   (pg_dump format custom)
#   <BACKUP_DIR>/<timestamp>/minio/          (salinan data bucket)
#   <BACKUP_DIR>/<timestamp>/metadata.json   (info sumber + checksum)
set -euo pipefail

BACKUP_DIR="${1:-./backups}"
PG_CONTAINER="${PG_CONTAINER:-aiassistant-postgres}"
MINIO_CONTAINER="${MINIO_CONTAINER:-aiassistant-minio}"
PG_USER="${POSTGRES_USER:-ai_assistant}"
PG_DB="${POSTGRES_DB:-ai_assistant}"
MINIO_DATA_PATH="${MINIO_DATA_PATH:-/bitnami/minio/data}"

TS="$(date -u +%Y%m%dT%H%M%SZ)"
DEST="${BACKUP_DIR}/${TS}"
mkdir -p "${DEST}/minio"

echo "==> Backup database ${PG_DB} dari ${PG_CONTAINER}"
docker exec "${PG_CONTAINER}" pg_dump -U "${PG_USER}" -Fc -d "${PG_DB}" > "${DEST}/postgres.dump"
test -s "${DEST}/postgres.dump" || { echo "FATAL: dump kosong"; exit 1; }

echo "==> Backup object storage (${MINIO_CONTAINER}:${MINIO_DATA_PATH})"
docker cp "${MINIO_CONTAINER}:${MINIO_DATA_PATH}/." "${DEST}/minio/" 2>/dev/null || \
  echo "PERINGATAN: salinan MinIO gagal (container/path tidak ada?)"

PG_SIZE="$(wc -c < "${DEST}/postgres.dump" | tr -d ' ')"
OBJ_COUNT="$(find "${DEST}/minio" -type f 2>/dev/null | wc -l | tr -d ' ')"
PG_SHA="$(shasum -a 256 "${DEST}/postgres.dump" | awk '{print $1}')"
TABLES="$(docker exec "${PG_CONTAINER}" psql -U "${PG_USER}" -d "${PG_DB}" -tAc \
  "SELECT count(*) FROM information_schema.tables WHERE table_schema='public'")"

cat > "${DEST}/metadata.json" <<EOF
{
  "timestamp": "${TS}",
  "database": "${PG_DB}",
  "postgres_dump_bytes": ${PG_SIZE},
  "postgres_dump_sha256": "${PG_SHA}",
  "object_files": ${OBJ_COUNT},
  "public_tables": ${TABLES}
}
EOF

echo "==> Selesai: ${DEST}"
cat "${DEST}/metadata.json"
