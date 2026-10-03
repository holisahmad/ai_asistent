# Config Reference — Semua variabel `APP_*`

Semua konfigurasi dibaca dari environment variables dengan prefix `APP_`.
Sumber prioritas (tinggi ke rendah): env var → file `.env` di root repo → nilai default.

Setting dibaca oleh `CoreSettings` (`core/src/ai_asistent_core/config.py`) via
`pydantic-settings`. Tipe dan default terdokumentasi di sini.

---

## Cara Pemakaian

```bash
# .env di root repo (development)
APP_LLM_PROVIDER=openai_compat
APP_OPENAI_BASE_URL=http://localhost:8080
APP_OPENAI_API_KEY=sk-local

# Override satu-satu untuk A/B eval
make eval ARGS='--set answer_mode=extractive --set answer_extractive_threshold=0.4'
make bench ARGS='--set reranker_enabled=false'
```

---

## 1. Lingkungan & Logging

| Variabel | Tipe | Default | Keterangan |
| --- | --- | --- | --- |
| `APP_ENVIRONMENT` | `str` | `development` | `development` \| `staging` \| `production` |
| `APP_LOG_LEVEL` | `str` | `INFO` | `DEBUG` \| `INFO` \| `WARNING` \| `ERROR` \| `CRITICAL` |

---

## 2. Database & Antrian

| Variabel | Tipe | Default | Keterangan |
| --- | --- | --- | --- |
| `APP_DATABASE_URL` | `str` | `postgresql+psycopg://ai_assistant:ai_assistant@localhost:5433/ai_assistant` | URL koneksi PostgreSQL (psycopg3 async format) |
| `APP_REDIS_URL` | `str` | `redis://localhost:6380/0` | URL Redis untuk antrian RQ |
| `APP_QUEUE_NAME` | `str` | `default` | Nama antrian RQ worker |

---

## 3. Object Storage (MinIO / S3-compatible)

| Variabel | Tipe | Default | Keterangan |
| --- | --- | --- | --- |
| `APP_MINIO_ENDPOINT` | `str` | `localhost:9000` | Host:port MinIO |
| `APP_MINIO_ACCESS_KEY` | `str` | `minioadmin` | Access key MinIO |
| `APP_MINIO_SECRET_KEY` | `str` | `minioadmin` | Secret key MinIO — **ganti di produksi** |
| `APP_MINIO_BUCKET` | `str` | `ai-assistant` | Nama bucket default |
| `APP_MINIO_SECURE` | `bool` | `false` | Gunakan HTTPS ke MinIO |
| `APP_MAX_UPLOAD_BYTES` | `int` | `104857600` (100 MB) | Batas ukuran file upload per request |
| `APP_PRESIGN_EXPIRY_SECONDS` | `int` | `900` | TTL presigned download URL (detik) |

---

## 4. API & Keamanan

| Variabel | Tipe | Default | Keterangan |
| --- | --- | --- | --- |
| `APP_CORS_ORIGINS_CSV` | `str` | `http://localhost:3000` | Origin CORS diizinkan, pisah koma |
| `APP_API_RATE_LIMIT_PER_MIN` | `int` | `120` | Maksimum request per menit per user/token; `0` = nonaktif |
| `APP_API_RATE_LIMIT_BURST` | `int` | `0` | Kuota tambahan burst satu kali jalan |
| `APP_METRICS_TOKEN` | `str\|None` | `None` | Bearer token untuk `GET /metrics`; kosong = endpoint terbuka |
| `APP_REQUEST_ID_HEADER` | `str` | `X-Request-ID` | Header request ID untuk tracing |
| `APP_AUDIT_LOG_FILE` | `str\|None` | `None` | Path file JSONL audit trail; kosong = dinonaktifkan |

---

## 5. Ketahanan Panggilan Eksternal

| Variabel | Tipe | Default | Keterangan |
| --- | --- | --- | --- |
| `APP_EXTERNAL_MAX_ATTEMPTS` | `int` | `3` | Jumlah maksimum retry untuk panggilan eksternal (LLM, web) |
| `APP_EXTERNAL_RETRY_BASE_SECONDS` | `float` | `0.5` | Delay awal exponential backoff (detik) |
| `APP_EXTERNAL_RETRY_MAX_SECONDS` | `float` | `8.0` | Delay maksimum antara retry (detik) |
| `APP_BREAKER_FAILURE_THRESHOLD` | `int` | `5` | Jumlah kegagalan berturut sebelum circuit breaker OPEN |
| `APP_BREAKER_RECOVERY_SECONDS` | `float` | `60.0` | Waktu tunggu sebelum circuit breaker mencoba lagi (detik) |

