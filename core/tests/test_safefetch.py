"""Test safefetch.py — Fase 4 SSRF protection."""

import pytest

from ai_asistent_core.safefetch import _is_private_ip, _validate_url, safe_fetch


class TestIsPrivateIP:
    """IP private/reserved detection."""

    def test_loopback_ipv4(self) -> None:
        assert _is_private_ip("127.0.0.1")
        assert _is_private_ip("127.1.2.3")

    def test_private_ipv4(self) -> None:
        assert _is_private_ip("10.0.0.1")
        assert _is_private_ip("172.16.0.1")
        assert _is_private_ip("192.168.1.1")

    def test_link_local_ipv4(self) -> None:
        assert _is_private_ip("169.254.1.1")

    def test_metadata_endpoint(self) -> None:
        assert _is_private_ip("169.254.169.254")

    def test_loopback_ipv6(self) -> None:
        assert _is_private_ip("::1")

    def test_ipv6_ula(self) -> None:
        assert _is_private_ip("fc00::1")
        assert _is_private_ip("fd00::1")

    def test_ipv6_link_local(self) -> None:
        assert _is_private_ip("fe80::1")

    def test_public_ip(self) -> None:
        assert not _is_private_ip("8.8.8.8")
        assert not _is_private_ip("1.1.1.1")


class TestValidateURL:
    """URL validation: scheme, hostname, SSRF check."""

    def test_valid_http_url(self) -> None:
        is_valid, reason = _validate_url("http://example.com/path")
        assert is_valid, reason

    def test_valid_https_url(self) -> None:
        is_valid, reason = _validate_url("https://example.com/path?query=1")
        assert is_valid, reason

    def test_reject_file_scheme(self) -> None:
        is_valid, reason = _validate_url("file:///etc/passwd")
        assert not is_valid
        assert "scheme" in reason.lower()

    def test_reject_data_scheme(self) -> None:
        is_valid, reason = _validate_url("data:text/html,<script>alert('xss')</script>")
        assert not is_valid
        assert "scheme" in reason.lower()

    def test_reject_ftp_scheme(self) -> None:
        is_valid, reason = _validate_url("ftp://example.com")
        assert not is_valid

    def test_reject_localhost_http(self) -> None:
        is_valid, reason = _validate_url("http://localhost/admin")
        assert not is_valid
        assert "private" in reason.lower() or "reserved" in reason.lower()

    def test_reject_localhost_numeric(self) -> None:
        is_valid, reason = _validate_url("http://127.0.0.1:8000")
        assert not is_valid

    def test_reject_private_10_range(self) -> None:
        is_valid, reason = _validate_url("http://10.0.0.1")
        assert not is_valid

    def test_reject_private_172_range(self) -> None:
        is_valid, reason = _validate_url("http://172.16.1.1")
        assert not is_valid

    def test_reject_private_192_range(self) -> None:
        is_valid, reason = _validate_url("http://192.168.1.1")
        assert not is_valid

    def test_reject_metadata_endpoint(self) -> None:
        is_valid, reason = _validate_url("http://169.254.169.254/latest/meta-data/iam/")
        assert not is_valid
        assert "metadata" in reason.lower() or "private" in reason.lower()

    def test_reject_no_hostname(self) -> None:
        is_valid, reason = _validate_url("http:///path")
        assert not is_valid
        assert "hostname" in reason.lower()

    def test_reject_invalid_scheme(self) -> None:
        is_valid, reason = _validate_url("gopher://example.com")
        assert not is_valid
        assert "scheme" in reason.lower()

    def test_reject_malformed_url(self) -> None:
        is_valid, reason = _validate_url("not a url at all")
        assert not is_valid

    # Note: DNS resolution tests are integration tests — skip in unit tests
    # or mock socket.getaddrinfo


class TestSafeFetchIntegration:
    """safe_fetch() integration tests (mocked HTTP)."""

    @pytest.mark.asyncio
    async def test_safe_fetch_public_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Fetch from public URL (mocked)."""
        # Mock httpx.get
        class MockResponse:
            status_code = 200
            content = b"<html>Test content</html>"
            text = "<html>Test content</html>"
            headers = {"content-type": "text/html; charset=utf-8"}
            url = "https://example.com"

        def mock_get(*args, **kwargs):
            return MockResponse()

        import httpx as httpx_module
        original_get = httpx_module.get
        httpx_module.get = mock_get

        try:
            content, success, reason = safe_fetch("https://example.com")
            assert success, reason
            assert "Test content" in content
        finally:
            httpx_module.get = original_get

    def test_safe_fetch_blocks_localhost(self) -> None:
        """safe_fetch rejects localhost without network call."""
        content, success, reason = safe_fetch("http://localhost:8000/admin")
        assert not success
        assert "private" in reason.lower() or "reserved" in reason.lower()

    def test_safe_fetch_blocks_127_0_0_1(self) -> None:
        """safe_fetch rejects 127.0.0.1 without network call."""
        content, success, reason = safe_fetch("http://127.0.0.1:8080/api")
        assert not success

    def test_safe_fetch_blocks_metadata(self) -> None:
        """safe_fetch rejects AWS metadata endpoint."""
        content, success, reason = safe_fetch("http://169.254.169.254/latest/")
        assert not success
        assert "metadata" in reason.lower() or "private" in reason.lower()

    def test_safe_fetch_blocks_file_scheme(self) -> None:
        """safe_fetch rejects file:// scheme."""
        content, success, reason = safe_fetch("file:///etc/passwd")
        assert not success
        assert "scheme" in reason.lower()

    def test_safe_fetch_timeout_parameter(self) -> None:
        """safe_fetch accepts timeout parameter."""
        # Akan timeout karena invalid URL, tapi tidak crash
        content, success, reason = safe_fetch(
            "http://localhost/", timeout=0.1
        )
        assert not success
