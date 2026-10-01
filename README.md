# AI Knowledge Assistant

Asisten AI knowledge base perusahaan: grounded-first, source-aware, multi-tenant, dan siap produksi. Panduan lengkap ada di [roadmap.md](roadmap.md).

## Status: Fase 1–5 selesai ✅

- **Fase 1 — Foundation**: struktur project, infra Docker, health checks, CI, tooling kualitas.
- **Fase 2 — Auth & Workspace**: registrasi/login/logout, session token, multi-tenant workspace, RBAC (admin/editor/contributor/viewer), audit trail, migrasi Alembic.
- **Fase 3 — File Upload & Storage**: upload PDF/DOCX/PPTX/XLSX/TXT/MD/CSV/HTML/JSON, validasi ukuran & ekstensi, checksum sha256 dedup, MinIO + signed URL, status queued/processing/indexed/failed, cancel/delete/reindex.
- **Fase 4 — Ingestion & Parsing**: parser per format (PDF halaman, DOCX heading/tabel, PPTX slide, XLSX sheet, TXT/MD char, CSV blok baris) di worker RQ; locator page/slide/sheet/row/char sebagai dasar sitasi; job idempotent via Redis.
- **Fase 5 — Chunking & Indexing**: chunk token-aware (512 tok, overlap 64) yang mempertahankan locator, embedding adapter (local hash / OpenAI), vector store **pgvector** (cosine, IVFFlat), pipeline worker end-to-end → status `indexed`.

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

Cek cepat: buka http://localhost:3000 (landing) dan http://localhost:3000/status (panel status yang memanggil `/health/live` & `/health/ready`).

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
│       ├── models.py     # semua model SQLAlchemy + pgvector Vector
│       ├── db.py         # engine/session/redis (lazy) + koneksi RQ biner
│       ├── storage.py    # adapter MinIO (StorageProtocol)
│       ├── parsers.py    # PDF/DOCX/PPTX/XLSX/TXT/MD/CSV → Section+locator
│       ├── chunking.py   # chunk token-aware + overlap
│       ├── embeddings.py # adapter local hash / OpenAI
│       └── vecstore.py   # adapter pgvector (VectorStoreProtocol)
├── backend/          # FastAPI: app/, migrations/, tests/
│   ├── app/
│   │   ├── api/routes/   # health, auth, workspaces, files
│   │   ├── deps.py           # current user, RBAC require_role, audit
│   │   ├── queue.py          # enqueue RQ (graceful bila Redis down)
│   │   ├── security.py       # bcrypt + token opaque
│   │   ├── audit.py          # JSONL audit sink
│   │   ├── schemas.py        # Pydantic request/response
│   │   └── main.py           # app factory
│   └── migrations/       # Alembic 0001-0003 (pgvector, documents, chunks)
├── worker/           # RQ worker (src layout)
│   └── src/worker/
│       ├── pipeline.py   # ingest_file: get→parse→chunk→embed→index (idempotent)
│       ├── jobs.py       # registry job (whitelist)
│       └── main.py       # entrypoint `make worker`
├── frontend/         # Next.js App Router: app/, lib/
├── docs/             # catatan arsitektur & keputusan
├── docker-compose.yml    # pgvector + Redis + MinIO + healthchecks
├── .env.example          # template config, tanpa secret
└── roadmap.md            # panduan eksekusi 10 fase
```

Backend & worker berbagi package `core` via **uv workspace** — model dan pipeline tidak diduplikasi, worker tetap bisa di-deploy terpisah.

## API — Fase 2 (auth & workspace)

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

## Prinsip yang dipegang (dari roadmap.md)

- **Grounded-first** — jawaban hanya dari konteks lolos threshold; tanpa bukti → "informasi belum tersedia".
- **Async by design** — parsing/OCR/transkripsi/embedding/indexing sebagai job worker idempotent.
- **Secure by default** — isolasi workspace/tenant + ACL sebelum konteks masuk ke LLM (Fase 2 & 6).
- **Adapter untuk vendor** — LLM (OpenAI/Anthropic/Gemini/lokal) dan vector store (pgvector → Qdrant) selalu di balik interface.

## Environment

Salin `.env.example` → `.env`. Prefix variabel aplikasi: `APP_` (mis. `APP_DATABASE_URL`). Jangan pernah commit `.env` — sudah dicegah oleh [.gitignore](.gitignore).

## Langkah berikutnya

Fase 6 (Retrieval & RAG: hybrid search, reranking, chat grounded dengan sitasi) → dst. Lihat [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) untuk alur end-to-end dan keputusan tiap fase.