---

## 6. Ingestion & Embedding

| Variabel | Tipe | Default | Keterangan |
| --- | --- | --- | --- |
| `APP_CHUNK_TARGET_TOKENS` | `int` | `512` | Target ukuran chunk dalam token |
| `APP_CHUNK_OVERLAP_TOKENS` | `int` | `64` | Overlap antar chunk (token) untuk kontinuitas konteks |
| `APP_EMBEDDING_DIM` | `int` | `384` | Dimensi vektor embedding |
| `APP_EMBEDDING_BATCH_SIZE` | `int` | `32` | Jumlah teks per batch embedding |
| `APP_EMBEDDING_PROVIDER` | `str` | `local` | `local` (hash BoW, tanpa GPU) \| `openai` |
| `APP_OPENAI_API_KEY` | `str\|None` | `None` | API key OpenAI; wajib bila `embedding_provider=openai` atau `llm_provider=openai` |
| `APP_OPENAI_EMBEDDING_MODEL` | `str` | `text-embedding-3-small` | Model embedding OpenAI |

---

## 7. Retrieval & Reranker

| Variabel | Tipe | Default | Keterangan |
| --- | --- | --- | --- |
| `APP_RETRIEVAL_TOP_K` | `int` | `6` | Jumlah chunk terbaik dikembalikan ke LLM |
| `APP_RETRIEVAL_CANDIDATES` | `int` | `24` | Jumlah kandidat yang difusi sebelum rerank |
| `APP_RETRIEVAL_MIN_SCORE` | `float` | `0.05` | Ambang skor minimum untuk lolos fusi |
| `APP_RERANKER_ENABLED` | `bool` | `true` | Aktifkan reranker BM25+IDF; `false` = urutan fusi murni |
| `APP_RERANKER_PROVIDER` | `str` | `lexical` | `lexical` (BM25 deterministik) \| `none` |
| `APP_RERANKER_TOP_N` | `int` | `0` | Jumlah kandidat teratas yang diurutkan ulang; `0` = semua |

> **Catatan:** `APP_RERANKER_ENABLED=true` default karena terbukti menaikkan recall@5 0.9→1.0
> dan MRR 0.80→0.88 pada dataset headroom tanpa regresi dataset gate. Lihat
> `docs/UPGRADE_PLAN.md` Fase 1 untuk detail.

---

## 8. LLM Provider

| Variabel | Tipe | Default | Keterangan |
| --- | --- | --- | --- |
| `APP_LLM_PROVIDER` | `str` | `local` | `local` (stub dev) \| `openai` \| `openai_compat` |
| `APP_OPENAI_CHAT_MODEL` | `str` | `gpt-4o-mini` | Model chat OpenAI |
| `APP_OPENAI_BASE_URL` | `str\|None` | `None` | Endpoint OpenAI-compatible (vLLM/gateway); kosong = `api.openai.com` |
| `APP_OPENAI_TIMEOUT_SECONDS` | `float` | `60.0` | Timeout HTTP ke LLM (detik) |
| `APP_RAG_MAX_CONTEXT_CHARS` | `int` | `6000` | Batas karakter total konteks yang dikirim ke LLM |

> **Provider `local`** adalah stub deterministik untuk dev/test — tidak memanggil API.
> Ganti ke `openai` atau `openai_compat` untuk produksi.

---

## 9. Mode Jawaban (Fase 2 upgrade)

| Variabel | Tipe | Default | Keterangan |
| --- | --- | --- | --- |
| `APP_ANSWER_MODE` | `str` | `generative` | `generative` \| `extractive` \| `auto` |
| `APP_ANSWER_EXTRACTIVE_THRESHOLD` | `float` | `0.55` | Ambang `LexicalConfidence.score` [0–1] untuk mode ekstraktif |
| `APP_ANSWER_MIN_MARGIN` | `float` | `0.10` | Margin minimum skor chunk #1 vs #2; kecil = LLM lebih aman |
| `APP_ANSWER_MAX_CHARS` | `int` | `600` | Panjang maksimum cuplikan ekstraktif (karakter); `0` = tidak dipotong |

