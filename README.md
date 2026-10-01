# AI Knowledge Assistant

Asisten AI knowledge base perusahaan: grounded-first, source-aware, multi-tenant, dan siap produksi. Panduan lengkap ada di [roadmap.md](roadmap.md).

## Status: Fase 1–10 selesai ✅

- **Fase 1 — Foundation**: struktur project, infra Docker, health checks, CI, tooling kualitas.
- **Fase 2 — Auth & Workspace**: registrasi/login/logout, session token, multi-tenant workspace, RBAC (admin/editor/contributor/viewer), audit trail, migrasi Alembic.
- **Fase 3 — File Upload & Storage**: upload PDF/DOCX/PPTX/XLSX/TXT/MD/CSV/HTML/JSON, validasi ukuran & ekstensi, checksum sha256 dedup, MinIO + signed URL, status queued/processing/indexed/failed, cancel/delete/reindex.
- **Fase 4 — Ingestion & Parsing**: parser per format (PDF halaman, DOCX heading/tabel, PPTX slide, XLSX sheet, TXT/MD char, CSV blok baris) di worker RQ; locator page/slide/sheet/row/char sebagai dasar sitasi; job idempotent via Redis.
- **Fase 5 — Chunking & Indexing**: chunk token-aware (512 tok, overlap 64) yang mempertahankan locator, embedding adapter (local hash / OpenAI), vector store **pgvector** (cosine, IVFFlat), pipeline worker end-to-end → status `indexed`.
- **Fase 6 — Retrieval & RAG**: hybrid retrieval (dense pgvector + keyword FTS Postgres) dengan fusi skor deterministik (RRF + cosine) dan threshold; ACL workspace difilter di SQL sebelum konteks ke LLM; LLM adapter (local stub / OpenAI / **openai_compat**) dengan prompt grounded; jawaban streaming SSE token-level dengan citation objects klikabel; no-answer "informasi belum tersedia"; chats/messages/citations tersimpan.
- **Fase 7 — Web Fallback**: mode `internal_only` / `internal_plus_web` (default aman), web search hanya bila bukti internal tak cukup **dan** klien mengirim `allow_web=true`; provider adapter (DuckDuckGo tanpa key / SearXNG / Tavily); allowlist & denylist domain (deny menang), rate limit, timeout, sanitasi konten; sitasi web selalu `source_type=web` + URL (tidak pernah dicampur dengan sitasi internal); setiap percobaan tercatat di `web_search_logs`.
- **Fase 8 — UI/UX**: login/register, dashboard workspace multi-tenant, chat streaming SSE dengan badge grounded/no-answer/web, **drawer sumber** (snippet, locator, unduh file, buka sumber web), render markdown + sitasi `[n]` klikabel, copy jawaban, feedback 👍/👎, tombol **coba lagi**, upload drag-and-drop dengan progress & error recovery, pustaka dokumen (cari nama, filter status, reindex, hapus, unduh), RBAC pada tombol aksi, empty/loading/error state, CORS untuk frontend.
- **Fase 9 — Production Hardening**: retry/backoff eksponensial + **circuit breaker** untuk LLM & web search (`core/resilience.py`); **idempotency key** pada upload; **rate limit API** per token (429 + `Retry-After`); correlation ID (`X-Request-ID`) di log & respons; log JSON terstruktur; **metrik Prometheus** (`GET /metrics`) + `GET /version`; mitigasi **prompt-injection** (konteks diperlakukan sebagai data, kalimat injeksi ditandai); pemindaian malware upload (EICAR/signature executable/NUL); skrip **backup/restore/restore-drill** (Postgres + MinIO) yang terbukti PASS; **secret scan** & **dependency scan** (pip-audit + npm audit); benchmark p50/p95/p99.
- **Fase 10 — Pilot & Scale**: dataset evaluasi retrieval/answer ([docs/eval/retrieval_dataset.json](docs/eval/retrieval_dataset.json)) dengan metrik recall@k, MRR, citation correctness, no-answer accuracy, hallucination rate, false-no-answer rate; **quality gate** otomatis di CI ([backend/tests/test_retrieval_eval.py](backend/tests/test_retrieval_eval.py)); skrip evaluasi & benchmark yang menghasilkan laporan markdown ([docs/reports/](docs/reports)); dokumentasi deployment, operasi, incident response, rollback, dan jalur scaling (API/worker/scheduler terpisah, migrasi Qdrant).

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
make migrate       # jalankan migrasi Alembic ke DB development
make test-db       # (sekali) buat + migrasi database test
make lint          # ruff (core, backend & worker)
make typecheck     # mypy --strict (core, backend & worker) + tsc (frontend)
make test          # pytest (core, backend & worker) + tsc (frontend)
make smoke         # curl /health/live & /health/ready (api harus berjalan)
make scan-secrets  # pindai pola kredensial pada file tracked git
make scan-deps     # audit dependensi (pip-audit + npm audit)
make backup        # backup Postgres + MinIO ke ./backups/<timestamp>
make restore-drill # backup → restore ke DB scratch → bandingkan → PASS/FAIL
make eval ARGS=--write  # evaluasi kualitas RAG → docs/reports/eval-<stamp>.md
make bench ARGS='--iterations 50'  # benchmark p50/p95/p99 retrieval & chat
make reembed ARGS=--check  # deteksi embedding chunk yang stale vs kode terbaru
```

> **Penting:** bila algoritma/provider embedding berubah (`APP_EMBEDDING_PROVIDER`/dim), vektor chunk lama menjadi tidak konsisten. Jalankan `make reembed ARGS=--check` untuk memeriksa, lalu `make reembed` untuk menghitung ulang. Alternatif per-file: `POST /files/{id}/reindex`.

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
│       ├── resilience.py # Fase 9: retry/backoff + circuit breaker
│       ├── guards.py     # Fase 9: pemindaian malware upload (EICAR/MZ/ELF/NUL)
│       ├── injection.py  # Fase 9: deteksi & mitigasi prompt-injection
│       └── eval.py       # Fase 10: metrik recall@k, MRR, sitasi, no-answer, biaya
├── backend/          # FastAPI: app/, migrations/, tests/
│   ├── app/
│   │   ├── api/routes/   # health, auth, workspaces, files, chat, ops (/metrics, /version)
│   │   ├── deps.py           # current user, RBAC require_role, audit
│   │   ├── queue.py          # enqueue RQ (graceful bila Redis down)
│   │   ├── security.py       # bcrypt + token opaque
│   │   ├── audit.py          # JSONL audit sink
│   │   ├── context.py        # Fase 9: correlation ID (contextvar)
│   │   ├── idempotency.py    # Fase 9: Idempotency-Key untuk upload
│   │   ├── observability.py  # Fase 9: metrik Prometheus + rate limit + middleware
│   │   ├── schemas.py        # Pydantic request/response
│   │   └── main.py           # app factory
│   └── migrations/       # Alembic 0001-0006 (pgvector, chats, web, idempotency/feedback)
├── worker/           # RQ worker (src layout)
│   └── src/worker/
│       ├── jobs.py       # registry job → core.pipeline.ingest_file (idempotent)
│       └── main.py       # entrypoint `make worker`
├── frontend/         # Next.js App Router: app/ (landing, /login, /app, /status), lib/api.ts (SSE)
├── scripts/          # Fase 9/10: backup/restore/drill, scan_secrets, scan_deps, eval_rag, bench, reembed
├── docs/             # catatan arsitektur & keputusan
│   ├── ARCHITECTURE.md       # alur end-to-end + keputusan tiap fase
│   ├── DEPLOYMENT.md         # Fase 10: deployment, operasi, incident, rollback, scaling
│   ├── eval/                 # dataset evaluasi retrieval/answer
│   └── reports/              # laporan eval & benchmark (gitignored)
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
| POST | `/api/v1/workspaces/{id}/chats/{chat_id}/messages/{message_id}/feedback` | viewer+ (👍/👎) |
| GET | `/metrics` | publik / Bearer `APP_METRICS_TOKEN` bila diset (Prometheus) |
| GET | `/version` | publik (nama & versi aplikasi) |

## Prinsip yang dipegang (dari roadmap.md)

- **Grounded-first** — jawaban hanya dari konteks lolos threshold; tanpa bukti → "informasi belum tersedia".
- **Async by design** — parsing/OCR/transkripsi/embedding/indexing sebagai job worker idempotent.
- **Secure by default** — isolasi workspace/tenant + ACL sebelum konteks masuk ke LLM (Fase 2 & 6).
- **Adapter untuk vendor** — LLM (OpenAI/Anthropic/Gemini/lokal) dan vector store (pgvector → Qdrant) selalu di balik interface.

## Environment

Salin `.env.example` → `.env`. Prefix variabel aplikasi: `APP_` (mis. `APP_DATABASE_URL`). Jangan pernah commit `.env` — sudah dicegah oleh [.gitignore](.gitignore).

## Langkah berikutnya

Fase 1–10 selesai. Berikutnya (pasca-roadmap): pilot dengan data nyata yang disetujui, tuning reranker/prompt/chunking berdasar laporan evaluasi, dan migrasi vector store ke Qdrant bila pgvector tidak lagi memadai. Lihat [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) untuk alur & keputusan, dan [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) untuk deployment, operasi, incident response, rollback, serta scaling.
