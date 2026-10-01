# AI Knowledge Assistant

Asisten AI knowledge base perusahaan: grounded-first, source-aware, multi-tenant, dan siap produksi. Panduan lengkap ada di [roadmap.md](roadmap.md).

## Status: Fase 1–8 selesai ✅

- **Fase 1 — Foundation**: struktur project, infra Docker, health checks, CI, tooling kualitas.
- **Fase 2 — Auth & Workspace**: registrasi/login/logout, session token, multi-tenant workspace, RBAC (admin/editor/contributor/viewer), audit trail, migrasi Alembic.
- **Fase 3 — File Upload & Storage**: upload PDF/DOCX/PPTX/XLSX/TXT/MD/CSV/HTML/JSON, validasi ukuran & ekstensi, checksum sha256 dedup, MinIO + signed URL, status queued/processing/indexed/failed, cancel/delete/reindex.
- **Fase 4 — Ingestion & Parsing**: parser per format (PDF halaman, DOCX heading/tabel, PPTX slide, XLSX sheet, TXT/MD char, CSV blok baris) di worker RQ; locator page/slide/sheet/row/char sebagai dasar sitasi; job idempotent via Redis.
- **Fase 5 — Chunking & Indexing**: chunk token-aware (512 tok, overlap 64) yang mempertahankan locator, embedding adapter (local hash / OpenAI), vector store **pgvector** (cosine, IVFFlat), pipeline worker end-to-end → status `indexed`.
- **Fase 6 — Retrieval & RAG**: hybrid retrieval (dense pgvector + keyword FTS Postgres) dengan fusi skor deterministik (RRF + cosine) dan threshold; ACL workspace difilter di SQL sebelum konteks ke LLM; LLM adapter (local stub / OpenAI / **openai_compat**) dengan prompt grounded; jawaban streaming SSE token-level dengan citation objects klikabel; no-answer "informasi belum tersedia"; chats/messages/citations tersimpan.
- **Fase 7 — Web Fallback**: mode `internal_only` / `internal_plus_web` (default aman), web search hanya bila bukti internal tak cukup **dan** klien mengirim `allow_web=true`; provider adapter (DuckDuckGo tanpa key / SearXNG / Tavily); allowlist & denylist domain (deny menang), rate limit, timeout, sanitasi konten; sitasi web selalu `source_type=web` + URL (tidak pernah dicampur dengan sitasi internal); setiap percobaan tercatat di `web_search_logs`.
- **Fase 8 — UI/UX**: login/register, dashboard workspace multi-tenant, chat streaming SSE dengan badge grounded/no-answer/web, **drawer sumber** (snippet, locator, unduh file, buka sumber web), upload drag-and-drop dengan progress & error recovery, pustaka dokumen (status, reindex, hapus, unduh), RBAC pada tombol aksi, empty/loading/error state, CORS untuk frontend.

| Komponen | Teknologi | Port dev |
| --- | --- | --- |
| Frontend | Next.js 15 + React 19 + Tailwind v4 | 3000 |
| Backend API | FastAPI + SQLAlchemy + Pydantic v2 | 8000 |
| Worker | Redis + RQ (queue `default`) + pipeline parser/chunk/embed | — |
| Database | PostgreSQL 16 + pgvector (image `pgvector/pgvector:pg16`) | **5433** (host) |
| Queue/Cache | Redis 7 | **6380** (host) |
| Object storage | MinIO (S3-compatible) | 9000 / konsol 9001 |

> Port 5432 & 6379 dihosting Mac ini sudah terpakai layanan lain, sehingga dipetakan ke 5433/6380.

## Menjalankan project (satu instruksi)

```bash
cp .env.example .env          # 1x saja, sesuaikan bila perlu
make infra                    # Postgres + Redis + MinIO (docker compose up -d --wait)
make install                  # uv sync (backend & worker) + npm install (frontend)

make api                      # terminal 1: backend di http://localhost:8000
make worker                   # terminal 2: RQ worker
make web                      # terminal 3: frontend di http://localhost:3000
```

Cek cepat: buka http://localhost:3000 (landing) → **Masuk/Daftar** di http://localhost:3000/login → dashboard di http://localhost:3000/app (chat + dokumen). Panel status: http://localhost:3000/status.

## Quality gates

```bash
make migrate     # jalankan migrasi Alembic ke DB development
make test-db     # (sekali) buat + migrasi database test
make lint        # ruff (backend & worker)
make typecheck   # mypy --strict (backend & worker) + tsc (frontend)
make test        # pytest (backend & worker)
make smoke       # curl /health/live & /health/ready (api harus berjalan)
```

CI (GitHub Actions) menjalankan hal yang sama di setiap push/PR — lihat [.github/workflows/ci.yml](.github/workflows/ci.yml).

## Struktur

