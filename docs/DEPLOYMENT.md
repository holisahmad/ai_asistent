# Deployment Guide — AI Knowledge Assistant

> **Fase 9 Production Hardening** — dokumen ini adalah satu-satunya sumber kebenaran
> untuk deployment, operasi rutin, backup, dan scaling. Deployment harus dapat diulang
> dari dokumen ini tanpa pengetahuan tacit.

Lihat juga: [CONFIG_REFERENCE.md](CONFIG_REFERENCE.md) · [API.md](API.md) ·
[INCIDENT_RESPONSE.md](INCIDENT_RESPONSE.md) · [OPERATIONS.md](OPERATIONS.md)

---

## 1. Prasyarat

| Komponen | Versi minimum | Catatan |
|---|---|---|
| Docker Engine | 24+ | Docker Desktop untuk dev Mac |
| Docker Compose | v2 plugin | `docker compose version` |
| `uv` | 0.4+ | `pip install uv` atau `brew install uv` |
| Node.js | 22+ | untuk frontend build |
| Python | 3.12 | dikelola oleh `uv` |
| PostgreSQL | 16 + pgvector | via Docker di dev; managed di prod |
| Redis | 7 | via Docker di dev |
| MinIO / S3 | API-compatible | via Docker di dev; AWS S3/GCS di prod |

---

## 2. Development Lokal (Mac/Linux)

### Setup pertama kali

```bash
git clone https://github.com/holisahmad/ai_asistent.git
cd ai_asistent

# 1. Environment
cp .env.example .env
# Edit .env: set APP_LLM_PROVIDER, APP_OPENAI_API_KEY, dll

# 2. Diagnosa environment
make doctor            # cek Docker, port, .env, konektivitas
make doctor ARGS=--fix # perbaiki otomatis (nyalakan Docker, buat .env, jalankan infra)

# 3. Infra + install
make infra             # Postgres + Redis + MinIO (docker compose up -d --wait)
make install           # uv sync + npm install

# 4. Migrasi DB (WAJIB sebelum API pertama kali)
make migrate

# 5. Jalankan services (tiap terminal terpisah)
make api               # backend :8000
make worker            # RQ worker
make web               # frontend :3000

# 6. Verifikasi
make smoke             # GET /health/live + /health/ready
```

### Perintah harian

```bash
make lint              # ruff check semua package
make typecheck         # mypy + tsc
make test              # pytest + tsc
make eval ARGS=--write # evaluasi kualitas RAG → docs/reports/eval-<stamp>.md
make bench             # benchmark p50/p95
make backup            # backup Postgres + MinIO → ./backups/<timestamp>/
make scan-secrets      # pindai kredensial sebelum push
```

---

## 3. Produksi — Docker Compose

### File yang dipakai

```
docker-compose.yml           # infra: Postgres, Redis, MinIO
docker-compose.prod.yml      # override produksi: API, worker, nginx, certbot
infra/
  docker/
    Dockerfile.api           # multi-stage build backend
    Dockerfile.worker        # multi-stage build worker
  nginx/
    nginx.conf               # reverse proxy + TLS + security headers
  certbot/                   # Let's Encrypt certificates (diisi Certbot)
  systemd/
    ai-backup.service        # backup harian via systemd
    ai-backup.timer
```

### Deploy ke server Linux

```bash
# 1. Clone di server
git clone https://github.com/holisahmad/ai_asistent.git /opt/ai_asistent
cd /opt/ai_asistent

# 2. Buat .env.prod (JANGAN gunakan .env dev!)
cp .env.example .env.prod
# Edit .env.prod: isi semua nilai produksi dari secret manager

# 3. (Pertama kali) Dapatkan sertifikat TLS dengan Certbot
docker run --rm \
  -v $(pwd)/infra/certbot:/etc/letsencrypt \
  -v $(pwd)/infra/certbot/webroot:/var/www/certbot \
  certbot/certbot certonly --webroot \
  -w /var/www/certbot -d yourdomain.com \
  --email admin@yourdomain.com --agree-tos --non-interactive
# Kemudian edit infra/nginx/nginx.conf: uncomment ssl_certificate*,
# hapus baris ssl fallback self-signed

# 4. Build images
docker compose -f docker-compose.yml -f docker-compose.prod.yml build

# 5. Jalankan infra dulu
docker compose -f docker-compose.yml up -d --wait postgres redis minio

# 6. Migrasi DB
docker compose -f docker-compose.yml -f docker-compose.prod.yml run --rm api \
  uv run alembic upgrade head

# 7. Naikan semua services
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --wait

# 8. Verifikasi
curl https://yourdomain.com/health/ready
curl https://yourdomain.com/version
```

