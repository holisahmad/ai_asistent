# Upgrade Plan — Reranker, Answer Mode, External Research, Parser

Rencana pengerjaan turunan dari `AI_KNOWLEDGE_ASSISTANT_DOCUMENT_INTELLIGENCE_UPGRADE.md`,
disaring agar sesuai kondisi repo dan hardware target (MacBook Pro Intel 2018, RAM terbatas).

Prinsip:

- **Ukur dulu, baru klaim perbaikan.** Setiap fase retrieval/answer harus melewati
  `backend/tests/test_retrieval_eval.py` dan menyertakan delta metrik di laporan.
- **Tanpa layanan berat baru.** Tidak menambah model lokal besar, torch, atau server baru
  pada jalur default. Parser/provider berat bersifat *opt-in* lewat konfigurasi.
- **Provider-neutral.** Adapter baru mengikuti pola `Protocol` yang sudah ada
  (`Parser`, `EmbeddingProvider`, `LLMProvider`, `WebSearchProvider`).
- **Satu fase satu commit.** lint → typecheck → test → eval → push → CI hijau.

Ringkasan urutan:

| Fase | Item | Prioritas | Dependency | Dampak ukur |
| --- | --- | --- | --- | --- |
| 0 | Baseline & harness evaluasi | P0 | — | acuan delta |
| 1 | Reranker ringan (deterministik) | P0 | 0 | recall@5, MRR |
| 2 | Answer mode extractive bertingkat | P0 | 1 | latensi, biaya token |
| 3 | Query rewriting berbasis aturan | P1 | 1 | recall@5 |
| 4 | SSRF-safe fetch & validasi URL | P1 (security) | — | uji keamanan |
| 5 | External reader adapter (opsional) | P2 | 4 | kualitas jawaban web |
| 6 | Parser gateway + Docling opsional | P2 | 3 | kualitas ekstraksi |
| — | MinerU / Firecrawl / Jina / LlamaParse | P3 | 5,6 | ditunda |

Urutan sengaja berbeda dari dokumen sumber (yang menaruh Docling di depan): parser kita
sudah menghasilkan locator page/sheet yang dipakai sitasi, sedangkan kualitas **urutan
kandidat** saat ini paling lemah karena embedding lokal bag-of-words. Karena itu reranker
lebih dulu, parser berat belakangan dan opsional.

---

## Fase 0 — Baseline & Harness Evaluasi

Tujuan: punya angka acuan sebelum mengubah apa pun, dan cara membandingkan dua konfigurasi.

Langkah:

1. Jalankan dan simpan laporan acuan: `make eval ARGS=--write` →
   `docs/reports/eval-<stamp>.md` (sudah gitignored).
2. Catat metrik acuan di dokumen ini: recall@5, MRR, citation correctness, no-answer
   accuracy, hallusinasi, false-no-answer, plus latensi p50/p95 dari `make bench`.
3. Tambah opsi `scripts/eval_rag.py` untuk menjalankan dataset dengan konfigurasi
   bergantian (mis. `--set reranker_enabled=true`) agar perbandingan A/B reproducible.

File: [scripts/eval_rag.py](scripts/eval_rag.py), [scripts/bench.py](scripts/bench.py),
[core/src/ai_asistent_core/eval.py](core/src/ai_asistent_core/eval.py).

Kriteria diterima: angka acuan terdokumentasi; quality gate yang ada tetap hijau.

Baseline (isi setelah dijalankan): recall@5 = `<…>`, MRR = `<…>`, p95 = `<…> ms`.

---

## Fase 1 — Reranker Ringan (P0)

Tujuan: mengubah daftar kandidat fusi menjadi peringkat yang lebih relevan, tanpa model
berat.

Desain:

- `RerankerProtocol` (`rerank(query, candidates, top_k) -> list[RankedCandidate]`).
- Default `LexicalReranker` deterministik, tanpa dependency baru: gabungan skor fusi +
  overlap term bermakna + kedekatan frasa + sinyal metadata (nama file/judul), semua
  dihitung lokal.
