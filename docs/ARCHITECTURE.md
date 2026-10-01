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

## Keputusan Fase 7 (Web Fallback)

| Keputusan | Alasan |
| --- | --- |
| Dua faktor izin: mode workspace (`internal_plus_web`) DAN `allow_web` per request | Roadmap: web hanya bila diizinkan; pengguna/workspace memegang kendali, default `internal_only` (aman). |
| Web dipanggil hanya saat bukti internal tidak mencukupi (retrieval kosong atau LLM menjawab `NO_ANSWER`) | Internal-first: data perusahaan tetap prioritas; web tidak pernah menimpa jawaban internal. |
| Provider adapter: DuckDuckGo (tanpa key) / SearXNG (self-host) / Tavily (API key), `none` = mati | Vendor dapat diganti tanpa mengubah orkestrasi; dev bisa jalan tanpa biaya/API key. |
| ACL domain allowlist+denylist dengan **deny menang**, dicocokkan pada hostname penuh | `deny: bad.example.com` tetap memblokir subdomain walau `allow: example.com` ada; hasil yang ditolak tetap dicatat di log. |
| Rate limit sliding-window per proses + timeout 8s + `max_results` | Roadmap: timeout & rate limit wajib; melindungi biaya dan mencegah loop pencarian. |
| Sanitasi konten (strip tag/entity/zero-width, collapse whitespace, batas panjang) sebelum masuk prompt | Konten web tidak dipercaya (prompt injection/HTML); hanya teks bersih yang menjadi konteks LLM. |
| Sitasi web: `source_type="web"`, `url`, `chunk_id`/`file_id` NULL, locator `url` | Roadmap: jangan campur data web dengan internal tanpa provenance — UI bisa membedakan warna/label dan tidak pernah salah mengunduh file. |
| `web_search_logs` mencatat query, provider, jumlah hasil, hasil yang ditolak, error | Provenance & audit biaya; dasar evaluasi kualitas fallback di Fase 9/10. |
| Kegagalan web search/LLM web di-degrade ke no-answer, bukan error 5xx | Chat tetap responsif; kegagalan eksternal tidak menjatuhkan alur internal. |

## Keputusan Fase 8 (UI/UX)

| Keputusan | Alasan |
| --- | --- |
| Token opaque disimpan di `localStorage`, guard redirect ke `/login` | Konsisten dengan auth Fase 2 (tanpa JWT/cookie); cukup untuk MVP dan mudah diganti cookie httpOnly nanti. |
| Chat streaming via `fetch` POST + pembacaan `ReadableStream` (bukan `EventSource`) | `EventSource` tidak bisa POST/Authorization; parser SSE kecil di `lib/api.ts` menangani event `meta`/`delta`/`done`/`error`. |
| Teks final otoritatif ada di event `done` | Jalur no-answer/sentinel bisa mengganti teks yang sempat ter-stream (UI tidak menampilkan `NO_ANSWER`). |
| Drawer sumber berisi filename, locator, snippet, skor; tombol unduh (internal) atau buka URL (web) | Roadmap: citation objects yang dapat diklik + sumber eksternal ditandai jelas. |
| Peran diambil dari `GET /workspaces/{id}` lalu dibandingkan dengan urutan role | Tombol aksi (upload/reindex/hapus) mengikuti RBAC yang sama dengan API — UI tidak menawarkan aksi yang akan gagal 403. |
| Polling status dokumen 4s hanya saat ada file `queued`/`processing` | Progress ingestion tanpa websocket; berhenti otomatis ketika semua selesai (hemat request). |
| CORS dibatasi `APP_CORS_ORIGINS_CSV` (default `http://localhost:3000`), `allow_credentials=false` | Frontend di origin berbeda butuh preflight; tanpa cookie sehingga credentials tidak diperlukan. |

## Keputusan Fase 6 (Retrieval & RAG)

| Keputusan | Alasan |
| --- | --- |
| Hybrid retrieval: dense pgvector + keyword FTS (`websearch_to_tsquery`, fallback ILIKE) | Roadmap minta dense + keyword; dua jalur menangkap kelemahan masing-masing (paraphrase vs istilah eksak). |
| ACL difilter `workspace_id` di level SQL pada semua jalur retrieval | Roadmap: ACL sebelum konteks ke LLM — bukti tenant lain mustahil masuk prompt, bukan sekadar difilter setelahnya. |
| Fusi deterministik: RRF per sumber + skor cosine terbobot (0.6/0.4) + threshold | Tanpa model eksternal (MVP); RRF stabil terhadap skala skor; deterministik agar test & audit reproducible. |
| Embedding local diganti bag-of-words hashing (dari whole-text hash) | Whole-text blake2b membuat cosine antar teks berbeda ~konstan → threshold tak bermakna; bag-of-words memberi skor shared-token sehingga ranking & threshold berfungsi di dev/test. Produksi tetap disarankan `openai`. |
| LLM adapter `local` stub / `openai` / `openai_compat` + sentinel `NO_ANSWER` | Pola sama dengan embeddings: dev/test deterministik tanpa API; `openai_compat` (httpx, parsing toleran) menampung gateway/vLLM lokal apa pun, termasuk endpoint yang menempelkan `data: [DONE]` pada respons non-stream. `NO_ANSWER` memisahkan "model bilang tak cukup bukti" dari error. |
| Prompt grounded: hanya dari konteks, sitasi [n], fakta/inferensi/ketidakpastian, no-answer wajib | Sesuai prinsip produk roadmap (grounded-first, source-aware). |
| Streaming SSE (event meta/delta/done) | Kontrak API minimum `POST /chat/stream`; delta diteruskan apa adanya dari `stream_generate` provider (token asli pada openai/openai_compat, kata pada stub lokal). Sentinel `NO_ANSWER` ditahan agar tidak terlihat klien. |
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
