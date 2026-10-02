# Deployment, Operasi & Incident Response — AI Knowledge Assistant

Dokumen ini melengkapi [../roadmap.md](../roadmap.md) (Fase 10: Pilot & Scale) dan
[ARCHITECTURE.md](ARCHITECTURE.md). Tujuannya: deployment dapat **diulang dari
dokumentasi ini** tanpa pengetahuan tacit, dan insiden bisa ditangani/rollback
dengan prosedur yang jelas.

## 1. Prasyarat

- Docker + Docker Compose v2 (dev) atau cluster Kubernetes / managed services (produksi).
- `uv` (Python) dan Node.js 22+ (frontend).
- Akun object storage S3-compatible (MinIO/S3), PostgreSQL 16 + ekstensi `pgvector`, Redis 7.
- Kunci API LLM (opsional; bisa memakai gateway OpenAI-compatible / model lokal).

## 2. Konfigurasi

Semua variabel aplikasi berprefix `APP_` (lihat [.env.example](../.env.example)).
Yang **wajib** ditinjau untuk produksi:

| Variabel | Catatan produksi |
| --- | --- |
| `APP_DATABASE_URL` | Managed Postgres + TLS; jangan pakai kredensial dev. |
| `APP_REDIS_URL` | Redis dengan autentikasi/TLS; jangan expose ke publik. |
| `APP_MINIO_*` | Bucket privat; kredensial dari secret manager. |
| `APP_CORS_ORIGINS_CSV` | Hanya origin frontend resmi. |
| `APP_LLM_PROVIDER` / `APP_OPENAI_*` | `openai` atau `openai_compat`; API key dari secret manager. |
| `APP_EMBEDDING_PROVIDER` | Disarankan `openai` di produksi (semantik penuh; lokal hanya BoW). |
| `APP_WEB_FALLBACK_MODE` | `internal_only` bila web tidak diizinkan. |
| `APP_METRICS_TOKEN` | Set agar `/metrics` tidak publik. |
| `APP_API_RATE_LIMIT_PER_MIN` | Sesuaikan kuota per token/tim. |

Jangan pernah commit `.env` — sudah dicegah `.gitignore` dan diperiksa `make scan-secrets`.

## 3. Deployment (Docker Compose — baseline)

```bash
cp .env.example .env            # sesuaikan nilai produksi
make infra                      # Postgres + Redis + MinIO
make install                    # uv sync + npm ci
make migrate                    # alembic upgrade head (wajib sebelum API serve)
make api                        # uvicorn (ganti ke gunicorn/uvicorn workers, lihat §7)
make worker                     # RQ worker
make web                        # next build && next start (bukan dev)
```

Urutan penting: **migrasi dulu**, baru API/worker. API boleh naik lebih dulu daripada
worker (upload tetap masuk queue), tetapi chat butuh worker agar dokumen ter-index.

### Health & readiness

- `GET /health/live` — proses hidup.
- `GET /health/ready` — DB/Redis/storage; kembar 503 bila belum siap → jadikan probe liveness/readiness orchestrator.
- `GET /version` — nama & versi aplikasi (untuk verifikasi rilis).
- `GET /metrics` — metrik Prometheus (kunci dengan `APP_METRICS_TOKEN`).

## 4. CI/CD

`.github/workflows/ci.yml` menjalankan: lint+typecheck+test `core`/`backend`/`worker`,
build frontend, validasi compose, dan job **security** (secret scan blocking +
dependency audit non-blocking). Job backend memakai service `pgvector` + `MinIO`,
menjalankan `alembic upgrade head`, lalu pytest — termasuk **quality gate Fase 10**
(`backend/tests/test_retrieval_eval.py`): recall@5 ≥ 0.8, MRR ≥ 0.6, sitasi ≥ 0.8,
no-answer = 1.0, halusinasi = 0, false-no-answer ≤ 0.2.

Rilis: merge ke `main` hanya bila CI hijau. Tag rilis (`vX.Y.Z`) menandai image yang
di-deploy; catat commit SHA di changelog.

## 5. Backup & Restore

```bash
make backup          # ./backups/<timestamp>/ {postgres.dump, minio/, metadata.json}
make restore-drill   # backup → restore ke DB scratch → bandingkan → PASS/FAIL
make restore DIR=backups/<timestamp> [DB=nama_database]
```

- Backup memakai `pg_dump -Fc` + salinan data MinIO, disertai checksum sha256 dan
  jumlah tabel di `metadata.json`.
- **Restore drill wajib dijalankan berkala** (mis. mingguan) di lingkungan non-produksi;
  drill membandingkan jumlah baris tabel inti (users, workspaces, files, documents,
  document_chunks, chats, messages, citations, audit_events) antara sumber & hasil restore.
- RPO/RTO: backup harian → RPO ≤ 24 jam; restore drill terukur (detik–menit pada dataset dev).
  Untuk produksi, tambahkan WAL archiving / PITR dari penyedia managed Postgres.

## 6. Incident Response

**Deteksi** — sumber sinyal:
- `GET /metrics`: rate-limit 429, histogram latensi retrieval/chat, status breaker.
- Log JSON terstruktur (`request_id`, `action` audit) — grep `X-Request-ID` untuk menautkan satu request.
- `/health/ready` 503 → ketergantungan infra bermasalah.

