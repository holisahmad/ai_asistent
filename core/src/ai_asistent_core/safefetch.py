"""SSRF-safe fetch wrapper (Fase 4) — validasi URL sebelum fetch.

Mencegah SSRF (Server-Side Request Forgery) dengan:
- Whitelist skema (http/https saja)
- Resolve DNS, tolak IP private/loopback/metadata
- Validasi ulang setiap redirect
- Batas size/timeout/content-type
"""

import ipaddress
import logging
import re
from urllib.parse import urlparse

import httpx

logger = logging.getLogger("ai_asistent_core.safefetch")

# Private/reserved IP ranges (RFC 1918 + loopback + link-local + metadata).
_PRIVATE_RANGES = [
    ipaddress.ip_network("127.0.0.0/8"),      # loopback
    ipaddress.ip_network("10.0.0.0/8"),       # private
    ipaddress.ip_network("172.16.0.0/12"),    # private
    ipaddress.ip_network("192.168.0.0/16"),   # private
    ipaddress.ip_network("169.254.0.0/16"),   # link-local
    ipaddress.ip_network("::1/128"),          # IPv6 loopback
    ipaddress.ip_network("fc00::/7"),         # IPv6 ULA
    ipaddress.ip_network("fe80::/10"),        # IPv6 link-local
]

# EC2 metadata endpoint — always block.
_METADATA_IPS = {"169.254.169.254", "::ffff:169.254.169.254"}

_USER_AGENT = "ai-asistent-rag/0.1 (knowledge assistant; contact: admin@localhost)"


def _is_private_ip(ip_str: str) -> bool:
    """Check apakah IP adalah private/reserved."""
    try:
        ip = ipaddress.ip_address(ip_str)
        # Check metadata endpoint khusus
        if str(ip) in _METADATA_IPS:
            return True
        # Check private ranges
        return any(ip in net for net in _PRIVATE_RANGES)
    except ValueError:
        return False


def _validate_url(url: str) -> tuple[bool, str]:
    """Validasi URL sebelum fetch.

    Returns: (is_valid, reason)
    """
    try:
        parsed = urlparse(url)

        # 1) Skema whitelist
        if parsed.scheme not in ("http", "https"):
            return False, f"Unsupported scheme: {parsed.scheme}"

        # 2) Hostname required
        if not parsed.hostname:
            return False, "No hostname in URL"

        # 3) Cegah bypass: file://, data://, gopher://, etc.
        if re.match(r"^(file|data|gopher|ftp|rtsp|telnet|nntp)://", url.lower()):
            return False, "Blocked scheme (file/data/gopher/ftp/etc)"

        # 4) Resolve hostname ke IP, cek private
        try:
            import socket
            ips = socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80))
            if not ips:
                return False, f"Cannot resolve {parsed.hostname}"

            for family, socktype, proto, canonname, sockaddr in ips:
                ip_str = sockaddr[0]
                if _is_private_ip(ip_str):
                    return False, f"Private/reserved IP: {ip_str}"
        except socket.gaierror as e:
            return False, f"DNS resolution failed: {e}"

        return True, "OK"
    except Exception as e:
        return False, f"URL validation error: {e}"


def safe_fetch(
    url: str,
    timeout: float = 8.0,
    max_bytes: int = 200_000,
    allowed_content_types: list[str] | None = None,
) -> tuple[str, bool, str]:
    """Fetch URL dengan proteksi SSRF.

    Args:
        url: URL to fetch
        timeout: HTTP timeout (seconds)
        max_bytes: Max response size (bytes)
        allowed_content_types: Allowed MIME types (default: text/html, text/plain, application/json)

    Returns:
        (content: str, success: bool, reason: str)
    """
    if allowed_content_types is None:
        allowed_content_types = ["text/html", "text/plain", "application/json"]

    # 1) Validasi URL awal
    is_valid, reason = _validate_url(url)
    if not is_valid:
        logger.warning("SSRF check failed for url=%s: %s", url, reason)
        return "", False, reason

    try:
        # 2) HTTP GET dengan redirect handling
        resp = httpx.get(
            url,
            headers={"User-Agent": _USER_AGENT},
            timeout=timeout,
            follow_redirects=True,
            limits=httpx.Limits(max_redirects=5),  # Limit redirects
        )

        # 3) Validasi setiap redirect (httpx secara otomatis follow, tapi kita
        #    perlu cek final URL)
        final_parsed = urlparse(str(resp.url))
        is_valid_final, reason_final = _validate_url(str(resp.url))
        if not is_valid_final:
            logger.warning("SSRF check failed for redirect target=%s: %s", resp.url, reason_final)
            return "", False, f"Redirect to unsafe URL: {reason_final}"

        # 4) Status code OK
        if resp.status_code >= 400:
            return "", False, f"HTTP {resp.status_code}"

        # 5) Content-Type check
        content_type = resp.headers.get("content-type", "").lower().split(";")[0]
        if content_type and not any(ct in content_type for ct in allowed_content_types):
            logger.warning("Content-type blocked for url=%s: %s", url, content_type)
            return "", False, f"Blocked content-type: {content_type}"

        # 6) Size limit
        if len(resp.content) > max_bytes:
            logger.warning("Response too large for url=%s: %d bytes", url, len(resp.content))
            return "", False, f"Response too large: {len(resp.content)} bytes"

        return resp.text, True, "OK"

    except httpx.TimeoutException:
        logger.warning("Timeout fetching url=%s", url)
        return "", False, "HTTP timeout"
    except httpx.RedirectLoop:
        logger.warning("Redirect loop for url=%s", url)
        return "", False, "Redirect loop detected"
    except httpx.HTTPError as e:
        logger.warning("HTTP error for url=%s: %s", url, e)
        return "", False, f"HTTP error: {e}"
    except Exception as e:
        logger.warning("Unexpected error fetching url=%s: %s", url, e)
        return "", False, f"Unexpected error: {e}"