**Perbandingan mode:**

| Mode | LLM dipanggil | Hemat token | Grounded | Streaming |
| --- | --- | --- | --- | --- |
| `generative` | Selalu | ❌ | ✅ | ✅ |
| `extractive` | Tidak (bila lolos threshold) | ✅✅ | ✅ (cuplikan verbatim) | ✅ |
| `auto` | Fallback bila ekstraktif gagal | ✅ | ✅ | ✅ |

---

## 10. Query Rewriting (Fase 3 upgrade)

| Variabel | Tipe | Default | Keterangan |
| --- | --- | --- | --- |
| `APP_QUERY_REWRITE_ENABLED` | `bool` | `false` | Aktifkan rewriting berbasis aturan (buang frasa meta, ekspansi sinonim) |

> Default `false` — aktifkan hanya setelah uplift terukur di dataset headroom.

---

## 11. SSRF Protection & URL Fetch (Fase 4 upgrade)

| Variabel | Tipe | Default | Keterangan |
| --- | --- | --- | --- |
| `APP_URL_VALIDATION_ENABLED` | `bool` | `true` | Validasi SSRF sebelum fetch (whitelist skema, tolak IP private) |
| `APP_URL_FETCH_MAX_BYTES` | `int` | `200000` (200 KB) | Batas ukuran respons fetch eksternal |
| `APP_URL_DENYLIST_REGEX` | `str` | `` | Regex URL yang selalu diblokir, pisah `|`; kosong = none |
| `APP_URL_ALLOWLIST_REGEX` | `str` | `` | Regex URL yang diizinkan (setelah private IP check); kosong = semua |

---

## 12. External Reader (Fase 5 upgrade)

| Variabel | Tipe | Default | Keterangan |
| --- | --- | --- | --- |
| `APP_WEB_READER` | `str` | `http` | `http` (HttpReader + safefetch) \| provider lain (future) |
| `APP_WEB_READER_TIMEOUT_SECONDS` | `float` | `8.0` | Timeout fetch halaman web (detik) |

---

## 13. Document Parser (Fase 6 upgrade)

| Variabel | Tipe | Default | Keterangan |
| --- | --- | --- | --- |
| `APP_DOCUMENT_PARSER` | `str` | `builtin` | `builtin` (pypdf/python-docx/etc) \| `docling` (layout analysis, opsional) |
| `APP_DOCUMENT_FALLBACK` | `str\|None` | `None` | Provider fallback (reserved, belum dipakai) |

> **`docling`** membutuhkan `pip install docling` (~500 MB, torch-based).
> Tidak terinstal secara default. Aktifkan hanya bila kualitas ekstraksi PDF kompleks
> lebih penting dari ukuran image.

---

## 14. Web Fallback & Search (Fase 7)

| Variabel | Tipe | Default | Keterangan |
| --- | --- | --- | --- |
| `APP_WEB_FALLBACK_MODE` | `str` | `internal_only` | `internal_only` \| `internal_plus_web` |
| `APP_WEB_SEARCH_PROVIDER` | `str` | `none` | `none` \| `bing_rss` \| `duckduckgo` \| `searx` \| `tavily` |
| `APP_WEB_SEARCH_FALLBACK_PROVIDERS_CSV` | `str` | `` | Provider cadangan (CSV) bila provider utama gagal |
| `APP_WEB_SEARCH_BASE_URL` | `str\|None` | `None` | Base URL untuk Searx (mis. `http://searx:8080`) |
| `APP_TAVILY_API_KEY` | `str\|None` | `None` | API key Tavily; wajib bila `web_search_provider=tavily` |
| `APP_WEB_SEARCH_TIMEOUT_SECONDS` | `float` | `8.0` | Timeout pencarian web (detik) |
| `APP_WEB_SEARCH_MAX_RESULTS` | `int` | `5` | Jumlah maksimum hasil pencarian web |
| `APP_WEB_SEARCH_MARKET` | `str` | `id-ID` | Locale/market Bing RSS (mis. `id-ID`, `en-US`) |
| `APP_WEB_SEARCH_RATE_LIMIT_PER_MIN` | `int` | `10` | Rate limit pencarian web per menit |
| `APP_WEB_SEARCH_DOMAIN_ALLOWLIST_CSV` | `str` | `` | Domain diizinkan (CSV); kosong = semua |
| `APP_WEB_SEARCH_DOMAIN_DENYLIST_CSV` | `str` | `` | Domain diblokir (CSV); menang atas allowlist |
| `APP_WEB_EVIDENCE_MIN_RELEVANCE` | `float` | `0.34` | Ambang relevansi minimum hasil web; di bawah ini → diabaikan |
| `APP_WEB_EVIDENCE_MIN_RESULTS` | `int` | `1` | Jumlah minimum hasil lolos; kurang dari ini → no_answer |