**Triase** (skenario umum):

| Gejala | Kemungkinan penyebab | Tindakan |
| --- | --- | --- |
| Setup lokal tidak jalan (infra/env) | Docker mati, port terpakai, `.env` hilang/salah, layanan belum siap | Jalankan `make doctor` — mencetak item merah + langkah perbaikan. Untuk perbaikan otomatis (nyalakan Docker, `docker compose up -d --wait`, salin `.env`): `make doctor ARGS=--fix`. |
| `/health/ready` 503 | DB/Redis/MinIO turun | Cek container/instance; pulihkan ketergantungan; API tetap liveness OK. |
| Chat lambat / timeout | Provider LLM lambat / breaker terbuka | Cek metrik breaker & error log; kurangi `APP_RETRIEVAL_TOP_K`; fallback provider. |
| 429 massal | Rate limit terlalu ketat / klien loop | Naikkan `APP_API_RATE_LIMIT_PER_MIN` atau perbaiki klien; cek `Retry-After`. |
| Web fallback error | Provider web menolak/diblokir (403, captcha, atau DNS internet positif mengarahkan ke IP blokir) | Ganti `APP_WEB_SEARCH_PROVIDER` (rekomendasi `bing_rss` — feed RSS resmi tanpa key); degrade otomatis ke no-answer (bukan 5xx). |
| Jawaban tidak grounded | Dokumen belum ter-index / embedding lama | Cek status `indexed`; jalankan reindex (embedding berubah antarversi). |
| Runtime Error `Cannot find module './NNN.js'` di :3000 | Artefak `.next` campur aduk — `next build` dijalankan saat `next dev` masih aktif (atau build terpotong) | Hentikan `make web`, jalankan `make clean`, start ulang. Jangan jalankan `npm run build` bersamaan dengan dev server. |

**Eskalasi**: incident commander mencatat timeline, dampak, dan keputusan. Setiap
insiden kritis → postmortem maksimal 3 hari kerja.

## 7. Rollback

1. **Aplikasi**: deploy image/tag rilis sebelumnya; proses stateless → rollback cepat.
2. **Skema DB**: migrasi Alembic bersifat *upgrade*; hindari downgrade destruktif.
   Bila perlu, pulihkan dari backup (§5) ke DB baru lalu arahkan `APP_DATABASE_URL`.
3. **Index**: bila kualitas retrieval turun setelah perubahan embedding/model,
   jalankan reindex (`POST /files/{id}/reindex`) sebelum menilai regresi.
4. **Verifikasi pasca-rollback**: `/health/ready`, `/version`, satu pertanyaan smoke
   dari dataset evaluasi, dan cek metrik 5xx/429.

## 8. Scaling

| Tahap | Pemicu | Langkah |
| --- | --- | --- |
| 1 (sekarang) | pilot kecil | API + worker satu host; pgvector; MinIO/Redis satu instance. |
| 2 | CPU/latensi API naik | Pisah service: API di-scale horizontal (stateless), worker di-scale via beberapa proses/queue. |
| 3 | ingest backlog | Tambah worker khusus ingestion; pisahkan scheduler/cron (cleanup, reindex massal) ke proses sendiri. |
| 4 | DB baca berat | Read replica untuk daftar/riwayat; indeks tambahan bila perlu; tune HNSW/IVFFlat. |
| 5 | pgvector tak memadai | Migrasi ke Qdrant via `VectorStoreProtocol` (tanpa ubah pemanggil); reindex penuh. |

Praktik: batasi `APP_RETRIEVAL_TOP_K`/`CANDIDATES` untuk menahan biaya token;
pantau histogram latensi & biaya token dari `scripts/bench.py` dan laporan eval.

## 8b. Pemeliharaan Embedding

Skor dense retrieval hanya konsisten bila vektor chunk dan vektor query dihitung
oleh kode/provider yang sama. Saat `APP_EMBEDDING_PROVIDER` atau dimensi berubah,
jalankan:

```bash
make reembed ARGS=--check   # non-destruktif: laporkan cosine lama-vs-baru (exit 1 bila ada stale)
make reembed                # hitung ulang embedding semua chunk dari content
make reembed ARGS='--workspace <WS_ID> --batch 64'
```

Skrip membaca langsung `document_chunks.content` (tidak mem-parse ulang file),
sehingga aman dijalankan tanpa object storage. Jadwalkan `--check` pada proses
operasi berkala; bila melaporkan stale > 0, jalankan `make reembed` sebelum menilai
kualitas retrieval.

## 9. Evaluasi Berkala (Pilot)

```bash
make eval ARGS=--write        # laporan docs/reports/eval-<stamp>.md (LLM stub)
make eval ARGS='--llm gateway --write'   # dengan LLM/gateway sebenarnya
make bench ARGS='--iterations 50'
```

Tindak lanjuti laporan: perbaiki chunking (ukuran/overlap), reranker, prompt, atau
pilihan model berdasarkan metrik correctness/recall/sitasi/latensi/biaya. Versikan
dataset ([docs/eval/retrieval_dataset.json](eval/retrieval_dataset.json)) saat menambah kueri.
```
