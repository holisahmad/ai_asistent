"""Web search adapter + sanitizer + ACL domain + rate limit (Fase 7).

Prinsip roadmap: web search HANYA bila diizinkan dan bukti internal tidak
mencukupi; sumber eksternal selalu ditandai; domain allowlist/denylist;
timeout & rate limit; konten disanitasi sebelum masuk prompt LLM.
Provider dapat diganti: bing_rss (tanpa API key, rekomendasi), duckduckgo,
searx (self-host), tavily (API key). `provider none` → web fallback mati total.
"""

import html as html_mod
import json
import logging
import re
import time
import unicodedata
from collections import deque
from dataclasses import dataclass
from functools import partial
from typing import Protocol
from urllib.parse import parse_qs, urlparse
from xml.etree import ElementTree as ET

import httpx

from ai_asistent_core.config import CoreSettings, csv_list, get_settings
from ai_asistent_core.resilience import RetryPolicy, call_with_retry, get_breaker

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


_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\u200b\u200c\u200d\ufeff]")
_QUOTE_CHARS = "\"'“”‘’«»"
_WORD_RE = re.compile(r"[a-z0-9]+")
# Kata fungsi yang tidak menambah sinyal relevansi (ID + Inggris).
_STOPWORDS = frozenset(
    {
        "apa", "siapa", "kapan", "dimana", "mana", "bagaimana", "mengapa", "kenapa",
        "di", "ke", "dari", "yang", "dan", "atau", "itu", "ini", "adalah", "akan",
        "untuk", "dengan", "pada", "dalam", "tentang", "sebuah", "para", "juga",
        "the", "a", "an", "of", "to", "is", "are", "how", "what", "why", "when",
        "where", "which", "and", "or", "for", "with", "about",
    }
)


def _clean_inline_html(raw: str) -> str:
    """Bersihkan teks dalam tag HTML (entity + tag sisa + whitespace)."""
    return re.sub(r"\s+", " ", html_mod.unescape(re.sub(r"<[^>]+>", "", raw))).strip()


