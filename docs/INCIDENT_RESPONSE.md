# Incident Response Runbook — AI Knowledge Assistant

> **Gunakan dokumen ini saat terjadi insiden produksi.**
> Tujuan: diagnosis cepat, dampak terkendali, rollback terukur, dan postmortem ≤ 3 hari kerja.

Lihat juga: [DEPLOYMENT.md](DEPLOYMENT.md) · [OPERATIONS.md](OPERATIONS.md)

---

## Severity Level

| Level | Definisi | Respons |
|---|---|---|
| **P0 — Kritis** | Layanan tidak bisa diakses sama sekali; data terancam hilang | Segera — incident commander wajib aktif |
| **P1 — Tinggi** | Fitur inti gagal (chat/upload); latensi > 10× SLO | ≤ 30 menit respons awal |
| **P2 — Sedang** | Fitur degradasi parsial; error rate naik; 1 tenant terdampak | ≤ 2 jam |
| **P3 — Rendah** | Bug minor; SLO tidak terlampaui | Sprint berikutnya |

---

## Kontak On-Call

> Edit bagian ini dengan kontak nyata sebelum go-live.

| Peran | Nama | Kontak |
|---|---|---|
| Incident Commander | — | — |
| Backend on-call | — | — |
| Infra on-call | — | — |
| Eskalasi manajemen | — | — |

---

## 1. Deteksi & Triase Awal (< 5 menit)

### Sumber sinyal

```bash
# 1. Health check
curl https://yourdomain.com/health/live    # proses hidup?
curl https://yourdomain.com/health/ready   # DB/Redis/MinIO ok?

# 2. Status container
docker compose ps

# 3. Log API (50 baris terakhir)
docker logs aiassistant-api --tail 50 --follow

# 4. Log worker
docker logs aiassistant-worker --tail 50 --follow

# 5. Metrik Prometheus (butuh APP_METRICS_TOKEN)
curl -H "Authorization: Bearer $APP_METRICS_TOKEN" https://yourdomain.com/metrics \
  | grep -E "http_requests_total|http_rate_limited|http_request_duration"

# 6. Doctor lokal (untuk setup dev)
make doctor
```

### Pertanyaan triase

1. Apakah `/health/live` HTTP 200? → jika tidak, proses API mati → lihat §2
2. Apakah `/health/ready` HTTP 200? → jika tidak, infra bermasalah → lihat §3
3. Apakah hanya satu tenant/workspace terdampak? → lihat §5
4. Apakah terjadi setelah deploy baru? → rollback langsung → lihat §6

---

## 2. API Tidak Merespons (P0)

**Gejala**: HTTP timeout atau connection refused di semua endpoint.

```bash
# Cek container
docker compose ps aiassistant-api

# Restart API
docker compose restart api

# Cek log crash
docker logs aiassistant-api --tail 100

# Jika masih gagal: rebuild dan up ulang
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d api

# Verifikasi
curl https://yourdomain.com/health/live
```

**Jika API tidak mau start** (crash loop):
1. Cek log untuk `ImportError` / `RuntimeError` — biasanya konfigurasi/dependency
2. Cek `.env.prod`: semua variabel wajib terisi?
3. Rollback ke image sebelumnya → lihat §6

---

## 3. Infra Bermasalah (DB / Redis / MinIO)

**Gejala**: `/health/ready` HTTP 503 dengan detail `"database": "unavailable"`.

```bash
# Cek semua container infra
docker compose ps postgres redis minio

# Restart infra spesifik
docker compose restart postgres   # atau redis / minio

# Cek log Postgres
docker logs aiassistant-postgres --tail 50

# Cek koneksi Postgres dari host
docker exec aiassistant-postgres pg_isready -U ai_assistant

# Cek disk (volume penuh?)
df -h
docker system df

# Cek Redis
docker exec aiassistant-redis redis-cli ping

# Cek MinIO
curl http://localhost:9000/minio/health/live
```

**Volume penuh (Postgres)**:
```bash
# Identifikasi tabel besar
docker exec aiassistant-postgres psql -U ai_assistant -c \
  "SELECT relname, pg_size_pretty(pg_total_relation_size(oid)) AS size
   FROM pg_class WHERE relkind='r' ORDER BY pg_total_relation_size(oid) DESC LIMIT 10;"

# VACUUM + ANALYZE setelah pembersihan
docker exec aiassistant-postgres psql -U ai_assistant -c "VACUUM ANALYZE;"
```

---

## 4. Latensi Tinggi / Chat Lambat

**Gejala**: respons chat > 10 detik; timeout; SSE terpotong.

```bash
# Benchmark cepat
./scripts/benchmark.sh https://yourdomain.com 10

# Cek metrik latensi
curl -H "Authorization: Bearer $APP_METRICS_TOKEN" https://yourdomain.com/metrics \
  | grep "http_request_duration_seconds"

# Cek log retrieval (debug)
docker logs aiassistant-api --tail 100 | grep -E "retrieval|llm|rag"

# Cek circuit breaker
docker logs aiassistant-api | grep "circuit breaker"
```

**Tindakan**:
1. Circuit breaker LLM terbuka → provider LLM bermasalah:
   - Cek `APP_OPENAI_BASE_URL` masih aktif
   - Fallback ke provider lain sementara
2. Retrieval lambat → kurangi `APP_RETRIEVAL_CANDIDATES` sementara (edit `.env.prod`, restart API)
3. Worker backlog → cek antrian RQ:
   ```bash
   docker exec aiassistant-redis redis-cli -n 0 llen rq:queue:default
   ```

