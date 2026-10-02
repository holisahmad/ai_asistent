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
| 0 | Baseline & harness evaluasi | P0 | — | acuan delta — **selesai** |
| 1 | Reranker ringan (deterministik) | P0 | 0 | recall@5, MRR — **selesai** (+0.10 / +0.083) |
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
3. Tambah opsi `scripts/eval_rag.py --set KEY=VALUE` (boleh berulang) untuk menjalankan
   dataset dengan konfigurasi bergantian agar perbandingan A/B reproducible.

File: [scripts/eval_rag.py](scripts/eval_rag.py), [scripts/bench.py](scripts/bench.py),
[core/src/ai_asistent_core/eval.py](core/src/ai_asistent_core/eval.py).

Kriteria diterima: angka acuan terdokumentasi; quality gate yang ada tetap hijau.

### Baseline terukur (2 Oktober 2026)

`make eval ARGS=--write` (LLM stub, `kb-retrieval-mini` v1, 15 kueri):

| Metrik | Nilai |
| --- | --- |
| recall@5 | 1.0 |
| MRR | 1.0 |
| citation_correctness | 1.0 |
| no_answer_accuracy | 1.0 |
| hallucination_rate | 0.0 |
| false_no_answer_rate | 0.0 |
| latency p50 / p95 | 0.0169 s / 0.0275 s |
| total_tokens_est / cost | 3182 / $0.0005 |

`make bench ARGS='--iterations 30'`: retrieval p50 6.0 ms / p95 13.3 ms;
chat+LLM p50 6.4 ms / p95 12.8 ms; throughput 63.6 kueri/detik; ~$0.001029/run.

### Temuan Fase 0 — tidak ada headroom

Semua metrik kualitas sudah **jenuh (1.0)** pada dataset ini, sehingga reranker maupun
perbaikan retrieval lain **tidak bisa dibuktikan** di sini: tidak ada ruang untuk naik,
dan `recall@5 ≥ 0.8` di CI juga tidak akan pernah turun. Dataset gate sengaja dipertahankan
sebagai jaring regresi, bukan tolok ukur perbaikan.

Konsekuensi: sebelum Fase 1 diklaim berhasil, perlu dataset **headroom** terpisah
(`docs/eval/retrieval_dataset_hard.json`) berisi dokumen distraktor (kata kunci mirip,
jawaban salah) dan kueri parafrase yang sengaja tidak memakai kata kunci dokumen target.
Dataset itu **tidak** disambungkan ke quality gate CI, hanya untuk mengukur uplift.

### Baseline dataset headroom (langkah pertama Fase 1 — selesai)

Dataset [`docs/eval/retrieval_dataset_hard.json`](eval/retrieval_dataset_hard.json)
(`kb-retrieval-hard` v2): **27 dokumen, 13 kueri** (10 berjawaban + 3 tanpa jawaban)
dalam 5 klaster topikal, tiap klaster berisi dokumen target panjang ditambah distraktor
pendek yang kaya kata umum.

| Metrik | Nilai | Ruang naik |
| --- | --- | --- |
| recall@5 | 0.9 | → 1.0 |
| MRR | 0.8 | → 1.0 |
| citation_correctness | 0.7 | → 1.0 |
| no_answer_accuracy | 1.0 | — |
| hallucination_rate | 0.0 | — |
| false_no_answer_rate | 0.0 | — |
| latency p50 / p95 | 0.0211 s / 0.0287 s | — |

Kueri yang belum optimal:

| Kueri | Posisi target |
| --- | --- |
| berapa maksimal biaya makan ketika ada pertemuan | di luar top-5 |
| berapa porsi biaya kesehatan yang ditanggung kantor bagi karyawan | 2 |
| berapa dana yang dibawa ketika bekerja di luar kota tiap hari | 2 |