### Update / Rilis baru

```bash
cd /opt/ai_asistent
git pull origin main
docker compose -f docker-compose.yml -f docker-compose.prod.yml build
# Migrasi DB jika ada migration baru
docker compose -f docker-compose.yml -f docker-compose.prod.yml run --rm api \
  uv run alembic upgrade head
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --wait
curl https://yourdomain.com/version   # konfirmasi versi baru
```

---

## 4. Variabel Produksi Wajib

> Semua secret dikelola via environment injection atau secret manager (Vault, AWS SSM).
> **Jangan pernah commit `.env.prod` ke repo.**

| Variabel | Catatan |
|---|---|
| `APP_DATABASE_URL` | Managed Postgres + TLS (`sslmode=require`) |
| `APP_REDIS_URL` | Redis dengan password (`redis://:pass@host:6379/0`) |
| `APP_MINIO_*` | Bucket privat; `MINIO_SECRET_KEY` dari secret manager |
| `APP_OPENAI_API_KEY` | Dari secret manager; rotate berkala |
| `APP_METRICS_TOKEN` | Random string 32+ karakter; wajib di produksi |
| `APP_CORS_ORIGINS_CSV` | Hanya domain frontend resmi |
| `POSTGRES_PASSWORD` | Bukan `ai_assistant` — password kuat |
| `APP_LLM_PROVIDER` | `openai` atau `openai_compat`; bukan `local` |
| `APP_EMBEDDING_PROVIDER` | `fastembed` (lokal) atau `openai` (cloud) |
| `APP_ENVIRONMENT` | `production` |

Lihat daftar lengkap: [CONFIG_REFERENCE.md](CONFIG_REFERENCE.md)

---

## 5. Backup & Restore

### Backup manual

```bash
make backup
# → ./backups/<timestamp>/{postgres.dump, minio/, metadata.json}
```

### Backup otomatis (server)

```bash
# Crontab — backup harian 02:00
(crontab -l 2>/dev/null; echo "0 2 * * * cd /opt/ai_asistent && ./scripts/cron_backup.sh >> ./backups/cron.log 2>&1") | crontab -

# Atau systemd timer
sudo cp infra/systemd/ai-backup.{service,timer} /etc/systemd/system/
sudo sed -i 's|/opt/ai_asistent|'$(pwd)'|' /etc/systemd/system/ai-backup.service
sudo systemctl daemon-reload
sudo systemctl enable --now ai-backup.timer
sudo systemctl list-timers ai-backup.timer   # verifikasi jadwal
```

### Verifikasi backup (drill)

```bash
make restore-drill
# Output: RESTORE DRILL: PASS / FAIL
# Jalankan mingguan di lingkungan staging
```

### Restore

```bash
# Restore ke database aktif (HATI-HATI — akan menimpa data!)
make restore DIR=backups/20261003T020000Z

# Restore ke database baru (aman untuk verifikasi)
make restore DIR=backups/20261003T020000Z DB=ai_assistant_restore_test
```

### Retensi backup

- **Lokal**: `BACKUP_RETAIN_DAYS=7` (default) di `scripts/cron_backup.sh`
- **Produksi**: salin backup ke object storage eksternal (S3/GCS) + retensi 30 hari
- **Database managed**: aktifkan PITR (Point-in-Time Recovery) untuk RPO < 1 jam

---

## 6. Embedding & Reindex