---

## 5. Satu Tenant Terdampak

**Gejala**: user dari workspace tertentu gagal chat/upload; lainnya normal.

```bash
# Cek status file workspace (ganti WS_ID)
docker exec aiassistant-postgres psql -U ai_assistant -c \
  "SELECT status, count(*) FROM files WHERE workspace_id='WS_ID' GROUP BY status;"

# Cek job yang gagal
docker exec aiassistant-postgres psql -U ai_assistant -c \
  "SELECT id, status, error FROM files WHERE workspace_id='WS_ID' AND status='failed' LIMIT 10;"

# Reindex manual semua file failed di workspace
# (via API — butuh token admin workspace)
curl -X POST https://yourdomain.com/api/v1/workspaces/WS_ID/files/FILE_ID/reindex \
  -H "Authorization: Bearer ADMIN_TOKEN"
```

---

## 6. Rollback

### Rollback aplikasi (image/tag sebelumnya)

```bash
cd /opt/ai_asistent

# Cek tag yang tersedia
git log --oneline -10

# Checkout tag/commit sebelumnya
git checkout v1.2.3   # atau commit SHA

# Rebuild + deploy
docker compose -f docker-compose.yml -f docker-compose.prod.yml build
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d api worker

# Verifikasi
curl https://yourdomain.com/version
curl https://yourdomain.com/health/ready
```

### Rollback database (dari backup)

> ⚠️ **Destruktif** — backup data saat ini sebelum rollback!

```bash
# 1. Backup kondisi sekarang
make backup

# 2. Stop API dan worker dulu
docker compose stop api worker

# 3. Restore dari backup terakhir yang baik
make restore DIR=backups/20261003T020000Z

# 4. Start ulang
docker compose start api worker

# 5. Verifikasi
curl https://yourdomain.com/health/ready
make smoke
```

### Rollback konfigurasi

```bash
# Lihat perubahan .env.prod yang mencurigakan
git diff HEAD~1 HEAD -- .env.example   # env example sebagai proxy

# Revert ke nilai lama manual, lalu restart
docker compose restart api worker
```

---

## 7. Kebocoran Data / Security Incident

**Langkah segera (< 15 menit)**:

1. **Rotasi credential yang berpotensi bocor**:
   - `APP_OPENAI_API_KEY` → dashboard provider
   - `APP_MINIO_SECRET_KEY` → MinIO console
   - `APP_METRICS_TOKEN` → edit `.env.prod`, restart

2. **Audit log**:
   ```bash
   # Cari akses mencurigakan di log
   docker logs aiassistant-api 2>&1 | grep -E '"action":"login"|"action":"file_download"' \
     | grep -v '"user_id":"known-user"' | tail -50
   
   # Atau dari file audit log (bila APP_AUDIT_LOG_FILE diset)
   grep '"action":"file_download"' /var/log/ai_asistent/audit.jsonl | tail -20
   ```

3. **Blokir IP mencurigakan** (di nginx atau firewall):
   ```bash
   # Tambah ke nginx.conf (dalam server block)
   # deny 1.2.3.4;
   docker compose restart nginx
   ```

4. **Notifikasi** pengguna terdampak sesuai kebijakan privasi.

5. **Jangan hapus log** — preserve untuk investigasi.

---

## 8. Postmortem Template

Buat file `docs/postmortems/YYYY-MM-DD-judul.md` dalam 3 hari kerja.

```markdown
# Postmortem: <Judul Singkat>

**Tanggal**: YYYY-MM-DD
**Severity**: P0/P1/P2
**Durasi dampak**: HH:MM – HH:MM (X menit)
**Ditulis oleh**: Nama

## Ringkasan
Satu paragraf: apa yang terjadi, dampak pengguna, dan resolusi.

## Timeline
| Waktu | Kejadian |
|---|---|
| HH:MM | Deteksi pertama |
| HH:MM | Triase dimulai |
| HH:MM | Root cause ditemukan |
| HH:MM | Mitigasi diterapkan |
| HH:MM | Layanan pulih |

## Root Cause
Penjelasan teknis penyebab utama.

## Dampak
- Berapa user/tenant terdampak
- Data hilang / tidak hilang
- Durasi downtime

## Resolusi
Langkah yang diambil untuk memulihkan.

## Tindak Lanjut (Action Items)
| Item | Owner | Target |
|---|---|---|
| Tambah alert untuk X | Nama | YYYY-MM-DD |
| Perbaiki Y | Nama | YYYY-MM-DD |

## Pelajaran
Apa yang berjalan baik, apa yang bisa diperbaiki.
```

---

## 9. Referensi Cepat

```bash
# Semua log sekaligus
docker compose logs --tail 30 --follow

# Restart semua services
docker compose -f docker-compose.yml -f docker-compose.prod.yml restart api worker nginx

# Status lengkap
docker compose ps && curl -s https://yourdomain.com/health/ready | python3 -m json.tool

# Jumlah job RQ pending
docker exec aiassistant-redis redis-cli llen rq:queue:default

# Koneksi aktif Postgres
docker exec aiassistant-postgres psql -U ai_assistant -c \
  "SELECT count(*), state FROM pg_stat_activity GROUP BY state;"

# Benchmark cepat (10 iterasi)
./scripts/benchmark.sh https://yourdomain.com 10

# Scan secrets sebelum commit darurat
make scan-secrets
```