- Jalur opsional (belum diaktifkan): adapter *hosted* di balik protocol yang sama.
- Alur: `retrieval_candidates` (kini 24) → rerank → `retrieval_top_k` (kini 6) → konteks LLM.
- ACL tetap di SQL **sebelum** rerank; reranker tidak pernah melihat chunk di luar workspace.

Config baru: `APP_RERANKER_ENABLED` (default `false` sampai gate terbukti), `APP_RERANKER_PROVIDER`
(`lexical` | `none`), `APP_RERANKER_TOP_N`.

File: baru `core/src/ai_asistent_core/rerank.py`; ubah
[retrieval.py](core/src/ai_asistent_core/retrieval.py),
[config.py](core/src/ai_asistent_core/config.py), [rag.py](core/src/ai_asistent_core/rag.py).

Test & eval: unit test reranker (deterministik, batas top_n, tanpa regression urutan saat
skor sama) + jalankan `test_retrieval_eval.py` dan bandingkan recall@5/MRR sebelum-sesudah.

Kriteria diterima: tidak ada regresi ACL; quality gate hijau; delta recall@5/MRR dicatat
di laporan. Bila uplift tidak terukur, default tetap `false` dan temuan dilaporkan
(roadmap: jangan klaim tanpa bukti).

---

## Fase 2 — Answer Mode Extractive Bertingkat (P0)

Tujuan: tidak memanggil model bila retrieval sudah cukup, sehingga ringan dan murah.

Desain:

- Mode eksplisit: `extractive` (tanpa model) dan `llm`. Nilai saat ini `local` di
  [llm.py](core/src/ai_asistent_core/llm.py) sebenarnya sudah extractive — jadikan semantiknya
  eksplisit, bukan implisit.
- Kebijakan: bila chunk teratas ≥ `APP_ANSWER_EXTRACTIVE_THRESHOLD`, sajikan kutipan
  passage + sitasi tanpa memanggil LLM; selain itu baru panggil provider LLM.
- Pertahankan perilaku: `NO_ANSWER`, sitasi, streaming, dan `source_type` tidak berubah.

Config baru: `APP_ANSWER_MODE` (`extractive` | `llm`), `APP_ANSWER_EXTRACTIVE_THRESHOLD`.

File: [llm.py](core/src/ai_asistent_core/llm.py), [rag.py](core/src/ai_asistent_core/rag.py),
[config.py](core/src/ai_asistent_core/config.py).

Test & eval: test rag existing tetap lolos; tambah test jalur extractive (sitasi benar,
no-answer benar, LLM tidak dipanggil); ukur penurunan latensi token dari `make bench`.

Kriteria diterima: quality gate hijau; jawaban tetap grounded + bersitasi; latensi/penggunaan
LLM turun terdokumentasi.

---

## Fase 3 — Query Rewriting Berbasis Aturan (P1)

Tujuan: memperbaiki kueri yang "berisik" (basa-basi chat) tanpa menambah panggilan model.

Desain:

- `query_rewrite.py` deterministik: buang frasa meta (`carikan`, `tolong`, `di internet`,
  `saya mau tahu`), pakai ulang `normalize_query`, hasilkan varian kueri untuk keyword
  search (semantic/keyword/entity).
- Default `off` (`APP_QUERY_REWRITE_ENABLED=false`); bila on dan uplift tidak terukur,
  tetap off dan dilaporkan.

Kaitan nyata: keluhan "carikan tambahan informasi di web" adalah kueri meta tanpa topik;
rewriter ini dapat memakai pertanyaan sebelumnya sebagai konteks topik.

File: baru `core/src/ai_asistent_core/query_rewrite.py`; ubah
[retrieval.py](core/src/ai_asistent_core/retrieval.py) dan
[websearch.py](core/src/ai_asistent_core/websearch.py) (kueri web fallback).

Test & eval: unit test aturan; jalankan eval on/off dan catat delta recall@5.

Kriteria diterima: default off tidak mengubah apa pun; mode on terukur atau dilaporkan
sebagai no-op.

---

## Fase 4 — SSRF-Safe Fetch & Validasi URL (P1, security)

