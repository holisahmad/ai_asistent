# Operations Guide — AI Knowledge Assistant

> **Fase 10: Pilot & Scale** — panduan operasional harian, SLO, monitoring, scale-out,
> dan quality improvement loop untuk tim yang menjalankan sistem di produksi.

Lihat juga: [DEPLOYMENT.md](DEPLOYMENT.md) · [INCIDENT_RESPONSE.md](INCIDENT_RESPONSE.md)

---

## 1. SLO & Error Budget

### Service Level Objectives

| Metrik | SLO | Pengukuran |
|---|---|---|
| **Availability** (health/ready) | ≥ 99,5% per bulan | `/health/ready` HTTP 200 |
| **Latensi chat** first token (p95) | ≤ 5 000 ms | `http_request_duration_seconds` |
| **Latensi API umum** (p95) | ≤ 2 000 ms | `http_request_duration_seconds` |
| **Latensi health** (p95) | ≤ 200 ms | `http_request_duration_seconds` |
| **RAG recall@5** | ≥ 0,80 | `make eval` |
| **RAG citation correctness** | ≥ 0,80 | `make eval` |
| **Halusinasi** | 0,00 | `make eval` |
| **Error rate API** (5xx) | ≤ 1% | `http_requests_total{status="5xx"}` |

### Error budget (availability 99,5%)

```
Downtime per bulan yang diizinkan = (1 - 0.995) × 43200 menit = 216 menit
Bila error budget habis → freeze rilis; prioritaskan reliability
```

---

## 2. Monitoring

### Metrik Prometheus

Endpoint `GET /metrics` (kunci dengan `APP_METRICS_TOKEN`) mengekspor:

| Metrik | Tipe | Label | Catatan |
|---|---|---|---|
| `http_requests_total` | counter | method, route, status | Hitung per status code |
| `http_request_duration_seconds` | histogram | method, route, status | Latensi per endpoint |
| `http_rate_limited_total` | counter | route | Request yang di-429 |
| `app_info` | gauge | — | Selalu 1 (heartbeat) |

**Query Grafana penting**:

```promql
# Error rate 5xx (5 menit terakhir)
rate(http_requests_total{status=~"5xx"}[5m]) / rate(http_requests_total[5m])

# Latensi p95 chat stream
histogram_quantile(0.95,
  rate(http_request_duration_seconds_bucket{route="/api/v1/workspaces/{workspace_id}/chat/stream"}[5m])
)

# Rate limit hits
rate(http_rate_limited_total[5m])
```

### Log

Log API berformat JSON (structured logging):

```json
{
  "timestamp": "2026-10-03T10:00:00+00:00",
  "level": "INFO",
  "logger": "app.api.chat",
  "message": "chat stream selesai",
  "request_id": "abc123def456"
}
```

**Grep berguna**:

```bash
# Error dalam 1 jam terakhir
docker logs aiassistant-api 2>&1 | \
  python3 -c "import sys,json; [print(l) for l in sys.stdin if 'ERROR' in l]" | tail -20

# Request tertentu (tracing via request_id)
docker logs aiassistant-api 2>&1 | grep "abc123def456"

# Circuit breaker events
docker logs aiassistant-api 2>&1 | grep "circuit breaker"

# Rate limit events
docker logs aiassistant-api 2>&1 | grep "rate limit"
```

### Audit log

Bila `APP_AUDIT_LOG_FILE` diset, setiap aksi penting dicatat ke JSONL:

```bash
# Upload file hari ini
grep '"action":"file_upload"' /var/log/ai_asistent/audit.jsonl \
  | grep "$(date +%Y-%m-%d)"

# Login dari IP tertentu
grep '"action":"login"' /var/log/ai_asistent/audit.jsonl \
  | grep "1.2.3.4"
```

---

## 3. Operasi Rutin

### Harian (otomatis via cron/timer)

```bash
# Backup (02:00 UTC — sudah dijadwalkan)
./scripts/cron_backup.sh

# Setelah backup: verifikasi
ls -la backups/ | tail -5
cat backups/$(ls backups/ | tail -1)/metadata.json
```

### Mingguan

```bash
# 1. Restore drill (verifikasi backup dapat dipulihkan)
make restore-drill

# 2. Evaluasi kualitas RAG
make eval ARGS=--write    # hasilnya di docs/reports/eval-<stamp>.md

# 3. Benchmark SLO
./scripts/benchmark.sh https://yourdomain.com 50

# 4. Audit dependensi
make scan-deps

# 5. Cek embedding stale
make reembed ARGS=--check
```

### Bulanan

```bash
# 1. Rotasi token/credential
# - APP_OPENAI_API_KEY → dashboard provider
# - APP_METRICS_TOKEN → edit .env.prod, restart
# - APP_MINIO_SECRET_KEY → MinIO admin

# 2. Review log error bulan lalu
docker logs aiassistant-api 2>&1 | grep '"level":"ERROR"' | wc -l

# 3. Cek ukuran database
docker exec aiassistant-postgres psql -U ai_assistant -c \
  "SELECT pg_size_pretty(pg_database_size('ai_assistant'));"

# 4. Cek index vector (pgvector)
docker exec aiassistant-postgres psql -U ai_assistant -c \
  "SELECT schemaname, tablename, indexname, pg_size_pretty(pg_relation_size(indexname::regclass))
   FROM pg_indexes WHERE tablename='document_chunks';"
```

