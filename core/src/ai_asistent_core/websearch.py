"""Web search adapter + sanitizer + ACL domain + rate limit (Fase 7).

Prinsip roadmap: web search HANYA bila diizinkan dan bukti internal tidak
mencukupi; sumber eksternal selalu ditandai; domain allowlist/denylist;
timeout & rate limit; konten disanitasi sebelum masuk prompt LLM.
Provider dapat diganti: duckduckgo (tanpa API key), searx (self-host),
tavily (API key). `provider none` → web fallback mati total.
"""

import html as html_mod
import json
import logging
import re
import time
from collections import deque
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import parse_qs, urlparse

import httpx

from ai_asistent_core.config import csv_list, get_settings

logger = logging.getLogger("ai_asistent_core.websearch")

_USER_AGENT = "ai-asistent-rag/0.1 (knowledge assistant; contact: admin@localhost)"


@dataclass(frozen=True)
class WebResult:
    """Satu hasil pencarian web (akan jadi citation source_type=web)."""

    title: str
    url: str
    snippet: str


class WebSearchProvider(Protocol):
    """Kontrak provider pencarian web."""

    def search(self, query: str, max_results: int) -> list[WebResult]: ...


def _http_get(url: str, timeout: float) -> httpx.Response:
    return httpx.get(
        url,
        headers={"User-Agent": _USER_AGENT},
        timeout=timeout,
        follow_redirects=True,
    )


def _clean_inline_html(raw: str) -> str:
    """Bersihkan teks dalam tag HTML (entity + tag sisa + whitespace)."""
    return re.sub(r"\s+", " ", html_mod.unescape(re.sub(r"<[^>]+>", "", raw))).strip()


def parse_ddg_html(page: str, max_results: int) -> list[WebResult]:
    """Parse halaman HTML lite DDG menjadi hasil (murni, mudah diuji).

    Snippet ikut diambil: sering jadi satu-satunya konteks yang bisa
    dipakai bila halaman asli memblokir fetch (403/robots).
    """
    links = re.findall(
        r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', page, flags=re.S
    )
    snippets = [
        _clean_inline_html(s)
        for s in re.findall(r'class="result__snippet"[^>]*>(.*?)</a>', page, flags=re.S)
    ]

    results: list[WebResult] = []
    for i, (href, raw_title) in enumerate(links):
        if len(results) >= max_results:
            break
        href = html_mod.unescape(href)
        # DDG membungkus URL asli dalam redirect /l/?uddg=<encoded>
        if "uddg=" in href:
            try:
                qs = parse_qs(urlparse(href).query)
                href = qs.get("uddg", [href])[0]
            except ValueError:  # pragma: no cover - malformed
                pass
        if href.startswith("//"):
            href = "https:" + href
        if not href.startswith("http"):
            continue
        results.append(
            WebResult(
                title=_clean_inline_html(raw_title),
                url=href,
                snippet=snippets[i] if i < len(snippets) else "",
            )
        )
    return results


class DuckDuckGoSearch:
    """Scraping HTML lite DDG (html.duckduckgo.com/html) — tanpa API key.

    Cukup stabil untuk MVP; parsing regex, tanpa dependensi BeautifulSoup.
    """

    def search(self, query: str, max_results: int) -> list[WebResult]:
        resp = httpx.get(
            "https://html.duckduckgo.com/html/",
            params={"q": query},
            headers={"User-Agent": _USER_AGENT},
            timeout=get_settings().web_search_timeout_seconds,
            follow_redirects=True,
        )
        resp.raise_for_status()
        return parse_ddg_html(resp.text, max_results)


def parse_searx_json(data: object, max_results: int) -> list[WebResult]:
    """Parse respons JSON SearXNG/Tavily (bentuk hasil sama: results[])."""
    if not isinstance(data, dict):
        return []
    items = data.get("results", [])
    if not isinstance(items, list):
        return []
    out: list[WebResult] = []
    for item in items[:max_results]:
        if not isinstance(item, dict):
            continue
        out.append(
            WebResult(
                title=str(item.get("title", "")),
                url=str(item.get("url", "")),
                snippet=str(item.get("content", "")),
            )
        )
    return out


class SearxSearch:
    """SearXNG self-host dengan output JSON (?format=json)."""

    def __init__(self, base_url: str) -> None:
        self._base_url = base_url.rstrip("/")

    def search(self, query: str, max_results: int) -> list[WebResult]:
        resp = httpx.get(
            f"{self._base_url}/search",
            params={"q": query, "format": "json"},
            headers={"User-Agent": _USER_AGENT},
            timeout=get_settings().web_search_timeout_seconds,
        )
        resp.raise_for_status()
        return parse_searx_json(resp.json(), max_results)


class TavilySearch:
    """Tavily API (api.tavily.com) — butuh APP_TAVILY_API_KEY."""

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    def search(self, query: str, max_results: int) -> list[WebResult]:
        resp = httpx.post(
            "https://api.tavily.com/search",
            json={"api_key": self._api_key, "query": query, "max_results": max_results},
            timeout=get_settings().web_search_timeout_seconds,
        )
        resp.raise_for_status()
        return parse_searx_json(resp.json(), max_results)


