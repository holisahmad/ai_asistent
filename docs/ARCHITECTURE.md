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

## Keputusan Fase 6 (Retrieval & RAG)

| Keputusan | Alasan |
| --- | --- |
| Hybrid retrieval: dense pgvector + keyword FTS (`websearch_to_tsquery`, fallback ILIKE) | Roadmap minta dense + keyword; dua jalur menangkap kelemahan masing-masing (paraphrase vs istilah eksak). |
| ACL difilter `workspace_id` di level SQL pada semua jalur retrieval | Roadmap: ACL sebelum konteks ke LLM — bukti tenant lain mustahil masuk prompt, bukan sekadar difilter setelahnya. |
| Fusi deterministik: RRF per sumber + skor cosine terbobot (0.6/0.4) + threshold | Tanpa model eksternal (MVP); RRF stabil terhadap skala skor; deterministik agar test & audit reproducible. |
| Embedding local diganti bag-of-words hashing (dari whole-text hash) | Whole-text blake2b membuat cosine antar teks berbeda ~konstan → threshold tak bermakna; bag-of-words memberi skor shared-token sehingga ranking & threshold berfungsi di dev/test. Produksi tetap disarankan `openai`. |
| LLM adapter `local` stub / `openai` + sentinel `NO_ANSWER` | Pola sama dengan embeddings: dev/test deterministik tanpa API; ganti provider cukup env. `NO_ANSWER` memisahkan "model bilang tak cukup bukti" dari error. |
| Prompt grounded: hanya dari konteks, sitasi [n], fakta/inferensi/ketidakpastian, no-answer wajib | Sesuai prinsip produk roadmap (grounded-first, source-aware). |
| Streaming SSE (event meta/delta/done) | Kontrak API minimum `POST /chat/stream`; delta per kata simulasi token stream (adapter local deterministik), siap ditukar token asli OpenAI. |
| Sitasi disimpan sebagai baris `citations` (chunk_id, file_id, locator, snippet, score) | Citation objects klikabel & tahan waktu: riwayat chat tetap punya provenance walau chunk ter-reindex. |
| No-answer: pesan "Informasi belum tersedia" + `answer_kind=no_answer` + tanpa sitasi | Roadmap wajib menyatakan ketiadaan bukti; `answer_kind` memudahkan evaluasi & Web fallback Fase 7 memicu hanya bila flag ini aktif. |
| Migrasi 0004: chats/messages/citations FK CASCADE, chat.user_id SET NULL | Riwayat milik workspace (bukan per-user) sesuai model ACL workspace; audit `chat.ask` tetap mencatat user. |

## Keputusan Fase 4+5 (Ingestion, Parsing, Chunking, Indexing)

| Keputusan | Alasan |
| --- | --- |
| Package `core` bersama via uv workspace | Roadmap: worker terpisah dari API tapi butuh model/pipeline yang sama; uv workspace memberi satu lockfile tanpa publish package. |
| Parser interface kecil (`Parser` → `Section`+locator) | OCR & transkripsi (roadmap Fase 4) tinggal menambah implementasi Parser baru; pemanggil tak berubah. |
| Locator page/slide/sheet/row/char | Syarat sitasi roadmap; chunk mempertahankan locator section dominan. |
| Worker idempotent: hapus document+chunk lama sebelum tulis ulang | Reindex aman dijalankan ulang (retry RQ 3x). |
| Enqueue setelah commit DB (dan graceful bila Redis down) | Upload tidak gagal gara-gara queue; worker tidak balapan dengan transaksi API. |
| Koneksi Redis biner khusus RQ (`get_rq_connection`) | RQ menyimpan payload pickle (bytes); `decode_responses=True` merusak deserialisasi. |
| Estimasi token ≈4 karakter, target 512 + overlap 64 | MVP tanpa tokenizer eksternal; konfigurabel via `APP_CHUNK_*`, ganti tiktoken nanti tanpa ubah pipeline. |
| Embedding adapter: `local` hash (default) / `openai` | Dev/test offline deterministik; produksi cukup set `APP_EMBEDDING_PROVIDER=openai` + API key. |
| pgvector (cosine, IVFFlat lists=100) di `document_chunks.embedding` | MVP-first sesuai roadmap; `VectorStoreProtocol` siap diganti Qdrant. ACL difilter di query (workspace_id). |
| Migrasi 0003: `CREATE EXTENSION vector` + tabel documents/document_chunks | Satu sumber skema: worker tidak punya migrasi sendiri. |
| Smoke test nyata: upload→Redis→worker burst→pgvector terisi | Bukan hanya mock: pipeline terbukti jalan end-to-end di infra lokal. |

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

`GET /health/live`, `GET /health/ready` — sudah ada. `POST /api/v1/workspaces/{id}/chat/stream`, `GET /api/v1/workspaces/{id}/chats`, `GET /api/v1/workspaces/{id}/chats/{chat_id}` — ada sejak Fase 6. Sisanya (`POST /api/v1/sources/url`, `GET /api/v1/jobs/{id}`, dst.) dibangun per fase sesuai daftar API minimum di roadmap.

## Model data

users, workspaces, memberships, roles, files, file_versions, documents, document_chunks, ingestion_jobs, chats, messages, citations, audit_events — sudah ada (Fase 2–6). `web_search_logs` mengikuti di Fase 7. Daftar lengkap di roadmap.