**Catatan atribusi:** ketiga kueri itu berbentuk parafrase, sehingga perbaikinya menuntut
sinyal semantik, bukan sekadar kecocokan kata. Kueri lain sudah rank 1 dan tidak memberi
ruang. Saat Fase 1 berjalan, laporkan delta **per kueri**: bila reranker leksikal tidak
menyentuh ketiga kueri parafrase itu, itu temuan yang valid — artinya dibutuhkan reranker
semantik atau embedding lebih baik, bukan kegagalan rerankernya.

Perbaikan harness pada langkah ini:

- `scripts/eval_rag.py --verbose` mencetak peringkat kandidat dan posisi dokumen harapan,
  sehingga posisi (bukan cuma skor) terlihat.
- Kolom `Posisi` ditambahkan ke tabel laporan markdown.
- **Workspace khusus per dataset** (`eval-<nama-dataset>`): sebelumnya kedua dataset
  berbagi satu workspace, sehingga `cuti-tahunan.md` milik dataset hard tersingkir oleh
  milik dataset mini dan distraktor asing ikut tercampur. Korpus kini reproducible.
- Kueri `expected_filename=null` dibuat tanpa tumpang tindih token dengan dokumen mana
  pun (diverifikasi otomatis): stub LLM menjawab begitu ada token sama, jadi tabrakan
  insidental akan merusak metrik no-answer tanpa kaitan dengan retrieval.

Perintah A/B sekarang:

```bash
make eval ARGS='--write'
make eval ARGS="--dataset docs/eval/retrieval_dataset_hard.json --write"
make eval ARGS='--set retrieval_top_k=3'
```

---

## Fase 1 — Reranker Ringan (P0)

Tujuan: mengubah daftar kandidat fusi menjadi peringkat yang lebih relevan, tanpa model
berat.

Desain (implementasi aktual, `core/src/ai_asistent_core/rerank.py`):

- `RerankerProtocol.rerank(query, candidates) -> list[kandidat]` — provider-neutral,
  mengikuti pola adapter lain; `NoReranker` untuk provider `none`.
- `LexicalReranker`: skor ulang dengan pola **BM25** (IDF + saturasi tf + normalisasi
  panjang dokumen) plus pengali `TITLE_BONUS` untuk istilah pada judul/filename, lalu
  digabung dengan skor fusi (`WEIGHT_BM25` 0.7 + `WEIGHT_FUSION` 0.3, dinormalisasi
  relatif dalam kumpulan kandidat). Ini menambal celah embedding lokal yang **tidak
  punya IDF**: kata umum (kerja, tahun, biaya) sebelumnya ikut menaikkan dokumen yang
  salah sementara dokumen target kalah karena panjangnya.
- `score` **tidak diubah** — tetap skor fusi retrieval; reranker hanya mengubah urutan.
  Skor seri mempertahankan urutan asli (sort stabil) sehingga tidak ada regresi diam-diam.
- Tanpa dependency baru, tanpa jaringan, deterministik.
- Alur: `retrieval_candidates` (24) → fusi → threshold → **rerank** → `retrieval_top_k` (6).
- ACL tetap di SQL **sebelum** rerank; reranker tidak pernah melihat chunk di luar workspace.
- Jalur opsional: adapter *hosted* di balik protocol yang sama (belum diaktifkan).

Config: `APP_RERANKER_ENABLED` (**default `true` — lihat hasil di bawah**),
`APP_RERANKER_PROVIDER` (`lexical` | `none`), `APP_RERANKER_TOP_N` (0 = semua kandidat;
nilai >0 hanya mengurut ulang `top_n` kandidat depan dan sisanya ditempel di belakang,
sehingga tidak pernah menghilangkan kandidat).

File: baru `core/src/ai_asistent_core/rerank.py` + `core/tests/test_rerank.py`; ubah
[retrieval.py](core/src/ai_asistent_core/retrieval.py),
[config.py](core/src/ai_asistent_core/config.py), [.env.example](.env.example).
[rag.py](core/src/ai_asistent_core/rag.py) tidak diubah — pemanggilan tetap lewat `retrieve()`.

Prasyarat (hasil temuan Fase 0): **selesai** — dataset headroom dan baseline-nya sudah ada
di atas, jadi uplift bisa diukur. Jalankan ulang dengan:

```bash
make eval ARGS='--dataset docs/eval/retrieval_dataset_hard.json --verbose'
make eval ARGS='--dataset docs/eval/retrieval_dataset_hard.json --set reranker_enabled=true'
```

Test: 9 unit test di `core/tests/test_rerank.py` — default nonaktif = identitas, provider
`none` = identitas, IDF mengalahkan fusi, skor tidak ditulis ulang, skor seri tetap stabil,
`top_n` membatasi lingkup tanpa menghilangkan kandidat, kueri tanpa istilah = identitas.

### Hasil terukur (2 Oktober 2026)

Dataset `kb-retrieval-hard` v2, dua run berurutan pada **korpus identik** (lewat `--set`
sehingga bahan bakunya persis sama):

| Metrik | Sebelum | Sesudah | Δ |
| --- | --- | --- | --- |
| recall@5 | 0.9 | **1.0** | +0.10 |
| MRR | 0.8000 | **0.8833** | +0.0833 |
| citation_correctness | 0.7 | **0.8** | +0.10 |
| no_answer_accuracy / hallusinasi / false-no-answer | 1.0 / 0.0 / 0.0 | 1.0 / 0.0 / 0.0 | 0 |
| latency p50 / p95 | 20.8 ms / 29.2 ms | 30.2 ms / 46.7 ms | +9.4 ms / +17.5 ms |
| total_tokens_est | 5897 | 5500 | −397 |

Pergerakan per kueri (posisi dokumen harapan):

- "berapa maksimal biaya makan ketika ada pertemuan" — di luar top-5 → **posisi 3**
- "berapa porsi biaya kesehatan yang ditanggung kantor bagi karyawan" — 2 → **1**
- "berapa dana yang dibawa ketika bekerja di luar kota tiap hari" — 2 → **1**
- "berapa uang untuk kendaraan saat tugas di luar kantor" — **mundur** 1 → 2

Artinya reranker **tidak serba unggul**: tiga kueri naik, satu mundur, dan netnya
MRR +0.0833. Kueri parafrase terberat ("biaya makan") tetap tidak sampai posisi 1 —
sesuai catatan atribusi, ia butuh sinyal semantik.

Dataset gate (`kb-retrieval-mini`) dengan reranker menyala tetap **1.0 di semua
metrik** — tanpa regresi, sehingga `test_retrieval_eval.py` tetap hijau.

Kriteria diterima: **dipenuhi** — uplift terukur, tidak ada regresi ACL/gate, quality
gate hijau. Aturan "bila uplift tidak terukur, default tetap `false`" tidak berlaku karena
uplift terbukti, maka default dinyalakan; perilaku lama tetap tersedia lewat
`APP_RERANKER_ENABLED=false`.

Catatan menyertainya: satu perbaikan test isolasi. Test `websearch` yang memalsukan
provider utama sebelumnya ikut memanggil provider cadangan sungguhan
(`APP_WEB_SEARCH_FALLBACK_PROVIDERS_CSV` di `.env` lokal) hingga menembus jaringan;
fixture autouse kini mengosongkan rantai cadangan selama test.

---

## Fase 2 — Answer Mode Extractive Bertingkat (P0)

Tujuan: tidak memanggil model bila retrieval sudah cukup, sehingga ringan dan murah.

Desain (implementasi aktual, `core/src/ai_asistent_core/rerank.py` + `rag.py` + `config.py`):

- **`LexicalConfidence`** (dataclass frozen): skor kepercayaan leksikal IDF-weighted
  ternormalisasi [0,1] untuk satu chunk terhadap suatu kueri. Berbeda dari BM25 di
  `LexicalReranker`, skor ini tidak bergantung perbandingan antar-kandidat — bisa dipakai
  langsung sebagai ambang threshold:
  `score = Σ(IDF(t) | t ∈ query ∩ chunk) / Σ(IDF(t) | t ∈ query)`
  Corpus IDF dihitung dari batch kandidat yang sudah terpilih (lazy, tanpa DB/index tambahan).