# --- ACL domain ---------------------------------------------------------------


def registrable_domain(url: str) -> str:
    """Domain pembanding sederhana (dua label terakhir; host penuh bila IP/localhost)."""
    host = urlparse(url).hostname or ""
    host = host.lower().rstrip(".")
    if not host or host.replace(".", "").isdigit() or "localhost" in host:
        return host
    parts = host.split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def _host_matches(host: str, domain: str) -> bool:
    """Cocokkan host dengan entri ACL: sama persis atau subdomain-nya."""
    return host == domain or host.endswith("." + domain)


def domain_allowed(url: str, allowlist: list[str], denylist: list[str]) -> bool:
    """Denylist menang atas allowlist; allowlist kosong = semua diizinkan.

    Dicocokkan pada hostname penuh (bukan domain registrable) agar
    `deny: bad.example.com` tetap memblokir subdomainnya walau
    `allow: example.com` diberikan.
    """
    host = (urlparse(url).hostname or "").lower().rstrip(".")
    if not host:
        return False
    if any(_host_matches(host, d) for d in denylist):
        return False
    if not allowlist:
        return True
    return any(_host_matches(host, d) for d in allowlist)


# --- Rate limit (sliding window per proses) -----------------------------------

_rate_window: deque[float] = deque()


def rate_limit_allow() -> bool:
    """True bila permintaan web masih di bawah `web_search_rate_limit_per_min`."""
    s = get_settings()
    now = time.monotonic()
    while _rate_window and now - _rate_window[0] > 60.0:
        _rate_window.popleft()
    if len(_rate_window) >= max(1, s.web_search_rate_limit_per_min):
        return False
    _rate_window.append(now)
    return True


def reset_rate_limit() -> None:
    """Reset window (untuk test)."""
    _rate_window.clear()


# --- Sanitasi konten ----------------------------------------------------------

_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\u200b\u200c\u200d\ufeff]")


def sanitize_text(text: str, max_chars: int = 1200) -> str:
    """Bersihkan teks web sebelum masuk prompt: kontrol/zero-width char,
    HTML entity, whitespace runtuh, panjang dibatasi."""
    text = re.sub(r"<[^>]+>", " ", text)  # buang tag HTML sisa
    text = html_mod.unescape(text)
    text = _CTRL_RE.sub("", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > max_chars:
        text = text[:max_chars].rstrip() + "…"
    return text


def fetch_page_text(url: str, max_bytes: int = 200_000) -> str:
    """Ambil HTML halaman & ekstrak teks kasar (tanpa JS). Gagal → string kosong."""
    try:
        resp = _http_get(url, get_settings().web_search_timeout_seconds)
        resp.raise_for_status()
        raw = resp.content[:max_bytes]
        page = raw.decode(resp.encoding or "utf-8", errors="replace")
        page = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", page, flags=re.S | re.I)
        page = re.sub(r"<[^>]+>", " ", page)
        return sanitize_text(page, max_chars=4000)
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("fetch_page_text gagal url=%s: %s", url, exc)
        return ""


# --- Facade -------------------------------------------------------------------


def get_web_search_provider() -> WebSearchProvider | None:
    """Provider dari settings; None bila web search dimatikan."""
    s = get_settings()
    if s.web_search_provider == "duckduckgo":
        return DuckDuckGoSearch()
    if s.web_search_provider == "searx":
        if not s.web_search_base_url:
            raise RuntimeError("APP_WEB_SEARCH_BASE_URL belum diset untuk searx")
        return SearxSearch(s.web_search_base_url)
    if s.web_search_provider == "tavily":
        if not s.tavily_api_key:
            raise RuntimeError("APP_TAVILY_API_KEY belum diset")
        return TavilySearch(s.tavily_api_key)
    return None


def web_search(
    query: str, *, audit: list[dict[str, object]] | None = None
) -> list[WebResult]:
    """Cari web dengan rate limit + ACL domain + sanitasi snippet.

    `audit` (opsional) diisi catatan hasil yang ditolak ACL agar percobaan
    tetap terekam untuk review keamanan (roadmap Fase 9).
    Melempar RuntimeError bila rate limit terlampaui; error provider
    dibiarkan naik (pemanggil memutuskan degrade).
    """
    s = get_settings()
    if not rate_limit_allow():
        raise RuntimeError("Web search rate limit terlampaui")
    provider = get_web_search_provider()
    if provider is None:
        return []
    raw = provider.search(query, s.web_search_max_results)
    allow = csv_list(s.web_search_domain_allowlist_csv)
    deny = csv_list(s.web_search_domain_denylist_csv)
    results: list[WebResult] = []
    for r in raw:
        if not domain_allowed(r.url, allow, deny):
            if audit is not None:
                audit.append({"url": r.url, "rejected": "domain_acl"})
            continue
        results.append(
            WebResult(
                title=sanitize_text(r.title, 200),
                url=r.url,
                snippet=sanitize_text(r.snippet),
            )
        )
    return results


def to_json(data: object) -> str:
    """Helper kecil (dipakai test & logging)."""
    return json.dumps(data, ensure_ascii=False)
