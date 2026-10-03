"""Test parser_provider.py — Fase 6 parser gateway (stub implementation).

Tests BuiltinParser dispatch + DoclingParserStub fallback.
Real Docling implementation tests defer until Fase 6 activated.
"""

import pytest

from ai_asistent_core.parser_provider import (
    BuiltinParser,
    DoclingParserStub,
    ParserProvider,
    get_parser_provider,
)


class TestBuiltinParser:
    """BuiltinParser dispatch logic."""

    def test_parse_returns_parsed_document(self) -> None:
        """BuiltinParser.parse() returns ParsedDocument."""
        from ai_asistent_core.parsers import ParsedDocument

        # Create minimal PDF for testing
        pdf_bytes = b"%PDF-1.4\n%dummy pdf content"
        parser = BuiltinParser()
        doc = parser.parse(pdf_bytes, filename="test.pdf")

        assert isinstance(doc, ParsedDocument)
        assert doc.source_format  # Has format
        assert isinstance(doc.sections, list)

    def test_dispatch_by_extension_pdf(self) -> None:
        """Detect PDF format from filename."""
        pdf_bytes = b"%PDF-1.4\n%dummy"
        parser = BuiltinParser()
        doc = parser.parse(pdf_bytes, filename="document.pdf")

        # Should use PdfParser
        assert doc.source_format == "pdf"

    def test_dispatch_by_extension_txt(self) -> None:
        """Detect TXT format from filename."""
        txt_bytes = b"Hello, world!"
        parser = BuiltinParser()
        doc = parser.parse(txt_bytes, filename="readme.txt")

        # Should use TextParser
        assert doc.source_format == "txt"

    def test_dispatch_fallback_to_text(self) -> None:
        """Unknown format falls back to TextParser."""
        data = b"Some arbitrary data"
        parser = BuiltinParser()
        doc = parser.parse(data, filename="unknown.xyz")

        # Should fallback to text
        assert doc.source_format == "txt"

    def test_magic_bytes_pdf(self) -> None:
        """Detect PDF by magic bytes."""
        pdf_bytes = b"%PDF-1.4\n%dummy"
        parser = BuiltinParser()
        doc = parser.parse(pdf_bytes, filename="")  # No filename

        # Should detect PDF magic bytes
        assert doc.source_format == "pdf"

    def test_parse_without_filename(self) -> None:
        """Parse works without filename (uses magic bytes)."""
        txt_bytes = b"Plain text content"
        parser = BuiltinParser()
        doc = parser.parse(txt_bytes)

        # Should still parse as text
        assert isinstance(doc.sections, list)


class TestDoclingParserStub:
    """DoclingParserStub stub implementation."""

    def test_stub_returns_parsed_document(self) -> None:
        """Stub still returns ParsedDocument (via fallback to BuiltinParser)."""
        from ai_asistent_core.parsers import ParsedDocument

        data = b"%PDF-1.4\n%dummy"
        parser = DoclingParserStub()
        doc = parser.parse(data, filename="test.pdf")

        assert isinstance(doc, ParsedDocument)

    def test_stub_fallback_to_builtin(self, caplog: pytest.LogCaptureFixture) -> None:
        """Stub logs warning and falls back to BuiltinParser."""
        data = b"Test content"
        parser = DoclingParserStub()
        doc = parser.parse(data, filename="test.txt")

        # Should log warning
        assert "fallback to BuiltinParser" in caplog.text

    def test_stub_preserves_format(self) -> None:
        """Stub fallback preserves source format."""
        pdf_bytes = b"%PDF-1.4\n%dummy"
        parser = DoclingParserStub()
        doc = parser.parse(pdf_bytes, filename="test.pdf")

        # Should be PDF format from fallback
        assert doc.source_format == "pdf"


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
        # Mock config
        class MockSettings:
            document_parser = "docling"

        import ai_asistent_core.parser_provider as pp_module

        original_get_settings = pp_module.get_settings

        def mock_get_settings():
            return MockSettings()

        monkeypatch.setattr(pp_module, "get_settings", mock_get_settings)

        provider = get_parser_provider()
        assert isinstance(provider, DoclingParserStub)


class TestParserProviderIntegration:
    """Integration: provider used in pipeline."""

    def test_provider_parse_workflow(self) -> None:
        """End-to-end: get provider → parse → get sections."""
        provider = get_parser_provider()

        # Parse simple text
        data = b"Line 1\nLine 2\nLine 3"
        doc = provider.parse(data, filename="test.txt")

        assert doc.source_format == "txt"
        assert len(doc.sections) > 0
        assert all(hasattr(s, "text") for s in doc.sections)
        assert all(hasattr(s, "locator_type") for s in doc.sections)

    def test_provider_protocol_compliance(self) -> None:
        """Provider matches ParserProvider protocol."""
        provider = get_parser_provider()

        # Protocol requires: parse(data: bytes, filename: str = "") -> ParsedDocument
        from ai_asistent_core.parsers import ParsedDocument

        result = provider.parse(b"test", filename="test.txt")
        assert isinstance(result, ParsedDocument)
