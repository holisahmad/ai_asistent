"""Chunking token-aware (Fase 5).

Estimasi token: ~4 karakter per token (cukup untuk MVP tanpa tokenizer
eksternal; dapat diganti tiktoken via adapter nanti). Chunk dirakit dari
section parser dengan overlap terukur dan locator asli dipertahankan.
"""

from dataclasses import dataclass

from ai_asistent_core.config import get_settings
from ai_asistent_core.parsers import Section


@dataclass(frozen=True)
class Chunk:
    """Chunk siap embed dengan locator asal."""

    content: str
    locator_type: str
    locator_start: int
    locator_end: int
    char_start: int
    char_end: int


def _estimate_tokens(text: str) -> int:
    """Estimasi jumlah token (~4 karakter/token)."""
    return max(1, len(text) // 4)


def chunk_sections(sections: list[Section]) -> list[Chunk]:
    """Gabungkan section menjadi chunk token-aware dengan overlap.

    - Target ukuran chunk: `chunk_target_tokens`.
    - Overlap antar chunk: `chunk_overlap_tokens`.
    - Locator chunk = locator section dominan (asal teks paling banyak).
    """
    s = get_settings()
    target_chars = s.chunk_target_tokens * 4
    overlap_chars = s.chunk_overlap_tokens * 4

    chunks: list[Chunk] = []
    buf: list[str] = []
    buf_len = 0
    buf_sources: list[Section] = []

    def flush() -> None:
        nonlocal buf, buf_len, buf_sources
        if not buf:
            return
        text = "\n\n".join(buf).strip()
        if text:
            dominant = max(set(buf_sources), key=buf_sources.count)
            char_start = 0
            chunks.append(
                Chunk(
                    content=text,
                    locator_type=dominant.locator_type,
                    locator_start=dominant.locator_start,
                    locator_end=dominant.locator_end,
                    char_start=char_start,
                    char_end=len(text),
                )
            )
        buf, buf_len, buf_sources = [], 0, []

    for section in sections:
        sec_len = _estimate_tokens(section.text) * 4
        if sec_len > target_chars:
            # Section besar: pecah per paragraf/kalimat kasar dengan overlap.
            flush()
            parts = section.text.split("\n")
            sub_buf: list[str] = []
            sub_len = 0
            for part in parts:
                part_len = len(part) + 1
                if sub_len + part_len > target_chars and sub_buf:
                    text = "\n".join(sub_buf).strip()
                    if text:
                        chunks.append(
                            Chunk(
                                content=text,
                                locator_type=section.locator_type,
                                locator_start=section.locator_start,
                                locator_end=section.locator_end,
                                char_start=0,
                                char_end=len(text),
                            )
                        )
                    overlap_parts: list[str] = []
                    overlap_total = 0
                    for p in reversed(sub_buf):
                        if overlap_total + len(p) > overlap_chars:
                            break
                        overlap_parts.insert(0, p)
                        overlap_total += len(p) + 1
                    sub_buf = overlap_parts
                    sub_len = overlap_total
                sub_buf.append(part)
                sub_len += part_len
            text = "\n".join(sub_buf).strip()
            if text:
                chunks.append(
                    Chunk(
                        content=text,
                        locator_type=section.locator_type,
                        locator_start=section.locator_start,
                        locator_end=section.locator_end,
                        char_start=0,
                        char_end=len(text),
                    )
                )
            continue

        if buf_len + sec_len > target_chars and buf:
            flush()
            overlap_text = "\n\n".join(buf).strip()[-overlap_chars:] if overlap_chars else ""
            if overlap_text:
                buf = [overlap_text]
                buf_len = len(overlap_text)
                buf_sources = list(buf_sources[-1:]) if buf_sources else []
            else:
                buf, buf_len, buf_sources = [], 0, []

        buf.append(section.text)
        buf_len += sec_len
        buf_sources.append(section)

    flush()
    return chunks
