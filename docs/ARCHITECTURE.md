# Arsitektur — AI Knowledge Assistant

Ringkasan alur end-to-end (detail lengkap: [../roadmap.md](../roadmap.md) bagian "Arsitektur Alur").

## Alur data

```
Upload/URL → API (validasi size/MIME/checksum/izin)
           → Object storage (MinIO) + metadata (PostgreSQL)
           → Queue (Redis/RQ) → Worker
               ├─ ekstraksi teks (PDF/DOCX/PPTX/XLSX/TXT/MD/HTML/CSV)
               ├─ OCR (gambar) / transkripsi (audio/video) via provider adapter
               ├─ chunking token-aware + metadata (page/slide/timecode)
               └─ embedding → pgvector
Pertanyaan → hybrid retrieval (dense + keyword) + ACL filter → reranking
           → LLM (adapter) menjawab HANYA dari konteks lolos threshold
           → jawaban + sitasi + uncertainty; no-answer bila bukti kurang
           → web fallback opsional (mode dikontrol, sumber ditandai eksternal)
```

## Keputusan Fase 3 (File Upload & Storage)

| Keputusan | Alasan |
| --- | --- |
| Storage adapter (`StorageProtocol`) di `app/storage.py` | Roadmap: vendor dapat diganti; MinIO hari ini, S3/Qdrant-side storage lain tanpa menyentuh pemanggil. |
| Validasi berbasis ekstensi allowlist (bukan MIME client) | MIME dari client mudah dipalsukan; ekstensi + magic-byte check penuh menyusul di Fase 4 saat parser menerima file. |
| Dedup via checksum sha256 per workspace | Hemat storage & index; file identik antar-workspace tetap diizinkan (isolasi tenant). |
| Object key hierarkis `workspaces/{ws}/files/{id}/v{n}/{filename}` | ACL per workspace mudah diterapkan level bucket; versioning eksplisit untuk reindex. |
| Upload gagal storage → rollback DB | Tidak ada metadata yatim; object storage ditulis sebelum commit DB. |
| Download via 307 ke presigned URL (15 menit) | API tidak memproksi byte file; TTL dari `APP_PRESIGN_EXPIRY_SECONDS`. |
| Soft delete (`is_deleted` + status `deleted`) | Roadmap minta cancel/delete/retry/reindex; purge fisik & cleanup object menyusul di Fase 9. |
| `_read_bounded` membaca max+1 byte | Upload > limit ditolak tanpa memuat seluruh isi ke memori. |

## Keputusan Fase 2 (Auth & Workspace)

| Keputusan | Alasan |
| --- | --- |
| Session token opaque (random 32B) + SHA-256 hash di DB | Tidak perlu JWT/signing key di MVP; revocation mudah (kolom `revoked_at`); token mentah tidak pernah disimpan. |
| bcrypt untuk password | Standar matang, salt otomatis; argon2 bisa menyusul via adapter bila diperlukan. |
| RBAC 4 role dengan hirarki viewer<contributor<editor<admin | Sesuai roadmap; `require_role(min)` memeriksa level, bukan equality, sehingga editor boleh apa pun yang boleh dilakukan viewer. |
| Bukan anggota → 404, bukan 403 | Anti enumeration: keberadaan workspace tenant lain tidak dibocorkan. Test isolasi mengunci perilaku ini. |
| Audit double-write: tabel `audit_events` + file JSONL | DB untuk query aplikasi; JSONL untuk operasi (tail/grep) tanpa akses DB. Dikontrol `APP_AUDIT_LOG_FILE`. |
| Monorepo tetap, backend bisa dipecah saat scale | Model & deps sudah modular (`db.py`, `deps.py`, `models.py`); pemisahan service jadi keputusan deployment, bukan refactor kode. |
| `pytest-env` mengarahkan test ke DB `_test` | Isolasi penuh data dev vs test; CI menjalankan `alembic upgrade head` sebelum pytest. |

## Keputusan Fase 1

| Keputusan | Alasan |
| --- | --- |
| Monorepo `backend/ worker/ frontend/` | Eksekusi per fase mudah; worker terpisah agar bisa di-scale independent. |
| `uv` untuk Python (backend & worker) | Cepat, lockfile deterministik, tanpa virtualenv manual; Python 3.12 dikelola uv (Python sistem Mac = 3.9, terlalu tua). |
| Postgres host port **5433**, Redis **6380** | 5432/6379 sudah terpakai layanan lain di Mac pengguna; mapping hanya di host, di dalam jaringan compose tetap standar. |
| Health ready = per-check status, selalu respons JSON | Memudahkan debug infra dan tetap aman untuk orchestrator (503 saat tidak siap). |
| Dependensi DB/Redis lazy (dibuat saat pertama dipakai) | Test & import app tidak butuh infra berjalan; smoke test bisa jalan bertahap. |
| Structured JSON logging sejak awal | Syarat observability roadmap; murah dilakukan sejak Fase 1, mahal jika ditambah belakangan. |
| Worker = RQ (bukan Celery) | MVP-first sesuai roadmap; naik ke Celery/Temporal bila workflow meningkat. |
| Settings via pydantic-settings, prefix `APP_`, env root | Satu sumber konfigurasi untuk backend+worker, tanpa secret di-commit. |

## Kontrak yang sudah terkunci (API minimum)

`GET /health/live`, `GET /health/ready` — sudah ada. Sisanya (`/api/v1/auth/...`, `/api/v1/files`, `/api/v1/chat/stream`, dst.) dibangun per fase sesuai daftar API minimum di roadmap.

## Model data (rencana Fase 2-5)

users, workspaces, memberships, roles, files, file_versions, documents, document_chunks, ingestion_jobs, chats, messages, citations, web_search_logs, audit_events — lihat daftar di roadmap.