---

## 4. Quality Improvement Loop (Fase 10)

Prinsip: **ukur dulu, baru ubah**. Setiap perubahan pada retrieval, chunking, atau
prompt harus melewati evaluasi sebelum masuk produksi.

### Alur evaluasi

```
1. Ambil dataset evaluasi
   docs/eval/retrieval_dataset.json       (gate CI — selalu hijau)
   docs/eval/retrieval_dataset_hard.json  (headroom — untuk mengukur uplift)

2. Jalankan baseline
   make eval ARGS='--write'              → catat metrik saat ini

3. Ubah parameter/konfigurasi
   mis. APP_RETRIEVAL_TOP_K=8, APP_ANSWER_MODE=auto

4. Bandingkan
   make eval ARGS='--set top_k=8 --write'

5. Hanya merge bila delta positif (atau tidak ada regresi)
```

### Parameter yang dapat di-tune tanpa kode

```bash
# Kurangi biaya token (ekstraktif bila yakin)
APP_ANSWER_MODE=auto
APP_ANSWER_EXTRACTIVE_THRESHOLD=0.45

# Tingkatkan recall (lebih banyak kandidat)
APP_RETRIEVAL_CANDIDATES=32
APP_RETRIEVAL_TOP_K=8

# Aktifkan query rewriting (bila terbukti uplift)
APP_QUERY_REWRITE_ENABLED=true

# Perbesar konteks LLM (bila jawaban terpotong)
APP_RAG_MAX_CONTEXT_CHARS=8000
```

### Kapan reindex diperlukan

| Kondisi | Tindakan |
|---|---|
| `APP_EMBEDDING_PROVIDER` berubah | `make reembed` wajib |
| `APP_EMBEDDING_DIM` berubah | `make reembed` wajib |
| `APP_FASTEMBED_MODEL` berubah | `make reembed` wajib |
| Dokumen gagal index (`status=failed`) | `POST /files/{id}/reindex` per file |
| Skor retrieval turun tanpa sebab jelas | `make reembed ARGS=--check` |

---

## 5. Scale-Out Guide

### Tahap 2 — Scale API horizontal

```bash
# docker-compose.prod.yml: tambah replicas
services:
  api:
    deploy:
      replicas: 3

# Tambah nginx upstream
upstream api_backend {
    server api_1:8000;
    server api_2:8000;
    server api_3:8000;
    keepalive 32;
}
```

Syarat: `APP_DATABASE_URL` dan `APP_REDIS_URL` harus sama di semua instance (sudah stateless).

### Tahap 3 — Scale Worker

```bash
# Jalankan worker tambahan dengan nama berbeda
APP_WORKER_NAME=worker-2 docker compose up -d worker
# Atau via docker-compose.prod.yml dengan replicas dan env override
```

Batasan RQ: semua worker baca queue yang sama di Redis — scale horizontal otomatis.

### Tahap 4 — Migrasi ke Qdrant (bila pgvector tidak cukup)

```bash
# 1. Deploy Qdrant
docker run -d -p 6333:6333 qdrant/qdrant

# 2. Set config (tidak ubah kode — hanya adapter)
# APP_VECTOR_STORE=qdrant (belum diimplementasi — buat PR bila diperlukan)

# 3. Reindex penuh
make reembed

# 4. Eval sebelum dan sesudah untuk memastikan kualitas tidak turun
make eval ARGS='--write'
```

---

## 6. Token & Biaya

### Estimasi biaya per query (embedding OpenAI)

```
text-embedding-3-small: $0.02 / 1M token
rata-rata dokumen 500 token × 77 chunk = 38,500 token → $0.00077 satu kali
rata-rata query: 20 token → $0.0000004 per query (embedding query)
```

### Estimasi biaya per query (LLM)

```
gpt-4o-mini: $0.15 input / $0.60 output per 1M token
konteks RAG ~2000 token + jawaban ~300 token
→ ~$0.0003 + $0.00018 = ~$0.00048 per query generatif

Mode extractive: $0 LLM (tanpa LLM call bila threshold terpenuhi)
Mode auto: ~50% query extractive = ~50% penghematan biaya LLM
```

### Monitoring biaya

```bash
# Estimasi dari laporan eval (per 15 kueri)
make eval ARGS='--write' | grep "cost"

# Bench 30 iterasi
make bench ARGS='--iterations 30' | grep "cost"
```

---

## 7. Checklist Mingguan (On-Call)

```
[ ] /health/ready hijau
[ ] make restore-drill → PASS
[ ] make eval → semua gate PASS
[ ] ./scripts/benchmark.sh → PASS
[ ] make reembed ARGS=--check → tidak ada stale
[ ] docker compose ps → semua container running
[ ] df -h → disk < 80% di server produksi
[ ] backups/ berisi backup ≤ 24 jam terakhir
[ ] Log error review (docker logs aiassistant-api | grep ERROR)
[ ] Tidak ada P0/P1 open di backlog insiden
```
