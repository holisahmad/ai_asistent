# Catatan refactor uv workspace (Fase 4/5)

Backend & worker kini memakai package bersama `core/` (ai-asistent-core)
melalui uv workspace. Yang dipindah ke core: settings inti, models,
db/storage helpers, parsers, chunking, embeddings, vecstore.

Yang tersisa khusus backend (`backend/app/`): FastAPI (main, deps,
schemas, security, audit), API routes, settings turunan, logging.
Yang tersisa khusus worker (`worker/`): RQ worker, jobs pipeline.

Import lama `app.models` / `app.db` / `app.storage` diganti:
- `app.models`        → `ai_asistent_core.models`
- `app.db`            → `ai_asistent_core.db`
- `app.storage`       → `ai_asistent_core.storage`
- `app.settings`      → `ai_asistent_core.config` (get_settings)