```
ai_asistent/
├── core/             # Package bersama (uv workspace): ai_asistent_core
│   └── src/ai_asistent_core/
│       ├── config.py     # settings inti (env APP_*, satu sumber)
│       ├── models.py     # semua model SQLAlchemy + pgvector Vector + chats/messages/citations
│       ├── db.py         # engine/session/redis (lazy) + koneksi RQ biner
│       ├── storage.py    # adapter MinIO (StorageProtocol)
│       ├── parsers.py    # PDF/DOCX/PPTX/XLSX/TXT/MD/CSV → Section+locator
│       ├── chunking.py   # chunk token-aware + overlap
│       ├── embeddings.py # adapter local (bag-of-words hash) / OpenAI
│       ├── vecstore.py   # adapter pgvector (VectorStoreProtocol)
│       ├── retrieval.py  # hybrid: dense + keyword FTS + fusi RRF (ACL di SQL)
│       ├── llm.py        # adapter LLM: local stub / OpenAI SDK / openai_compat
│       ├── rag.py        # orkestrasi: retrieve → LLM → sitasi/no-answer/web fallback
│       ├── websearch.py  # Fase 7: DDG/SearXNG/Tavily + ACL domain + rate limit
│       └── models.py     # chats, messages, citations, web_search_logs
├── backend/          # FastAPI: app/, migrations/, tests/
│   ├── app/
│   │   ├── api/routes/   # health, auth, workspaces, files, chat
│   │   ├── deps.py           # current user, RBAC require_role, audit
│   │   ├── queue.py          # enqueue RQ (graceful bila Redis down)
│   │   ├── security.py       # bcrypt + token opaque
│   │   ├── audit.py          # JSONL audit sink
│   │   ├── schemas.py        # Pydantic request/response
│   │   └── main.py           # app factory
│   └── migrations/       # Alembic 0001-0005 (pgvector, chats, sitasi web)
├── worker/           # RQ worker (src layout)
│   └── src/worker/
│       ├── jobs.py       # registry job → core.pipeline.ingest_file (idempotent)
│       └── main.py       # entrypoint `make worker`
├── frontend/         # Next.js App Router: app/ (landing, /login, /app, /status), lib/api.ts (SSE)
├── docs/             # catatan arsitektur & keputusan
├── docker-compose.yml    # pgvector + Redis + MinIO + healthchecks
├── .env.example          # template config, tanpa secret
└── roadmap.md            # panduan eksekusi 10 fase
```

Backend & worker berbagi package `core` via **uv workspace** — model dan pipeline tidak diduplikasi, worker tetap bisa di-deploy terpisah.

## API (Fase 2–6: auth, workspace, files, chat)

| Method | Path | Akses |
|---|---|---|
| POST | `/api/v1/auth/register` | publik → token |
| POST | `/api/v1/auth/login` | publik → token |
| POST | `/api/v1/auth/logout` | bearer (revoke semua session) |
| GET | `/api/v1/auth/me` | bearer |
| POST | `/api/v1/workspaces` | bearer (pembuat jadi admin) |
| GET | `/api/v1/workspaces` | bearer (hanya miliknya) |
| GET | `/api/v1/workspaces/{id}` | viewer+ |
| PATCH | `/api/v1/workspaces/{id}` | admin |
| POST | `/api/v1/workspaces/{id}/members` | admin |
| DELETE | `/api/v1/workspaces/{id}/members/{user_id}` | admin |
| POST | `/api/v1/workspaces/{id}/files` | contributor+ (multipart, dedup 409) |
| GET | `/api/v1/workspaces/{id}/files` | viewer+ (`?status=` filter) |
| GET | `/api/v1/workspaces/{id}/files/{file_id}` | viewer+ |
| GET | `/api/v1/workspaces/{id}/files/{file_id}/download` | viewer+ → 307 presigned URL |
| POST | `/api/v1/workspaces/{id}/files/{file_id}/cancel` | contributor+ (queued saja) |
| DELETE | `/api/v1/workspaces/{id}/files/{file_id}` | editor+ (soft delete) |
| POST | `/api/v1/workspaces/{id}/files/{file_id}/reindex` | contributor+ |
| POST | `/api/v1/workspaces/{id}/chat/stream` | viewer+ (SSE: meta/delta/done; `allow_web` untuk fallback web) |
| GET | `/api/v1/workspaces/{id}/chats` | viewer+ (daftar chat) |
| GET | `/api/v1/workspaces/{id}/chats/{chat_id}` | viewer+ (pesan + sitasi) |

## Prinsip yang dipegang (dari roadmap.md)

- **Grounded-first** — jawaban hanya dari konteks lolos threshold; tanpa bukti → "informasi belum tersedia".
- **Async by design** — parsing/OCR/transkripsi/embedding/indexing sebagai job worker idempotent.
- **Secure by default** — isolasi workspace/tenant + ACL sebelum konteks masuk ke LLM (Fase 2 & 6).
- **Adapter untuk vendor** — LLM (OpenAI/Anthropic/Gemini/lokal) dan vector store (pgvector → Qdrant) selalu di balik interface.

## Environment

Salin `.env.example` → `.env`. Prefix variabel aplikasi: `APP_` (mis. `APP_DATABASE_URL`). Jangan pernah commit `.env` — sudah dicegah oleh [.gitignore](.gitignore).

## Langkah berikutnya

Fase 9 (Production hardening: rate limit API, retry/backoff, metrics/tracing, backup & restore drill, secret/dependency scan, benchmark p50/p95) → dst. Lihat [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) untuk alur end-to-end dan keputusan tiap fase.
