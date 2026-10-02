"""Reranker retrieval (Fase 1 upgrade plan) — penyusunan ulang kandidat.

Posisi kandidat keluaran fusi (`retrieval.py`) saat ini ditentukan gabungan
cosine hashing + RRF. Keduanya **tidak punya IDF**, sehingga kata umum
(kerja, tahun, hari, biaya) ikut menaikkan dokumen yang salah sementara
dokumen target justru kalah karena panjangnya. `LexicalReranker` menghitung
skor ulang dengan pola BM25 (IDF + saturasi tf + normalisasi panjang) lalu
menggabungkannya dengan skor fusi, sehingga:

- istilah jarah di dalam kueri diberi bobot besar;
- dokumen pendek yang menumpuk kata umum tidak lagi menang otomatis;
- skor fusi tetap ikut supaya tidak ada regresi saat sinyal leksikal seri.

Desain:

- **Deterministik.** Tanpa model, tanpa dependency baru, tanpa jaringan.
- **Provider-neutral.** `RerankerProtocol` mengikuti pola adapter lain
  (`Parser`, `EmbeddingProvider`, `LLMProvider`); adapter hosted dapat
  ditambahkan tanpa menyentuh orkestrasi retrieval.
- **Tidak merusak ACL.** Reranker hanya bekerja pada kandidat yang sudah
  lolos filter `workspace_id` di level SQL.
- **Netral terhadap tipe.** `score` pada kandidat TIDAK diubah — ia tetap
  skor fusi retrieval; reranker hanya mengubah urutan.
"""

import math
from collections.abc import Sequence
from typing import Protocol, TypeVar

from ai_asistent_core.config import get_settings
from ai_asistent_core.embeddings import content_tokens

# Parameter BM25 (nilai umum; deterministik).
K1 = 1.2  # saturasi term frequency
B = 0.75  # kekuatan normalisasi panjang dokumen
TITLE_BONUS = 1.5  # pengali untuk istilah yang muncul di judul/filename

# Bobot penggabungan (di-reset per pemanggilan berdasarkan skor relatif).
WEIGHT_BM25 = 0.7
WEIGHT_FUSION = 0.3


class Rankable(Protocol):
    """Kandidat retrieval yang bisa diurutkan ulang (read-only agar cocok
    dengan dataclass frozen milik retrieval)."""

    @property
    def chunk_id(self) -> str: ...

    @property
    def filename(self) -> str: ...

    @property
    def content(self) -> str: ...

    @property
    def score(self) -> float: ...


T = TypeVar("T", bound=Rankable)


class RerankerProtocol(Protocol):
    """Kontrak reranker: kandidat terfusi → urutan terbaik."""

    def rerank(self, query: str, candidates: Sequence[T]) -> list[T]: ...


def _unique(tokens: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for t in tokens:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


def _title_tokens(content: str, filename: str) -> set[str]:
    """Token judul (baris heading pertama) + nama berkas tanpa ekstensi."""
    heading = ""
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            heading = stripped.lstrip("#").strip()
            break
    stem = filename.rsplit(".", 1)[0] if "." in filename else filename
    return set(content_tokens(f"{stem} {heading}"))


class NoReranker:
    """Reranker identitas (provider `none`) — mengembalikan urutan apa adanya."""

    def rerank(self, query: str, candidates: Sequence[T]) -> list[T]:
        return list(candidates)


class LexicalReranker:
    """Reranker leksikal deterministik: BM25 + sinyal judul, digabung skor fusi."""

    def rerank(self, query: str, candidates: Sequence[T]) -> list[T]:
        items = list(candidates)
        if len(items) < 2:
            return items

        terms = _unique(content_tokens(query))
        if not terms:
            return items

        token_lists = [content_tokens(c.content) for c in items]
        titles = [_title_tokens(c.content, c.filename) for c in items]
        lengths = [len(t) for t in token_lists]
        avg_len = (sum(lengths) / len(lengths)) or 1.0
        n = len(items)

        bm25 = [0.0] * n
        for term in terms:
            tfs = [toks.count(term) for toks in token_lists]
            df = sum(1 for tf in tfs if tf)
            if df == 0:
                continue
            # IDF BM25; selalu positif agar istilah yang ada di semua kandidat
            # tetap memberi sinyal kecil, bukan menyetir skor.
            idf = math.log(1.0 + (n - df + 0.5) / (df + 0.5))
            for i, tf in enumerate(tfs):
                if tf == 0:
                    continue
                norm = K1 * (1.0 - B + B * lengths[i] / avg_len)
                bm25[i] += idf * (tf * (K1 + 1.0)) / (tf + norm)
                if term in titles[i]:
                    bm25[i] += idf * (TITLE_BONUS - 1.0)

        fusion = [c.score for c in items]
        bmax = max(bm25)
        fmax = max(fusion)

        scored: list[tuple[float, int]] = []
        for i in range(n):
            b = bm25[i] / bmax if bmax > 0 else 0.0
            f = fusion[i] / fmax if fmax > 0 else 0.0
            if bmax > 0 and fmax > 0:
                final = WEIGHT_BM25 * b + WEIGHT_FUSION * f
            elif bmax > 0:
                final = b
            else:
                final = f
            scored.append((final, i))

        # Skor seri → urutan asli dipertahankan (sort Python stabil), sehingga
        # reranker tidak pernah menggeser kandidat tanpa alasan skor.
        scored.sort(key=lambda pair: -pair[0])
        return [items[i] for _, i in scored]


def get_reranker() -> RerankerProtocol:
    """Reranker dari settings."""
    s = get_settings()
    if s.reranker_provider == "lexical":
        return LexicalReranker()
    return NoReranker()


def rerank_candidates[T: Rankable](query: str, candidates: list[T]) -> list[T]:
    """Terapkan reranker sesuai konfigurasi (enabled / provider / top_n).

    `reranker_top_n` membatasi jumlah kandidat depan yang ikut diurutkan ulang;
    sisanya menempel di belakang sehingga pengaturan ini tidak pernah
    menghilangkan kandidat.
    """
    s = get_settings()
    if not s.reranker_enabled or len(candidates) < 2:
        return candidates
    if s.reranker_provider == "none":
        return candidates
    reranker = get_reranker()
    top_n = s.reranker_top_n
    if top_n and top_n > 0 and top_n < len(candidates):
        head = reranker.rerank(query, candidates[:top_n])
        return [*head, *candidates[top_n:]]
    return reranker.rerank(query, candidates)
