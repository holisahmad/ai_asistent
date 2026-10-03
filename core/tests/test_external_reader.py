"""Test external_reader.py — Fase 5."""

import pytest
from datetime import datetime

from ai_asistent_core.external_reader import (
    ExternalDocument,
    HttpReader,
    _extract_title,
    _html_to_text,
    _parse_domain,
    get_external_reader,
)


class TestExternalDocument:
    """ExternalDocument dataclass validation."""

    def test_create_basic(self) -> None:
        doc = ExternalDocument(url="https://example.com")
        assert doc.url == "https://example.com"
        assert doc.source_type == "web"
        assert doc.content == ""

    def test_snippet_short(self) -> None:
        doc = ExternalDocument(url="https://example.com", content="Short text")
        snippet = doc.snippet(max_chars=100)
        assert snippet == "Short text"

    def test_snippet_truncate(self) -> None:
        doc = ExternalDocument(
            url="https://example.com",
            content="This is a very long text that should be truncated",
        )
        snippet = doc.snippet(max_chars=20)
        assert len(snippet) <= 22  # +2 for "…"
        assert snippet.endswith("…")

    def test_snippet_normalize_whitespace(self) -> None:
        doc = ExternalDocument(
            url="https://example.com",
            content="Text  with   multiple    spaces",
        )
        snippet = doc.snippet()
        assert "  " not in snippet


class TestParseDomain:
    """Extract domain from URL."""

    def test_basic_https(self) -> None:
        assert _parse_domain("https://example.com/path") == "example.com"

    def test_basic_http(self) -> None:
        assert _parse_domain("http://example.com") == "example.com"

    def test_with_port(self) -> None:
        assert _parse_domain("https://example.com:8443/path") == "example.com:8443"

    def test_with_subdomain(self) -> None:
        assert (
            _parse_domain("https://docs.github.com/en/rest")
            == "docs.github.com"
        )

    def test_invalid_url(self) -> None:
        assert _parse_domain("not a url") == ""

    def test_empty_string(self) -> None:
        assert _parse_domain("") == ""


class TestExtractTitle:
    """Extract title from HTML."""

    def test_title_tag(self) -> None:
        html = "<html><head><title>My Page</title></head></html>"
        assert _extract_title(html) == "My Page"

    def test_title_tag_with_attributes(self) -> None:
        html = '<html><head><title lang="en">My Page</title></head></html>'
        assert _extract_title(html) == "My Page"

    def test_title_with_whitespace(self) -> None:
        html = "<title>  Page Title  </title>"
        assert _extract_title(html) == "Page Title"

    def test_h1_fallback(self) -> None:
        html = "<html><body><h1>Welcome</h1></body></html>"
        assert _extract_title(html) == "Welcome"

    def test_title_preferred_over_h1(self) -> None:
        html = "<html><head><title>Title Tag</title></head><body><h1>H1 Tag</h1></body></html>"
        assert _extract_title(html) == "Title Tag"

    def test_no_title(self) -> None:
        html = "<html><body>No title here</body></html>"
        assert _extract_title(html) is None

    def test_case_insensitive(self) -> None:
        html = "<HTML><HEAD><TITLE>Case Test</TITLE></HEAD></HTML>"
        assert _extract_title(html) == "Case Test"


class TestHtmlToText:
    """Convert HTML to plain text."""

    def test_remove_script(self) -> None:
        html = "<html><script>alert('xss')</script><body>Text</body></html>"
        text = _html_to_text(html)
        assert "alert" not in text
        assert "Text" in text

    def test_remove_style(self) -> None:
        html = "<html><style>body { color: red; }</style><body>Text</body></html>"
        text = _html_to_text(html)
        assert "color:" not in text
        assert "Text" in text

    def test_remove_tags(self) -> None:
        html = "<p>Paragraph 1</p><p>Paragraph 2</p>"
        text = _html_to_text(html)
        assert "<p>" not in text
        assert "Paragraph 1" in text
        assert "Paragraph 2" in text

    def test_decode_entities(self) -> None:
        html = "<p>&amp; &lt; &gt; &quot;</p>"
        text = _html_to_text(html)
        assert "&" in text
        assert "<" in text
        assert ">" in text

    def test_normalize_whitespace(self) -> None:
        html = "<p>Text   with    multiple     spaces</p>"
        text = _html_to_text(html)
        assert "  " not in text
        assert text == "Text with multiple spaces"

    def test_empty_html(self) -> None:
        assert _html_to_text("") == ""

    def test_complex_html(self) -> None:
        html = """
        <html>
            <head><title>Title</title></head>
            <body>
                <h1>Header</h1>
                <p>This is <strong>bold</strong> text.</p>
                <script>console.log('hidden')</script>
            </body>
        </html>
        """
        text = _html_to_text(html)
        assert "Header" in text
        assert "bold" in text
        assert "hidden" not in text
        assert "console" not in text


class TestHttpReader:
    """HttpReader async integration (mock HTTP)."""

    @pytest.mark.asyncio
    async def test_read_success_mock(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Mock safe_fetch to simulate successful read."""

        def mock_safe_fetch(
            url: str, timeout: float = 8.0, max_bytes: int = 200_000
        ):
            html = "<html><head><title>Test Page</title></head><body>Test content</body></html>"
            return html, True, "OK"

        import ai_asistent_core.external_reader as er_module

        original = er_module.safe_fetch
        er_module.safe_fetch = mock_safe_fetch

        try:
            reader = HttpReader()
            doc = await reader.read("https://example.com")

            assert doc.url == "https://example.com"
            assert doc.title == "Test Page"
            assert "Test content" in doc.content
            assert doc.domain == "example.com"
            assert doc.source_type == "web"
            assert doc.retrieved_at  # ISO 8601 timestamp
        finally:
            er_module.safe_fetch = original

    @pytest.mark.asyncio
    async def test_read_failure_mock(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Mock safe_fetch to simulate SSRF/fetch failure."""

        def mock_safe_fetch(url: str, timeout: float = 8.0, max_bytes: int = 200_000):
            return "", False, "SSRF: Private IP"

        import ai_asistent_core.external_reader as er_module

        original = er_module.safe_fetch
        er_module.safe_fetch = mock_safe_fetch

        try:
            reader = HttpReader()
            doc = await reader.read("http://localhost:8000/admin")

            assert doc.url == "http://localhost:8000/admin"
            assert doc.content == ""  # Failed fetch
            assert doc.title is None
            assert doc.source_type == "web"
        finally:
            er_module.safe_fetch = original


class TestGetExternalReader:
    """Factory function for external reader."""

    def test_default_http_reader(self) -> None:
        reader = get_external_reader()
        assert isinstance(reader, HttpReader)

    def test_reader_protocol_compliance(self) -> None:
        """Reader implements ExternalReaderProtocol."""
        reader = get_external_reader()
        # Protocol requires read() method
        assert hasattr(reader, "read")
        assert callable(reader.read)
