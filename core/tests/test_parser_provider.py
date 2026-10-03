"""Test parser_provider.py — Fase 6 parser gateway (stub implementation).

Tests BuiltinParser dispatch + DoclingParserStub fallback.

Catatan: test PDF dihindari karena PdfParser membutuhkan file PDF valid lengkap
(magic bytes + struktur xref + %%EOF) yang sulit dibuat di unit test tanpa fixture
berat. Test cukup membuktikan dispatch, format inference, dan fallback via txt/md.
"""

import pytest

from ai_asistent_core.parser_provider import (
    BuiltinParser,
    DoclingParserStub,
    get_parser_provider,
)


class TestBuiltinParser:
    """BuiltinParser dispatch logic."""

    def test_parse_returns_parsed_document(self) -> None:
        """BuiltinParser.parse() returns ParsedDocument."""
        from ai_asistent_core.parsers import ParsedDocument

        data = b"Konten dokumen teks biasa."
        parser = BuiltinParser()
        doc = parser.parse(data, filename="test.txt")

        assert isinstance(doc, ParsedDocument)
        assert doc.source_format == "txt"
        assert isinstance(doc.sections, list)
        assert len(doc.sections) > 0

    def test_dispatch_by_extension_txt(self) -> None:
        """Detect TXT format from filename."""
        data = b"Hello, world!"
        parser = BuiltinParser()
        doc = parser.parse(data, filename="readme.txt")

        assert doc.source_format == "txt"

    def test_dispatch_by_extension_md(self) -> None:
        """Detect Markdown format from filename."""
        data = b"# Heading\n\nContent here."
        parser = BuiltinParser()
        doc = parser.parse(data, filename="README.md")

        assert doc.source_format == "md"

    def test_dispatch_fallback_to_text(self) -> None:
        """Unknown extension falls back to TextLikeParser."""
        data = b"Some arbitrary data"
        parser = BuiltinParser()
        doc = parser.parse(data, filename="unknown.xyz")

        # Unknown format → fallback to txt
        assert doc.source_format == "txt"
        assert isinstance(doc.sections, list)

    def test_parse_without_filename(self) -> None:
        """Parse works without filename (no magic bytes match → text fallback)."""
        data = b"Plain text content without extension"
        parser = BuiltinParser()
        doc = parser.parse(data)

        assert isinstance(doc.sections, list)

    def test_parse_csv(self) -> None:
        """Dispatch CSV format."""
        data = b"col1,col2\nval1,val2\n"
        parser = BuiltinParser()
        doc = parser.parse(data, filename="data.csv")

        assert doc.source_format == "csv"

    def test_parse_html(self) -> None:
        """Dispatch HTML format (treated as text-like)."""
        data = b"<html><body>Content</body></html>"
        parser = BuiltinParser()
        doc = parser.parse(data, filename="page.html")

        assert doc.source_format == "html"


class TestDoclingParserStub:
    """DoclingParserStub stub implementation."""

    def test_stub_returns_parsed_document(self) -> None:
        """Stub still returns ParsedDocument (via fallback to BuiltinParser)."""
        from ai_asistent_core.parsers import ParsedDocument

        data = b"Test document content"
        parser = DoclingParserStub()
        doc = parser.parse(data, filename="test.txt")

        assert isinstance(doc, ParsedDocument)
        assert doc.source_format == "txt"

    def test_stub_fallback_to_builtin(self, caplog: pytest.LogCaptureFixture) -> None:
        """Stub logs warning and falls back to BuiltinParser."""
        import logging

        with caplog.at_level(logging.WARNING, logger="ai_asistent_core.parser_provider"):
            data = b"Test content"
            parser = DoclingParserStub()
            parser.parse(data, filename="test.txt")

        # Log harus menyebut stub / fallback
        assert any(
            "stub" in record.message.lower() or "fallback" in record.message.lower()
            for record in caplog.records
        ), f"Expected stub/fallback warning, got: {caplog.text}"

    def test_stub_preserves_format_txt(self) -> None:
        """Stub fallback preserves source format (txt)."""
        parser = DoclingParserStub()
        doc = parser.parse(b"text content here", filename="test.txt")

        assert doc.source_format == "txt"


class TestGetParserProvider:
    """Factory function for parser provider."""

    def test_default_builtin_parser(self) -> None:
        """Default provider is BuiltinParser."""
        provider = get_parser_provider()
        assert isinstance(provider, BuiltinParser)

    def test_provider_implements_protocol(self) -> None:
        """Provider implements ParserProvider protocol."""
        provider = get_parser_provider()
        assert hasattr(provider, "parse")
        assert callable(provider.parse)

    def test_docling_provider_returns_stub(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """With APP_DOCUMENT_PARSER=docling, returns DoclingParserStub."""

        class MockSettings:
            document_parser = "docling"

        import ai_asistent_core.parser_provider as pp_module

        monkeypatch.setattr(pp_module, "get_settings", lambda: MockSettings())

        provider = get_parser_provider()
        assert isinstance(provider, DoclingParserStub)


class TestParserProviderIntegration:
    """Integration: provider used in pipeline."""

    def test_provider_parse_workflow(self) -> None:
        """End-to-end: get provider → parse → get sections."""
        provider = get_parser_provider()

        data = b"Line 1\nLine 2\nLine 3"
        doc = provider.parse(data, filename="test.txt")

        assert doc.source_format == "txt"
        assert len(doc.sections) > 0
        assert all(hasattr(s, "text") for s in doc.sections)
        assert all(hasattr(s, "locator_type") for s in doc.sections)

    def test_provider_protocol_compliance(self) -> None:
        """Provider matches ParserProvider protocol."""
        from ai_asistent_core.parsers import ParsedDocument

        provider = get_parser_provider()
        result = provider.parse(b"test content", filename="test.txt")
        assert isinstance(result, ParsedDocument)
