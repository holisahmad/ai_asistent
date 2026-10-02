"""Test unit Fase 7 — web search: ACL domain, sanitasi, parsing, rate limit."""

from collections.abc import Iterator

import pytest

from ai_asistent_core.config import get_settings
from ai_asistent_core.websearch import (
    BingRssSearch,
    domain_allowed,
    get_web_search_provider,
    parse_bing_rss,
    parse_ddg_html,
    parse_searx_json,
    rate_limit_allow,
    registrable_domain,
    reset_rate_limit,
    sanitize_text,
    web_search,
)


@pytest.fixture(autouse=True)
def _clean_rate_limit() -> Iterator[None]:
    reset_rate_limit()
    yield
    reset_rate_limit()


def test_registrable_domain() -> None:
    assert registrable_domain("https://docs.example.com/a/b") == "example.com"
    assert registrable_domain("https://example.com") == "example.com"
    assert registrable_domain("http://localhost:8080/x") == "localhost"
    assert registrable_domain("https://192.168.1.1/x") == "192.168.1.1"
    assert registrable_domain("not a url") == ""


def test_domain_allowed_denylist_wins_over_allowlist() -> None:
    allow = ["example.com"]
    deny = ["bad.example.com"]
    assert domain_allowed("https://good.example.com/x", allow, deny) is True
    # deny menang walau allowlist cocok (subdomain deny)
    assert domain_allowed("https://bad.example.com/x", allow, deny) is False


def test_domain_allowed_empty_allowlist_means_all() -> None:
    assert domain_allowed("https://anything.io/page", [], []) is True
    assert domain_allowed("https://blocked.io/page", [], ["blocked.io"]) is False
    assert domain_allowed("https://other.io/page", ["only.com"], []) is False


def test_sanitize_text_strips_tags_entities_and_control() -> None:
    raw = "<b>Halo</b> &amp; <script>x</script>\x00  dunia\n\n  penuh\tspasi\u200b"
    out = sanitize_text(raw)
    assert "<" not in out and "&amp;" not in out
    assert "Halo" in out and "&" in out and "dunia" in out
    assert "\x00" not in out and "\u200b" not in out
    assert "  " not in out


def test_sanitize_text_truncates() -> None:
    out = sanitize_text("kata " * 500, max_chars=40)
    assert len(out) <= 41
    assert out.endswith("…")


def test_parse_ddg_html_unwraps_redirect() -> None:
    page = (
        '<a rel="nofollow" class="result__a" '
        'href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fartikel&amp;rut=abc">'
        "Judul <b>Penting</b></a>"
        '<a class="result__snippet" href="x">Cuplikan <b>pertama</b> &amp; berguna</a>'
        '<a rel="nofollow" class="result__a" href="https://kedua.example.org/x">Kedua</a>'
    )
    results = parse_ddg_html(page, max_results=5)
    assert len(results) == 2
    assert results[0].url == "https://example.com/artikel"
    assert results[0].title == "Judul Penting"
    assert results[0].snippet == "Cuplikan pertama & berguna"
    assert results[1].url == "https://kedua.example.org/x"
    assert results[1].snippet == ""  # tidak ada snippet kedua
    # URL non-http (mis. relatif/janggal) dibuang
    assert parse_ddg_html('<a class="result__a" href="/relatif">x</a>', 5) == []


def test_parse_bing_rss_extracts_items() -> None:
    feed = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>Bing: python</title>
<item><title>Welcome to Python.org</title><link>https://www.python.org/</link>
<description>Quick &amp; Easy to Learn</description></item>
<item><title>Programiz</title><link>https://www.programiz.com/python</link>
<description>Tutorial Python</description></item>
</channel></rss>"""
    results = parse_bing_rss(feed, max_results=5)
    assert len(results) == 2
    assert results[0].title == "Welcome to Python.org"
    assert results[0].url == "https://www.python.org/"
    assert results[0].snippet == "Quick & Easy to Learn"
    assert results[1].url == "https://www.programiz.com/python"


def test_parse_bing_rss_bounds_and_skips_bad_links() -> None:
    feed = (
        "<rss><channel>"
        "<item><title>A</title><link>https://a.io/x</link></item>"
        "<item><title>B</title><link>https://b.io/x</link></item>"
        "<item><title>C</title><link></link></item>"
        "</channel></rss>"
    )
    assert len(parse_bing_rss(feed, max_results=1)) == 1  # batas max_results
    out = parse_bing_rss(feed, max_results=5)
    assert len(out) == 2  # link kosong/non-http dibuang
    assert parse_bing_rss("bukan xml <>", 5) == []  # XML rusak → aman kosong


def test_get_provider_bing_rss(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "web_search_provider", "bing_rss")
    assert isinstance(get_web_search_provider(), BingRssSearch)


def test_parse_searx_json_bounds_and_skips_bad_items() -> None:
    data = {
        "results": [
            {"title": "A", "url": "https://a.io", "content": "isi a"},
            "bukan dict",
            {"title": "B", "url": "https://b.io", "content": "isi b"},
        ]
    }
    out = parse_searx_json(data, max_results=1)
    assert len(out) == 1
    assert out[0].title == "A"
    assert parse_searx_json("bukan dict", 5) == []
    assert parse_searx_json({"results": "bukan list"}, 5) == []


def test_rate_limit_blocks_after_quota(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "web_search_rate_limit_per_min", 2)
    assert rate_limit_allow() is True
    assert rate_limit_allow() is True
    assert rate_limit_allow() is False


def test_get_provider_none_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "web_search_provider", "none")
    assert get_web_search_provider() is None


def test_web_search_disabled_returns_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "web_search_provider", "none")
    assert web_search("apa saja") == []


def test_web_search_applies_domain_acl(monkeypatch: pytest.MonkeyPatch) -> None:
    """Provider palsu → hasil difilter allowlist/denylist + disanitasi."""
    from ai_asistent_core.websearch import WebResult

    class FakeProvider:
        def search(self, query: str, max_results: int) -> list[WebResult]:
            return [
                WebResult(
                    title="<b>Diizinkan</b>",
                    url="https://ok.example.com/a",
                    snippet="  isi  ",
                ),
                WebResult(title="Diblokir", url="https://evil.example.com/b", snippet="isi"),
            ]

    monkeypatch.setattr(get_settings(), "web_search_provider", "duckduckgo")
    monkeypatch.setattr(get_settings(), "web_search_domain_allowlist_csv", "example.com")
    monkeypatch.setattr(get_settings(), "web_search_domain_denylist_csv", "evil.example.com")
    monkeypatch.setattr(
        "ai_asistent_core.websearch.get_web_search_provider", lambda: FakeProvider()
    )
    out = web_search("kata kunci")
    assert len(out) == 1
    assert out[0].url == "https://ok.example.com/a"
    assert out[0].title == "Diizinkan"  # tag HTML dibuang
    assert out[0].snippet == "isi"
