#!/usr/bin/env bash
# Backup otomatis AI Knowledge Assistant (Fase 9).
# Dirancang untuk dipanggil oleh cron atau systemd timer.
#
# Pemakaian:
#   ./scripts/cron_backup.sh                   # backup ke ./backups, retensi 7 hari
#   BACKUP_RETAIN_DAYS=14 ./scripts/cron_backup.sh
#
# Pasang ke crontab (backup harian pukul 02:00):
#   0 2 * * * cd /path/to/ai_asistent && ./scripts/cron_backup.sh >> ./backups/cron.log 2>&1
#
# Atau via systemd timer — lihat infra/systemd/ai-backup.{service,timer}
set -euo pipefail

cd "$(dirname "$0")/.."

BACKUP_RETAIN_DAYS="${BACKUP_RETAIN_DAYS:-7}"
LOG_TAG="[cron_backup $(date -u '+%Y-%m-%dT%H:%M:%SZ')]"

echo "${LOG_TAG} Memulai backup"

# Jalankan backup utama
./scripts/backup.sh ./backups

# Hapus backup lebih lama dari retensi
echo "${LOG_TAG} Membersihkan backup lebih lama dari ${BACKUP_RETAIN_DAYS} hari"
find ./backups -maxdepth 1 -type d -name "20*" \
    -mtime "+${BACKUP_RETAIN_DAYS}" \
    -exec echo "  hapus: {}" \; \
    -exec rm -rf {} +

# Hitung backup yang tersisa
REMAINING=$(find ./backups -maxdepth 1 -type d -name "20*" | wc -l | tr -d ' ')
echo "${LOG_TAG} Selesai. Backup tersisa: ${REMAINING}"

# Opsional: kirim notifikasi bila ada WEBHOOK_URL (Slack/Discord compatible)
if [ -n "${WEBHOOK_URL:-}" ]; then
    curl -sf -X POST "${WEBHOOK_URL}" \
        -H "Content-Type: application/json" \
        -d "{\"text\":\"✅ Backup AI Assistant selesai — ${REMAINING} backup tersimpan\"}" \
        || echo "${LOG_TAG} PERINGATAN: gagal kirim notifikasi webhook"
fi
