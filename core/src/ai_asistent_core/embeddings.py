"""Embedding adapter (Fase 5) — provider dapat diganti.

- `local`: feature hashing bag-of-words deterministik (blake2b per token →
  bucket) — tanpa API, cocok untuk dev/test & jalur offline. Teks yang
  berbagi kata memiliki cosine similarity tinggi, sehingga ranking &
  threshold retrieval tetap bermakna (bukan semantik penuh; produksi cukup
  set `APP_EMBEDDING_PROVIDER=openai`).
- `openai`: text-embedding-3-small (butuh APP_OPENAI_API_KEY).

Interface `EmbeddingProvider` memungkinkan menambah Anthropic/Gemini/
model lokal (Ollama) tanpa mengubah pemanggil.
"""

import hashlib
import math
import re
from typing import Protocol

from ai_asistent_core.config import get_settings

_TOKEN_RE = re.compile(r"[a-z0-9]+")

# Kata fungsi umum (Indonesia + Inggris) yang tidak membawa sinyal retrieval.
# Tanpa ini, kata seperti "yang"/"dan"/"adalah" membuat dokumen tak relevan
# tetap tampak cocok (false positive) pada embedding bag-of-words maupun
# heuristik LLM lokal.
_STOPWORDS = frozenset(
    {
        # Indonesia
        "ada", "adalah", "agar", "akan", "anda", "atau", "bagi", "bahwa",
        "bila", "bisa", "dalam", "dan", "dapat", "dari", "dengan", "di",
        "dia", "ini", "itu", "jika", "juga", "karena", "ke", "lagi", "maka",
        "maupun", "memang", "namun", "oleh", "pada", "para", "per", "secara",
        "sebagai", "sebuah", "sedang", "seperti", "serta", "setelah", "sudah",
        "supaya", "telah", "tentang", "tersebut", "terhadap", "untuk", "yaitu",
        "yang",
        # Inggris
        "an", "and", "are", "as", "at", "be", "but", "by", "for", "from",
        "has", "have", "in", "into", "is", "it", "its", "of", "on", "or",
        "that", "the", "their", "then", "there", "these", "this", "to", "was",
        "were", "which", "will", "with",
    }
)


def _tokens(text: str) -> list[str]:
    """Tokenisasi sederhana: huruf/angka lowercase, panjang >= 2."""
    return [t for t in _TOKEN_RE.findall(text.lower()) if len(t) >= 2]


def content_tokens(text: str) -> list[str]:
    """Token bermakna: tokenisasi biasa tanpa stopword fungsi umum (ID+EN).

    Dipakai bersama oleh embedding lokal dan heuristik LLM stub agar kata
    fungsi tidak dianggap bukti relevansi.
    """
    return [t for t in _tokens(text) if t not in _STOPWORDS]


def _bucket(token: str, dim: int) -> int:
    """Index bucket deterministik dari token via blake2b."""
    digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big") % dim


class EmbeddingProvider(Protocol):
    """Kontrak provider embedding."""

    dim: int

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class LocalHashEmbedding:
    """Bag-of-words feature hashing — deterministik & shared-token aware.

    Setiap token di-hash ke satu bucket (frekuensi diakumulasi), lalu
    vektor dinormalisasi L2. Dua teks yang berbagi kata → cosine tinggi.
    """

    def __init__(self, dim: int) -> None:
        self.dim = dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in texts:
            raw = [0.0] * self.dim
            for token in content_tokens(text):
                raw[_bucket(token, self.dim)] += 1.0
            norm = math.sqrt(sum(v * v for v in raw)) or 1.0
            vectors.append([v / norm for v in raw])
        return vectors


class OpenAIEmbedding:
    """Embedding via OpenAI API."""

    def __init__(self, api_key: str, model: str, dim: int) -> None:
        try:
            import httpx  # noqa: F401 - dipakai via openai client
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError("pip install openai untuk provider openai") from exc
        self._client = OpenAI(api_key=api_key)
        self._model = model
        self.dim = dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        resp = self._client.embeddings.create(model=self._model, input=texts)
        data = sorted(resp.data, key=lambda d: d.index)
        return [d.embedding for d in data]


def get_embedding_provider() -> EmbeddingProvider:
    """Pilih provider dari settings (embedding_provider: local|openai)."""
    s = get_settings()
    if s.embedding_provider == "openai":
        if not s.openai_api_key:
            raise RuntimeError("APP_OPENAI_API_KEY belum diset")
        return OpenAIEmbedding(s.openai_api_key, s.openai_embedding_model, s.embedding_dim)
    return LocalHashEmbedding(s.embedding_dim)


def embed_batch(texts: list[str]) -> list[list[float]]:
    """Embed dalam batch sesuai `embedding_batch_size`."""
    s = get_settings()
    provider = get_embedding_provider()
    out: list[list[float]] = []
    for i in range(0, len(texts), s.embedding_batch_size):
        out.extend(provider.embed(texts[i : i + s.embedding_batch_size]))
    return out