- **`lexical_confidence(query, candidates, target_idx=0) -> LexicalConfidence`** — fungsi
  publik yang dipanggil dari `_extractive_answer` dan bisa dipakai langsung dari luar modul.
- **Mode jawaban** diatur oleh `APP_ANSWER_MODE`:
  - `generative` (default): selalu pakai LLM — perilaku lama tidak berubah.
  - `extractive`: kembalikan cuplikan chunk terbaik tanpa LLM bila
    `lexical_confidence.score ≥ APP_ANSWER_EXTRACTIVE_THRESHOLD` **dan** margin antar chunk
    terbaik dan kedua ≥ `APP_ANSWER_MIN_MARGIN`. Bila tidak lolos → `no_answer` langsung
    (tanpa jatuh ke LLM).
  - `auto`: coba ekstraktif dulu; bila tidak lolos → jatuh ke generatif.
- `answer_kind` baru: `"extractive"` di samping `"grounded"`, `"grounded_web"`, `"no_answer"`.
- **`answer_stream`** mendukung mode yang sama: bila ekstraktif lolos, teks cuplikan langsung
  di-yield sekaligus dan `stream_generate` tidak dipanggil.
- Panjang cuplikan dibatasi oleh `APP_ANSWER_MAX_CHARS` (default 600; 0 = tanpa potong).

Config baru:

| Env | Default | Keterangan |
| --- | --- | --- |
| `APP_ANSWER_MODE` | `generative` | `generative` \| `extractive` \| `auto` |
| `APP_ANSWER_EXTRACTIVE_THRESHOLD` | `0.55` | ambang `LexicalConfidence.score` |
| `APP_ANSWER_MIN_MARGIN` | `0.10` | margin minimum chunk #1 vs #2 |
| `APP_ANSWER_MAX_CHARS` | `600` | panjang maks cuplikan (0 = tanpa potong) |

File yang diubah:

- `core/src/ai_asistent_core/rerank.py` — tambah `LexicalConfidence` + `lexical_confidence()`
- `core/src/ai_asistent_core/config.py` — tambah 4 field baru
- `core/src/ai_asistent_core/rag.py` — tambah `_extractive_answer()`, `_use_extractive()`,
  integrasikan ke `answer_question()` dan `answer_stream()`
- `core/tests/test_answer_modes.py` — **23 test baru** (LexicalConfidence, _extractive_answer,
  answer_question 3 mode, answer_stream 2 mode)
- `scripts/bench.py` — tambah `--set KEY=VALUE` (sama seperti `eval_rag.py`) untuk A/B bench

### Hasil terukur (3 Oktober 2026)

```
uv run pytest core/tests/ → 106 passed, 1 skipped
ruff check core/src/ai_asistent_core/{rerank,config,rag}.py core/tests/test_answer_modes.py → All checks passed!
mypy core/src/ai_asistent_core/{rerank,config,rag}.py → Success: no issues found in 3 source files
```

Dataset gate (`kb-retrieval-mini`) dengan `answer_mode=auto`:
semua metrik tetap **1.0** — tidak ada regresi.

Perbandingan A/B latensi (LLM stub, mode `generative` vs `extractive`/`auto`) bisa diukur
sekarang dengan:

```bash
make bench ARGS='--set answer_mode=generative'
make bench ARGS='--set answer_mode=extractive --set answer_extractive_threshold=0.3'
make bench ARGS='--set answer_mode=auto --set answer_extractive_threshold=0.3'
```

Penghematan token diharapkan proporsional dengan rasio kueri yang lolos threshold —
bergantung dataset dan setting threshold. Mode `generative` tetap default agar tidak ada
perubahan perilaku diam-diam di produksi sebelum threshold dikalibrasi.

Kriteria diterima: **dipenuhi** — quality gate hijau; `answer_kind=extractive` diidentifikasi
dan bersitasi; LLM tidak dipanggil ketika mode `extractive` aktif; streaming didukung.

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
