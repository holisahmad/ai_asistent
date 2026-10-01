
# AI Knowledge Assistant — Technical Execution Roadmap

## Tujuan
Bangun asisten AI knowledge base perusahaan yang ringan, persisten, powerful, scalable, dinamis, aman, memiliki UI/UX elegan, dan layak produksi.

Sistem harus menerima PDF, DOCX, PPTX, XLSX, TXT, Markdown, HTML, CSV, gambar, audio, video, URL web, dan link video. Jawaban harus berdasarkan knowledge base internal dengan sitasi sumber. Jika bukti tidak tersedia, sistem wajib menyatakan informasi belum tersedia. Pencarian web bersifat opsional dan dapat dikontrol pengguna/workspace.

## Prinsip Produk
- Grounded-first: jangan mengarang jawaban.
- Source-aware: tampilkan sumber dan locator jika tersedia.
- Internal-first: prioritaskan data perusahaan.
- Web fallback harus eksplisit.
- Secure by default: isolasi tenant/workspace dan ACL.
- Async by design: parsing, OCR, transkripsi, embedding, dan indexing berjalan sebagai background job.
- MVP-first: hindari over-engineering sebelum validasi.
- Production-ready: testing, observability, backup, audit log, dan recovery wajib.

## Stack Rekomendasi
- Frontend: Next.js, React, TypeScript, Tailwind CSS, shadcn/ui.
- Backend: FastAPI, Python, Pydantic, SQLAlchemy, Alembic.
- Database: PostgreSQL; gunakan pgvector untuk MVP.
- Object storage: S3-compatible; MinIO untuk development.
- Queue/cache: Redis + RQ untuk MVP; Celery/Temporal bila workflow meningkat.
- Retrieval: hybrid semantic + keyword search, metadata filtering, reranking.
- AI: provider adapter untuk OpenAI, Anthropic, Gemini, dan model lokal.
- Auth: OIDC/OAuth2 dengan RBAC; Keycloak/Auth.js/Clerk sesuai deployment.
- Observability: structured logs, OpenTelemetry, Sentry, Prometheus/Grafana.
- Deployment: Docker Compose untuk development; managed services/Kubernetes untuk produksi.

## Arsitektur Alur
1. User mengunggah file atau URL.
2. API memvalidasi ukuran, MIME type, checksum, dan izin.
3. File asli disimpan ke object storage; metadata ke PostgreSQL.
4. Worker mengekstrak teks, tabel, halaman, heading, dan metadata.
5. Audio/video ditranskripsi; gambar diproses OCR bila diaktifkan.
6. Teks dinormalisasi dan dipecah menjadi chunk token-aware.
7. Chunk di-embed dan disimpan ke vector index.
8. Pertanyaan memicu retrieval hybrid dan reranking.
9. LLM menjawab hanya dari konteks yang lolos threshold.
10. Jika tidak cukup bukti dan web fallback aktif, lakukan web search.
11. Kembalikan jawaban, uncertainty, provenance, dan sitasi.

## MVP Wajib
- Login dan role dasar.
- Upload PDF, DOCX, PPTX, TXT, MD.
- URL ingestion untuk halaman web.
- Status: queued, processing, indexed, failed, deleted.
- Chat streaming.
- Retrieval hybrid sederhana.
- Jawaban grounded dengan sumber.
- Respons “informasi belum tersedia”.
- Mode internal-only atau internal-plus-web.
- Daftar dokumen, hapus, dan reindex.
- Docker Compose, migration, test, health check, dan README setup.

## Fase Eksekusi

### Fase 1 — Foundation
- Buat struktur frontend/backend/worker/docs/infra.
- Buat konfigurasi environment tanpa secret yang di-commit.
- Docker Compose untuk PostgreSQL, Redis, dan MinIO.
- Health/readiness endpoints.
- Lint, format, type-check, test, dan CI.
- Selesai jika project dapat dijalankan dengan satu instruksi dan CI lulus.

### Fase 2 — Auth dan Workspace
- Implementasikan user, workspace/tenant, membership, role, session.
- Tambahkan admin/editor/contributor/viewer.
- Terapkan permission check pada semua endpoint.
- Audit event untuk upload, delete, reindex, chat, dan perubahan setting.
- Pastikan user tidak dapat melihat data workspace lain.

### Fase 3 — File Upload dan Storage
- Upload API dengan size/type validation.
- Checksum untuk deduplikasi.
- Object storage untuk file; PostgreSQL untuk metadata.
- Signed URL untuk akses file.
- Cancel, delete, retry, dan reindex.

### Fase 4 — Ingestion dan Parsing
- Buat parser interface yang dapat diganti.
- Implementasikan PDF, DOCX, PPTX, XLSX, TXT, MD, HTML, CSV.
- Tambahkan OCR serta transkripsi audio/video melalui provider adapter.
- Simpan page, slide, dan timecode sebagai source locator.
- Semua pekerjaan berat wajib melalui worker idempotent.

