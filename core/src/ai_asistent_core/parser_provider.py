"""Parser provider abstraction (Fase 6) — gateway for pluggable document parsers.

Separates format dispatch from parser selection. Default: BuiltinParser (existing
pypdf, python-docx, etc.). Optional: DoclingParser (heavy, torch-based layout analysis).

Design: ParserProvider protocol + factory. Docling guarded import (not installed by default).
"""

import logging
from typing import Protocol

from ai_asistent_core.parsers import ParsedDocument

logger = logging.getLogger("ai_asistent_core.parser_provider")


class ParserProvider(Protocol):
    """Kontrak provider parser dokumen (bytes → ParsedDocument)."""

    def parse(self, data: bytes, filename: str = "") -> ParsedDocument:
        """Parse dokumen.

        Args:
            data: File bytes
            filename: Nama file (untuk inferensi format)

        Returns:
            ParsedDocument dengan sections + locators
        """
        ...


class BuiltinParser:
    """Default parser provider: dispatch to existing parsers (pypdf, python-docx, etc).

    Wraps format-specific parsers di parsers.py module.
    """

    def parse(self, data: bytes, filename: str = "") -> ParsedDocument:
        """Parse dokumen menggunakan builtin parsers.

        Infers format dari filename atau content magic bytes, dispatches ke parser
        yang sesuai (PDF → PdfParser, DOCX → DocxParser, dll).

        Args:
            data: File bytes
            filename: Nama file (untuk format inference)

        Returns:
            ParsedDocument
        """
        from ai_asistent_core.parsers import (
            DocxParser,
            HtmlParser,
            MarkdownParser,
            PdfParser,
            PptxParser,
            TextParser,
            XlsxParser,
            CsvParser,
        )

        # Infer format dari filename extension
        format_hint = ""
        if filename:
            ext = filename.lower().split(".")[-1]
            format_hint = ext

        # Dispatch ke parser sesuai format
        if format_hint == "pdf":
            return PdfParser().parse(data)
        elif format_hint == "docx":
            return DocxParser().parse(data)
        elif format_hint == "pptx":
            return PptxParser().parse(data)
        elif format_hint == "xlsx":
            return XlsxParser().parse(data)
        elif format_hint in ("txt", "text"):
            return TextParser().parse(data)
        elif format_hint in ("md", "markdown"):
            return MarkdownParser().parse(data)
        elif format_hint == "csv":
            return CsvParser().parse(data)
        elif format_hint in ("html", "htm"):
            return HtmlParser().parse(data)

        # Fallback: try magic bytes detection
        if data.startswith(b"%PDF"):
            return PdfParser().parse(data)
        elif data.startswith(b"PK"):  # ZIP magic (docx, pptx, xlsx are ZIP)
            # Heuristic: check for docx/pptx/xlsx markers
            if b"word/" in data or b"document.xml" in data:
                return DocxParser().parse(data)
            elif b"ppt/" in data or b"presentation.xml" in data:
                return PptxParser().parse(data)
            elif b"xl/" in data or b"workbook.xml" in data:
                return XlsxParser().parse(data)

        # Last resort: treat as text
        logger.warning("Unknown format for %s, fallback to text parser", filename)
        return TextParser().parse(data)


class DoclingParserStub:
    """Stub for Docling parser (Fase 6 — not implemented in MVP).

    Docling provides better layout analysis (heading hierarchy, tables, columns).
    Heavy dependency (torch-based); only loaded if explicitly enabled.

    Activation:
    - Set APP_DOCUMENT_PARSER=docling in config
    - Install: pip install docling (not in default dependencies)
    - Fallback: if Docling fails or not installed, reverts to BuiltinParser

    Real implementation: call docling.document_converter, parse, map to ParsedDocument.
    """

    def parse(self, data: bytes, filename: str = "") -> ParsedDocument:
        """Parse using Docling (stub — not implemented).

        TODO: Implement when quality uplift is measured + Docling adoption decided.
        """
        logger.warning(
            "DoclingParser stub called; Fase 6 implementation pending. "
            "Falling back to BuiltinParser."
        )
        return BuiltinParser().parse(data, filename)


def get_parser_provider() -> ParserProvider:
    """Factory: return configured parser provider.

    Returns:
        ParserProvider instance (BuiltinParser or DoclingParser)

    Config:
        APP_DOCUMENT_PARSER: "builtin" (default) | "docling"
        APP_DOCUMENT_FALLBACK: fallback provider on error (future)
    """
    from ai_asistent_core.config import get_settings

    s = get_settings()
    provider_name = getattr(s, "document_parser", "builtin")

    if provider_name == "docling":
        logger.info("Using DoclingParser provider")
        return DoclingParserStub()  # TODO: replace with real implementation

    return BuiltinParser()
