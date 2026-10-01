"""Embedding adapter (Fase 5) — provider dapat diganti.

- `local`: hash deterministik (blake2b → vektor unit) — tanpa API, cocok
  untuk dev/test & jalur offline; kualitas semantik terbatas.
- `openai`: text-embedding-3-small (butuh APP_OPENAI_API_KEY).

Interface `EmbeddingProvider` memungkinkan menambah Anthropic/Gemini/
model lokal (Ollama) tanpa mengubah pemanggil.
"""

import hashlib
import math
from typing import Protocol

from ai_asistent_core.config import get_settings


class EmbeddingProvider(Protocol):
    """Kontrak provider embedding."""

    dim: int

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class LocalHashEmbedding:
    """Embedding deterministik berbasis hash — untuk dev/test."""

    def __init__(self, dim: int) -> None:
        self.dim = dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in texts:
            digest = hashlib.blake2b(text.encode("utf-8"), digest_size=64).digest()
            raw = [digest[i % len(digest)] / 255.0 for i in range(self.dim)]
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
