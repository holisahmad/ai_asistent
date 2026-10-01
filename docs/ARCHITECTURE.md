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