def normalize_query(query: str, max_chars: int = 300) -> str:
    """Rapikan kueri sebelum dikirim ke mesin pencari (fokus kueri ID dari chat).

    Chat pengguna sering menghasilkan kueri mentah: kutip copy-paste, tanda
    tanya berlebih, spasi/zero-width liar, atau karakter full-width. Semua ini
    menurunkan kualitas hasil, terutama di Bing RSS. Normalisasi ini idempoten.
    """
    text = unicodedata.normalize("NFKC", query)
    # Kontrol/zero-width diganti spasi (bukan dihapus) agar kata tidak menyatu.
    text = _CTRL_RE.sub(" ", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = text.strip(_QUOTE_CHARS).strip()
    text = re.sub(r"([!?.,;:])\1+", r"\1", text)
    text = text.strip(" ,;:!?.")
    if len(text) > max_chars:
        text = text[:max_chars].rstrip()
    return text


def query_terms(query: str) -> list[str]:
    """Term penting (tanpa stopword/token pendek) dari kueri ternormalisasi."""
    return [
        w
        for w in _WORD_RE.findall(normalize_query(query).lower())
        if len(w) > 2 and w not in _STOPWORDS
    ]


def relevance_score(result: WebResult, query: str) -> float:
    """Skor 0..1: fraksi term kueri yang muncul di judul/snippet hasil."""
    terms = query_terms(query)
    if not terms:
        return 0.0
    haystack = f"{result.title} {result.snippet}".lower()
    return sum(1 for t in terms if t in haystack) / len(terms)


def rank_by_relevance(results: list[WebResult], query: str) -> list[WebResult]:
    """Stabil-sort hasil menurut relevansi ke kueri (urutan asli jadi tiebreak).

    Membantu kueri Bahasa Indonesia: Bing kadang menaruh halaman generik di
    atas hasil yang benar-benar memuat istilah kueri.
    """
    if len(results) < 2:
        return results
    order = sorted(
        enumerate(results),
        key=lambda pair: (-relevance_score(pair[1], query), pair[0]),
    )
    return [r for _, r in order]


def filter_relevant(
    results: list[WebResult], query: str, min_score: float
) -> list[WebResult]:
    """Buang hasil berrelevansi rendah (skor < min_score) sebelum dipakai.

    Dipakai fallback web agar konteks lemah tidak pernah masuk prompt LLM.
    """
    return [r for r in results if relevance_score(r, query) >= min_score]


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


def parse_bing_rss(xml_text: str, max_results: int) -> list[WebResult]:
    """Parse feed RSS hasil pencarian Bing (www.bing.com/search?format=rss).

    Bing menyediakan feed XML resmi tanpa API key & tanpa challenge
    JavaScript — dipakai sebagai default karena DuckDuckGo diblokir DNS
    (internet positif) dan menyajikan captcha bot di banyak jaringan.
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    results: list[WebResult] = []
    for item in root.iter("item"):
        if len(results) >= max_results:
            break
        link = (item.findtext("link") or "").strip()
        if not link.startswith("http"):
            continue
        results.append(
            WebResult(
                title=(item.findtext("title") or "").strip(),
                url=link,
                snippet=(item.findtext("description") or "").strip(),
            )
        )
    return results


class BingRssSearch:
    """Pencarian Bing via feed RSS resmi — tanpa API key, tanpa captcha.

    Alternatif utama untuk jaringan yang memblokir DuckDuckGo;
    parser murni (ElementTree) tanpa dependensi tambahan.
    """

    def search(self, query: str, max_results: int) -> list[WebResult]:
        s = get_settings()
        params: dict[str, str] = {"q": query, "format": "rss"}
        # Bias hasil ke market/bahasa (mis. id-ID) — kueri Bahasa Indonesia
        # jauh lebih relevan daripada default en-US.
        market = s.web_search_market.strip()
        if market:
            params["mkt"] = market
            params["setlang"] = market.split("-")[0].lower()
        resp = httpx.get(
            "https://www.bing.com/search",
            params=params,
            headers={"User-Agent": _USER_AGENT},
            timeout=s.web_search_timeout_seconds,
            follow_redirects=True,
        )
        resp.raise_for_status()
        return parse_bing_rss(resp.text, max_results)


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
    """Ambil HTML halaman & ekstrak teks kasar (tanpa JS). Gagal → string kosong.

    Fase 4: SSRF-safe fetch — validasi URL sebelum HTTP request.
    """
    from ai_asistent_core.safefetch import safe_fetch

    try:
        page, success, reason = safe_fetch(
            url,
            timeout=get_settings().web_search_timeout_seconds,
            max_bytes=max_bytes,
        )
        if not success:
            logger.warning("fetch_page_text SSRF/validation gagal url=%s: %s", url, reason)
            return ""

        # Strip script/style tags, then HTML tags
        page = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", page, flags=re.S | re.I)
        page = re.sub(r"<[^>]+>", " ", page)
        return sanitize_text(page, max_chars=4000)
    except (ValueError, Exception) as exc:
        logger.warning("fetch_page_text gagal url=%s: %s", url, exc)
        return ""


# --- Facade -------------------------------------------------------------------


def _build_provider(name: str, s: CoreSettings) -> WebSearchProvider | None:
    """Bangun provider dari nama; None bila nama dinonaktifkan/tak dikenal.

    Melempar RuntimeError bila provider butuh konfigurasi yang belum diset
    (searx tanpa base URL, tavily tanpa API key).
    """
    if name == "bing_rss":
        return BingRssSearch()
    if name == "duckduckgo":
        return DuckDuckGoSearch()
    if name == "searx":
        if not s.web_search_base_url:
            raise RuntimeError("APP_WEB_SEARCH_BASE_URL belum diset untuk searx")
        return SearxSearch(s.web_search_base_url)
    if name == "tavily":
        if not s.tavily_api_key:
            raise RuntimeError("APP_TAVILY_API_KEY belum diset")
        return TavilySearch(s.tavily_api_key)
    return None


def get_web_search_provider() -> WebSearchProvider | None:
    """Provider utama dari settings; None bila web search dimatikan."""
    s = get_settings()
    return _build_provider(s.web_search_provider, s)


def _provider_attempts(
    primary: WebSearchProvider, s: CoreSettings
) -> list[tuple[str, WebSearchProvider]]:
    """Rantai provider: utama dulu, lalu cadangan (CSV) yang valid & unik."""
    attempts: list[tuple[str, WebSearchProvider]] = [(s.web_search_provider, primary)]
    for name in csv_list(s.web_search_fallback_providers_csv):
        if any(name == existing for existing, _ in attempts):
            continue
        try:
            provider = _build_provider(name, s)
        except RuntimeError as exc:
            logger.warning("provider web cadangan '%s' dilewati: %s", name, exc)
            continue
        if provider is not None:
            attempts.append((name, provider))
    return attempts


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
    query = normalize_query(query)
    if not query:
        return []
    if not rate_limit_allow():
        raise RuntimeError("Web search rate limit terlampaui")
    provider = get_web_search_provider()
    if provider is None:
        return []
    breaker = get_breaker("web_search")
    if not breaker.allow():
        raise RuntimeError("Web search circuit breaker OPEN — coba lagi nanti")
    policy = RetryPolicy(
        attempts=s.external_max_attempts,
        base_delay=s.external_retry_base_seconds,
        max_delay=s.external_retry_max_seconds,
    )

    # Coba provider utama; bila error atau hasilnya semua tak relevan, lanjut
    # ke provider cadangan. Set dengan skor terbaik diingat sebagai hasil akhir.
    attempts = _provider_attempts(provider, s)
    raw: list[WebResult] = []
    best_raw: list[WebResult] = []
    best_score = -1.0
    for idx, (name, prov) in enumerate(attempts):
        try:
            found = call_with_retry(
                partial(prov.search, query, s.web_search_max_results),
                policy=policy,
                retry_on=(httpx.HTTPError, OSError),
            )
        except Exception:
            if idx == len(attempts) - 1:
                breaker.record_failure()
                raise
            logger.warning("provider web '%s' gagal; mencoba provider cadangan", name)
            continue
        if not found:
            logger.info("provider web '%s' tidak mengembalikan hasil", name)
            continue
        raw = found
        top = max(relevance_score(r, query) for r in found)
        if top > best_score:
            best_raw, best_score = found, top
        if top >= s.web_evidence_min_relevance:
            break
        logger.info(
            "provider web '%s' hasilnya tak relevan (skor teratas %.2f)", name, top
        )
    breaker.record_success()
    raw = best_raw or raw
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
    return rank_by_relevance(results, query)


def to_json(data: object) -> str:
    """Helper kecil (dipakai test & logging)."""
    return json.dumps(data, ensure_ascii=False)