Tujuan: prasyarat wajib sebelum menerima URL eksternal apa pun.

Desain:

- `safefetch.py`: allowlist skema (hanya http/https); resolve DNS lalu tolak IP
  private/loopback/link-local/metadata (`127.0.0.0/8`, `169.254.169.254`, `::1`, dst.);
  validasi ulang setiap redirect; batas ukuran byte, timeout, allowlist content-type.
- `fetch_page_text` di [websearch.py](core/src/ai_asistent_core/websearch.py) memakai jalur ini.

Test: unit test untuk localhost, IP privat, redirect ke internal, skema `file://`, dan
respons melebihi batas ukuran. Regresi: fetch halaman publik normal tetap bekerja.

Kriteria diterima: semua kasus SSRF tertolak; test keamanan hijau; tidak ada perubahan
perilaku pada URL publik.

---

## Fase 5 — External Reader Adapter (P2)

Tujuan: pemisahan "cari" dan "baca" lewat abstraksi, provider bisa diganti.

Desain:

- `ExternalReaderProtocol`; implementasi default `HttpReader` berbasis `safefetch` Fase 4.
- Slot untuk adapter Firecrawl/Jina di balik protocol yang sama (belum diaktifkan).
- Provenance eksternal diperkaya: `url`, `title`, `domain`, `retrieved_at`, tetap
  `source_type=web` dan tidak pernah dicampur dengan sitasi internal.

Config: `APP_WEB_READER` (`http` | provider lain kelak).

Test & eval: test normalisasi reader + provenance; uji timeout/rate-limit/circuit breaker.

Kriteria diterima: fallback web tetap grounded + bersitasi; provider baru bisa ditambah
tanpa mengubah [rag.py](core/src/ai_asistent_core/rag.py).

---

## Fase 6 — Parser Gateway + Docling Opsional (P2)

Tujuan: menaikkan kualitas dokumen kompleks **tanpa membebani** jalur default.

Desain:

- `DocumentParserProtocol` gateway yang membungkus parser yang ada di
  [parsers.py](core/src/ai_asistent_core/parsers.py) (pypdf, docx, pptx, xlsx, txt, md, csv, html).
- `DoclingParser` sebagai **extra dependency opsional** (tidak diinstal default; tidak
  dipasang otomatis di mesin Intel 2018). Diaktifkan lewat config.
- `APP_DOCUMENT_PARSER=builtin` (default) | `docling`; `APP_DOCUMENT_FALLBACK=` opsional.
- Chunking struktural (heading/tabel) baru dikerjakan **setelah** struktur tersedia dari
  parser, dan tetap harus lulus evaluasi sebelum menjadi default.

Test & eval: pastikan format yang didukung lama tetap bekerja (status ingestion, reindex,
locator sitasi tidak berubah) + benchmark kecil untuk perbandingan ekstraksi.

Kriteria diterima: default `builtin` tidak berubah; Docling hanya dipromosikan menjadi
default bila benchmark menunjukkan manfaat nyata di lingkungan target.

---

## Ditunda / Tidak Dikerjakan Sekarang

- **MinerU** — hanya untuk benchmark PDF; tidak masuk jalur produksi.
- **Firecrawl, Jina Reader, LlamaParse** — adapter opsional (biaya + API key + privasi);
  ditambahkan di balik protocol Fase 5/6 bila kebutuhannya nyata.
- **Structured/semantic chunking** — bergantung pada struktur hasil Fase 6; ukur dulu.
- **Observability event names** (§25) — perbaikan inkremental, menyusul per fase.
- **Migrasi Qdrant** — hanya bila pgvector terbukti tak memadai.

---

## Checklist Setiap Fase

```
lint            cd core/backend/worker && uv run ruff check .
typecheck       uv run mypy src (core/worker) & app (backend) + npx tsc --noEmit
unit tests      uv run pytest (core, backend, worker)
eval            make eval ARGS=--write  +  backend/tests/test_retrieval_eval.py
commit          pesan Indonesia + trailer Codebuff
CI              gh run watch <RUN_ID> --exit-status  (6 job hijau)
```
