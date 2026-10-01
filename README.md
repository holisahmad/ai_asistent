# AI Knowledge Assistant

Asisten AI knowledge base perusahaan: grounded-first, source-aware, multi-tenant, dan siap produksi. Panduan lengkap ada di [roadmap.md](roadmap.md).

## Status: Fase 1 — Foundation ✅

Struktur project, infrastruktur Docker, health checks, CI, dan tooling kualitas sudah berjalan.

| Komponen | Teknologi | Port dev |
| --- | --- | --- |
| Frontend | Next.js 15 + React 19 + Tailwind v4 | 3000 |
| Backend API | FastAPI + SQLAlchemy + Pydantic v2 | 8000 |
| Worker | Redis + RQ (queue `default`) | — |
| Database | PostgreSQL 16 (+pgvector menyusul) | **5433** (host) |
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
make lint        # ruff (backend & worker)
make typecheck   # mypy --strict (backend & worker) + tsc (frontend)
make test        # pytest (backend & worker)
make smoke       # curl /health/live & /health/ready (api harus berjalan)
```

CI (GitHub Actions) menjalankan hal yang sama di setiap push/PR — lihat [.github/workflows/ci.yml](.github/workflows/ci.yml).

## Struktur

```
ai_asistent/
├── backend/          # FastAPI: app/, tests/, pyproject.toml
│   └── app/
│       ├── api/routes/   # health.py (live/ready) — auth/files/chat menyusul
│       ├── dependencies.py   # engine DB & Redis (lazy)
│       ├── logging.py        # structured JSON logs
│       ├── settings.py       # pydantic-settings (.env root, prefix APP_)
│       └── main.py           # app factory
├── worker/           # RQ worker: worker/jobs.py registry + tests/
├── frontend/         # Next.js App Router: app/, lib/
├── docs/             # catatan arsitektur & keputusan
├── infra/            # (disediakan untuk Dockerfile & konfigurasi deploy)
├── docker-compose.yml    # Postgres + Redis + MinIO + healthchecks
├── .env.example          # template config, tanpa secret
└── roadmap.md            # panduan eksekusi 10 fase
```

## Prinsip yang dipegang (dari roadmap.md)

- **Grounded-first** — jawaban hanya dari konteks lolos threshold; tanpa bukti → "informasi belum tersedia".
- **Async by design** — parsing/OCR/transkripsi/embedding/indexing sebagai job worker idempotent.
- **Secure by default** — isolasi workspace/tenant + ACL sebelum konteks masuk ke LLM (Fase 2 & 6).
- **Adapter untuk vendor** — LLM (OpenAI/Anthropic/Gemini/lokal) dan vector store (pgvector → Qdrant) selalu di balik interface.

## Environment

Salin `.env.example` → `.env`. Prefix variabel aplikasi: `APP_` (mis. `APP_DATABASE_URL`). Jangan pernah commit `.env` — sudah dicegah oleh [.gitignore](.gitignore).

## Langkah berikutnya

Fase 2 (auth, workspace, RBAC, audit) → Fase 3 (upload + storage) → dst. Lihat [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) untuk alur end-to-end.
