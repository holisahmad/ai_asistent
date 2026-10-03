"""External reader adapter (Fase 5) — provider-neutral URL-to-content abstraction.

Separates "search" (websearch.py) from "read" (this module). Default HttpReader
uses safefetch (Fase 4). Future providers (Firecrawl, Jina) slot in behind protocol.

Enriches provenance: url, title, domain, retrieved_at — always source_type=web,
never mixed with internal citations.
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from urllib.parse import urlparse

from ai_asistent_core.safefetch import safe_fetch

logger = logging.getLogger("ai_asistent_core.external_reader")


@dataclass(frozen=True)
class ExternalDocument:
    """Dokumen eksternal dengan provenance kaya."""

    url: str  # URL asli
    title: str | None = None  # HTML title tag atau hasil ekstraksi
    content: str = ""  # Teks halaman (bersih, tanpa HTML)
    domain: str = ""  # Parsed domain dari URL
    retrieved_at: str = ""  # ISO 8601 timestamp saat fetch
    content_type: str = "text/html"  # MIME type dari response
    source_type: str = "web"  # Always "web" untuk external

    def snippet(self, max_chars: int = 280) -> str:
        """Potongan awal konten untuk sitasi."""
        flat = " ".join(self.content.split())
        if len(flat) <= max_chars:
            return flat
        return flat[:max_chars].rstrip() + "…"


class ExternalReaderProtocol(Protocol):
    """Kontrak provider pembaca eksternal (URL → content)."""

    async def read(self, url: str) -> ExternalDocument:
        """Baca URL dan kembalikan dokumen eksternal dengan provenance.

        Args:
            url: URL untuk dibaca

        Returns:
            ExternalDocument dengan content, metadata, provenance
        """
        ...


class HttpReader:
    """Default external reader: HTTP GET via safefetch (Fase 4 SSRF protection)."""

    async def read(
        self, url: str, timeout: float = 8.0, max_bytes: int = 200_000
    ) -> ExternalDocument:
        """Fetch URL, parse title, extract text.

        Args:
            url: URL untuk dibaca
            timeout: HTTP timeout (seconds)
            max_bytes: Max response size (bytes)

        Returns:
            ExternalDocument dengan content, title, domain, timestamp
        """
        # 1) Safe fetch dengan SSRF protection
        content, success, reason = safe_fetch(
            url, timeout=timeout, max_bytes=max_bytes
        )

        if not success:
            logger.warning("HttpReader fetch gagal untuk url=%s: %s", url, reason)
            return ExternalDocument(
                url=url,
                title=None,
                content="",
                domain=_parse_domain(url),
                retrieved_at=datetime.utcnow().isoformat() + "Z",
                source_type="web",
            )

        # 2) Ekstrak title dari HTML
        title = _extract_title(content) if content else None

        # 3) Bersihkan HTML → teks
        text = _html_to_text(content) if content else ""

        return ExternalDocument(
            url=url,
            title=title,
            content=text,
            domain=_parse_domain(url),
            retrieved_at=datetime.utcnow().isoformat() + "Z",
            content_type="text/html",
            source_type="web",
        )


def _parse_domain(url: str) -> str:
    """Ekstrak domain dari URL."""
    try:
        parsed = urlparse(url)
        return parsed.netloc or ""
    except Exception:
        return ""


def _extract_title(html: str) -> str | None:
    """Ekstrak title dari tag <title> atau <h1>."""
    import re

    # Coba <title>
    match = re.search(r"<title[^>]*>([^<]+)</title>", html, re.IGNORECASE | re.DOTALL)
    if match:
        return match.group(1).strip()

    # Fallback: <h1>
    match = re.search(r"<h1[^>]*>([^<]+)</h1>", html, re.IGNORECASE)
    if match:
        return match.group(1).strip()

    return None


def _html_to_text(html: str) -> str:
    """Convert HTML ke plain text: buang script/style, tag, normalize whitespace."""
    import re

    # Buang script dan style tags + isinya
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)

    # Buang semua HTML tags
    text = re.sub(r"<[^>]+>", " ", text)

    # Decode HTML entities
    import html as html_mod

    text = html_mod.unescape(text)

    # Normalize whitespace
    text = re.sub(r"\s+", " ", text).strip()

    return text


def get_external_reader() -> ExternalReaderProtocol:
    """Factory: return configured external reader provider."""
    from ai_asistent_core.config import get_settings

    s = get_settings()
    provider_name = getattr(s, "web_reader", "http")  # Default: http

    # Future: switch(provider_name) untuk Firecrawl/Jina adapters
    if provider_name == "http":
        return HttpReader()

    # Fallback ke HTTP jika provider tidak dikenal
    logger.warning("Unknown web_reader provider: %s, fallback to http", provider_name)
    return HttpReader()