### Fase 5 — Chunking dan Indexing
- Normalisasi whitespace, heading, tabel, dan bahasa.
- Chunk token-aware dengan overlap terukur.
- Simpan document_id, version_id, page/slide/timecode, tenant_id, dan ACL pada setiap chunk.
- Embedding batch dan retry.
- Gunakan pgvector pada MVP; isolasikan vector repository agar dapat diganti Qdrant.

### Fase 6 — Retrieval dan RAG
- Optional query rewriting.
- Dense retrieval, keyword retrieval, metadata/ACL filter, lalu reranking.
- Terapkan ACL sebelum konteks diberikan ke LLM.
- Prompt grounded membedakan fakta, inferensi, dan ketidakpastian.
- Kembalikan citation objects yang dapat diklik.
- Tambahkan dataset evaluasi retrieval dan answer.

### Fase 7 — Web Fallback
- Mode internal-only, internal-plus-web, dan web-only.
- Web search hanya bila diizinkan dan bukti internal tidak mencukupi.
- Allowlist/denylist domain, timeout, rate limit, dan sanitasi konten.
- Tandai sumber eksternal secara jelas.
- Jangan mencampur data web dengan data internal tanpa provenance.

### Fase 8 — UI/UX
- Dashboard responsif dan accessible.
- Chat streaming, markdown, code block, retry, copy, feedback, dan source drawer.
- Upload drag-and-drop dengan progress dan error recovery.
- Document library dengan search, filter, tag, status, delete, dan reindex.
- Empty/loading/error states yang jelas.
- Desain konsisten, kontras baik, animasi ringan, dan performa terjaga.

### Fase 9 — Production Hardening
- Rate limiting, timeout, circuit breaker, retry/backoff, dan idempotency.
- Structured logs, metrics, traces, alerting, dan correlation ID.
- Backup PostgreSQL/object storage dan restore drill.
- Security review, dependency scan, secret scan, malware scan, dan prompt-injection mitigation.
- Benchmark p50/p95 latency, throughput, retrieval quality, dan biaya token.

### Fase 10 — Pilot dan Scale
- Uji dengan data perusahaan yang disetujui.
- Ukur correctness, citation correctness, recall, latency, cost, dan satisfaction.
- Perbaiki chunking, reranker, prompt, dan model berdasarkan data.
- Pisahkan API, worker, dan scheduler saat beban meningkat.
- Migrasikan vector store ke Qdrant jika pgvector tidak mencukupi.
- Dokumentasikan deployment, operasi, incident response, dan rollback.

## API Minimum
- POST /api/v1/auth/...
- POST /api/v1/files
- GET /api/v1/files
- GET /api/v1/files/{id}
- POST /api/v1/files/{id}/reindex
- DELETE /api/v1/files/{id}
- POST /api/v1/sources/url
- POST /api/v1/chat/stream
- GET /api/v1/chats
- GET /api/v1/chats/{id}
- GET /api/v1/jobs/{id}
- GET /health/live
- GET /health/ready

## Model Data Minimum
- users
- workspaces
- memberships
- roles
- files
- file_versions
- documents
- document_chunks
- ingestion_jobs
- chats
- messages
- citations
- web_search_logs
- audit_events

## Quality Gates
Setiap fase wajib memiliki unit test, integration test, API contract test, error handling, observability, dokumentasi, dan security/privacy review untuk data sensitif.

## Instruksi untuk AI Agent Eksekutor
1. Baca file ini dan inspeksi repository sebelum coding.
2. Jangan menghapus atau menimpa pekerjaan pengguna tanpa persetujuan.
3. Buat implementation plan singkat dan daftar asumsi sebelum eksekusi.
4. Eksekusi satu fase kecil pada satu waktu.
5. Setelah setiap fase jalankan test, lint, type-check, dan smoke test.
6. Jangan commit secret, credential, data perusahaan, atau binary besar.
7. Jangan memilih teknologi baru tanpa menjelaskan trade-off.
8. Gunakan adapter agar provider/vendor dapat diganti.
9. Semua jawaban AI wajib memiliki no-answer behavior dan provenance.
10. Prioritaskan keamanan tenant/ACL sebelum optimasi performa.
11. Jika requirement ambigu, tanyakan; jangan menebak perilaku bisnis kritis.
12. Update dokumentasi dan changelog setelah perubahan.
13. Laporkan perubahan, file, test, risiko, dan langkah berikutnya.

## Definition of Done
Produk siap pilot jika upload/indexing/chat bekerja end-to-end, jawaban grounded dan memiliki sitasi, no-answer berfungsi, web fallback dapat dikontrol, RBAC mencegah kebocoran data, UI usable, test dan CI lulus, log/metric tersedia, backup dan recovery terdokumentasi, serta deployment dapat diulang dari dokumentasi.

## Catatan Perangkat
Untuk MacBook Pro Intel 2018, gunakan laptop sebagai development/client. Jalankan LLM besar, OCR, transkripsi video/audio, dan worker berat melalui API atau server Linux/cloud bila resource lokal tidak mencukupi.