Model embedding menentukan kualitas retrieval. Bila `APP_EMBEDDING_PROVIDER` atau
model berubah, **semua chunk harus di-reembed** — vektor lama tidak kompatibel.

```bash
# Cek apakah ada chunk yang perlu reembed
make reembed ARGS=--check    # exit 1 bila ada stale; gunakan di CI/health check

# Re-embed semua chunk
make reembed

# Re-embed workspace tertentu dengan batch size besar
make reembed ARGS='--workspace <WS_ID> --batch 64'
```

---

## 7. CI/CD Pipeline

`.github/workflows/ci.yml` mencakup 6 job paralel:

| Job | Yang dicek |
|---|---|
| `core` | ruff + mypy + pytest (23 source files) |
| `backend` | ruff + mypy + migrate + pytest (dengan Postgres + MinIO) |
| `worker` | ruff + mypy + pytest |
| `frontend` | tsc + next build |
| `security` | scan_secrets.sh (blocking) + pip-audit (non-blocking) |
| `infra` | `docker compose config -q` |

**Quality gate RAG** (di job `backend`): recall@5 ≥ 0.8, MRR ≥ 0.6, citation ≥ 0.8,
no-answer = 1.0, halusinasi = 0.

Rilis: semua job hijau → merge ke `main` → tag `vX.Y.Z` → deploy.

---

## 8. Benchmark & SLO

```bash
# Benchmark lokal (50 iterasi default)
./scripts/benchmark.sh http://localhost:8000 50

# Benchmark produksi
./scripts/benchmark.sh https://yourdomain.com 100
```

SLO baseline (p95):

| Endpoint | SLO |
|---|---|
| `GET /health/live` | ≤ 200 ms |
| `GET /health/ready` | ≤ 200 ms |
| `GET /api/v1/workspaces` | ≤ 2000 ms |
| `POST /api/v1/.../chat/stream` (first token) | ≤ 5000 ms |

---

## 9. Scaling

| Tahap | Pemicu | Langkah |
|---|---|---|
| 1 — pilot | < 50 user | Satu server: API + worker + infra Docker Compose |
| 2 — scale API | CPU API > 70% | API stateless → scale horizontal; load balancer di depan nginx |
| 3 — scale worker | Antrian RQ > 100 job | Tambah worker container; pisah queue ingestion/embedding |
| 4 — DB read berat | query > 500 ms p95 | Read replica Postgres; tune HNSW `ef_search` |
| 5 — vector scale | pgvector tidak cukup | Migrasi ke Qdrant via `VectorStoreProtocol`; reindex penuh |

---

## 10. Checklist Go-Live

Sebelum mengekspos ke pengguna nyata, pastikan semua item ini terpenuhi:

```
Infrastructure
[ ] HTTPS aktif (Certbot atau managed TLS)
[ ] APP_METRICS_TOKEN diset (endpoint /metrics tidak publik)
[ ] APP_MINIO_SECRET_KEY bukan default (bukan "minioadmin")
[ ] POSTGRES_PASSWORD kuat dan bukan default
[ ] Redis password diset (REDIS_PASSWORD)
[ ] APP_CORS_ORIGINS_CSV hanya domain resmi

Aplikasi
[ ] APP_ENVIRONMENT=production
[ ] APP_LLM_PROVIDER bukan "local" (bukan stub)
[ ] make migrate berhasil di database produksi
[ ] make smoke: /health/live + /health/ready hijau
[ ] make eval: semua quality gate PASS
[ ] make scan-secrets: PASS
[ ] make scan-deps: PASS (atau temuan ditinjau)

Operasi
[ ] Backup otomatis terjadwal (crontab atau systemd timer)
[ ] make restore-drill: PASS pada data produksi
[ ] Log tersedia (stdout → log aggregator atau file)
[ ] /metrics terhubung ke Prometheus/Grafana (atau manual pantau)
[ ] Kontak on-call terdaftar di INCIDENT_RESPONSE.md
[ ] Runbook rollback sudah dibaca dan dipahami tim
```