---

## Template `.env` Lengkap

```bash
# ============================================================
# ai_asistent — .env template (salin ke .env, isi nilai nyata)
# ============================================================

# --- Lingkungan ---
APP_ENVIRONMENT=development
APP_LOG_LEVEL=INFO

# --- Database ---
APP_DATABASE_URL=postgresql+psycopg://ai_assistant:ai_assistant@localhost:5433/ai_assistant
APP_REDIS_URL=redis://localhost:6380/0
APP_QUEUE_NAME=default

# --- Object Storage ---
APP_MINIO_ENDPOINT=localhost:9000
APP_MINIO_ACCESS_KEY=minioadmin
APP_MINIO_SECRET_KEY=minioadmin          # GANTI DI PRODUKSI
APP_MINIO_BUCKET=ai-assistant
APP_MINIO_SECURE=false

# --- API & Keamanan ---
APP_CORS_ORIGINS_CSV=http://localhost:3000
APP_API_RATE_LIMIT_PER_MIN=120
APP_METRICS_TOKEN=                        # kosong = endpoint terbuka

# --- Embedding ---
APP_EMBEDDING_PROVIDER=local             # ganti ke openai untuk produksi
APP_OPENAI_API_KEY=                       # wajib bila provider=openai

# --- LLM ---
APP_LLM_PROVIDER=local                   # ganti ke openai atau openai_compat
APP_OPENAI_CHAT_MODEL=gpt-4o-mini
# APP_OPENAI_BASE_URL=http://localhost:8080  # untuk vLLM/gateway

# --- Retrieval & Reranker ---
APP_RETRIEVAL_TOP_K=6
APP_RETRIEVAL_CANDIDATES=24
APP_RERANKER_ENABLED=true
APP_RERANKER_PROVIDER=lexical

# --- Mode Jawaban (Fase 2) ---
APP_ANSWER_MODE=generative               # ganti ke auto untuk hemat token
APP_ANSWER_EXTRACTIVE_THRESHOLD=0.55
APP_ANSWER_MIN_MARGIN=0.10
APP_ANSWER_MAX_CHARS=600

# --- Query Rewriting (Fase 3, default OFF) ---
APP_QUERY_REWRITE_ENABLED=false

# --- SSRF & URL Fetch (Fase 4) ---
APP_URL_VALIDATION_ENABLED=true
APP_URL_FETCH_MAX_BYTES=200000

# --- Web Fallback (Fase 7, default OFF) ---
APP_WEB_FALLBACK_MODE=internal_only
APP_WEB_SEARCH_PROVIDER=none
# APP_TAVILY_API_KEY=tvly-xxxx            # wajib bila provider=tavily
```

---

## Catatan Produksi

1. **Secrets** (`MINIO_SECRET_KEY`, `OPENAI_API_KEY`, `METRICS_TOKEN`, `TAVILY_API_KEY`)
   — jangan pernah commit ke repo; gunakan secret manager atau vault.
2. **`APP_LLM_PROVIDER=local`** adalah stub deterministik untuk dev/test.
   Tidak cocok untuk produksi — ganti ke `openai` atau `openai_compat`.
3. **`APP_RERANKER_ENABLED=true`** adalah default karena telah terbukti meningkatkan
   kualitas retrieval. Lihat [`docs/UPGRADE_PLAN.md`](UPGRADE_PLAN.md) untuk detail metrik.
4. **`APP_WEB_FALLBACK_MODE=internal_only`** default aman. Aktifkan `internal_plus_web`
   hanya setelah mengonfigurasi provider pencarian dan memverifikasi SSRF protection.
5. Semua nilai `float` menerima notasi titik desimal (`0.55`) atau integer (`1`).
