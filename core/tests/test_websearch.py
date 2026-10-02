"""Test unit Fase 7 — web search: ACL domain, sanitasi, parsing, rate limit."""

from collections.abc import Iterator

import pytest

from ai_asistent_core.config import get_settings
from ai_asistent_core.websearch import (
    BingRssSearch,
    WebResult,
    domain_allowed,
    filter_relevant,
    get_web_search_provider,
    normalize_query,
    parse_bing_rss,
    parse_ddg_html,
    parse_searx_json,
    query_terms,
    rank_by_relevance,
    rate_limit_allow,
    registrable_domain,
    relevance_score,
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


# --- Kualitas kueri Bahasa Indonesia -----------------------------------------


def test_normalize_query_cleans_chat_artifacts() -> None:
    assert normalize_query('  "Apa itu Retrieval Augmented Generation???"  ') == (
        "Apa itu Retrieval Augmented Generation"
    )
    # full-width (NFKC) + ideographic space
    assert normalize_query("ＡＰＡ　ＩＴＵ") == "APA ITU"
    # zero-width diganti spasi, bukan dihapus (kata tidak menyatu)
    assert normalize_query("apa\u200bitu   retrieval") == "apa itu retrieval"
    assert normalize_query("apaaa") == "apaaa"
    assert normalize_query("  ") == ""


def test_normalize_query_is_idempotent_and_bounded() -> None:
    once = normalize_query('“Apa itu RAG di Indonesia?”')
    assert normalize_query(once) == once
    capped = normalize_query("kata " * 200, max_chars=20)
    assert len(capped) <= 20
    assert capped == capped.rstrip()


def test_query_terms_drops_stopwords_and_short_tokens() -> None:
    assert query_terms("Apa itu RAG di Indonesia?") == ["rag", "indonesia"]
    assert query_terms("dan atau untuk") == []


def test_relevance_score_and_stable_ranking() -> None:
    query = "apa itu retrieval augmented generation"
    relevant = WebResult(
        "Retrieval Augmented Generation di Indonesia",
        "https://id.example.com/rag",
        "panduan RAG",
    )
    generic = WebResult(
        "Generic overview", "https://en.example.com/a", "a technique for data"
    )
    assert relevance_score(relevant, query) == 1.0
    assert relevance_score(generic, query) < 1.0
    assert rank_by_relevance([generic, relevant], query)[0] is relevant
    # skor sama → urutan asli dipertahankan (stabil)
    assert rank_by_relevance([generic, generic], query) == [generic, generic]
    # kueri tanpa term bermakna → skor 0, urutan tetap
    assert relevance_score(generic, "apa itu") == 0.0
    assert rank_by_relevance([relevant, generic], "apa itu") == [relevant, generic]


def test_filter_relevant_drops_low_scores() -> None:
    query = "apa itu postgresql"
    good = WebResult("PostgreSQL docs", "https://www.postgresql.org/", "panduan resmi")
    weak = WebResult("Kucing lucu", "https://cats.example.com", "video kucing")
    assert filter_relevant([good, weak], query, 0.34) == [good]
    assert filter_relevant([weak], query, 0.34) == []
    assert filter_relevant([weak], query, 0.0) == [weak]  # ambang 0 = tanpa filter


def test_web_search_normalizes_query_for_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, str] = {}

    class FakeProvider:
        def search(self, query: str, max_results: int) -> list[WebResult]:
            captured["query"] = query
            return []

    monkeypatch.setattr(get_settings(), "web_search_provider", "bing_rss")
    monkeypatch.setattr(
        "ai_asistent_core.websearch.get_web_search_provider", lambda: FakeProvider()
    )
    assert web_search('  "Apa itu PostgreSQL???"  ') == []
    assert captured["query"] == "Apa itu PostgreSQL"


def test_web_search_rejects_whitespace_only_query(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "web_search_provider", "bing_rss")
    monkeypatch.setattr(
        "ai_asistent_core.websearch.get_web_search_provider",
        lambda: (_ for _ in ()).throw(AssertionError("provider tidak boleh dipanggil")),
    )
    assert web_search("   \u200b  ") == []


def test_web_search_ranks_indonesian_relevant_first(monkeypatch: pytest.MonkeyPatch) -> None:
    """Kueri ID: hasil yang benar-benar memuat istilah kueri naik ke atas."""

    class FakeProvider:
        def search(self, query: str, max_results: int) -> list[WebResult]:
            return [
                WebResult("Generic guide", "https://en.example.com/a", "about databases"),
                WebResult(
                    "PostgreSQL untuk pengembang di Indonesia",
                    "https://id.example.com/b",
                    "panduan postgresql lengkap",
                ),
            ]

    monkeypatch.setattr(get_settings(), "web_search_provider", "bing_rss")
    monkeypatch.setattr(get_settings(), "web_search_domain_allowlist_csv", "")
    monkeypatch.setattr(get_settings(), "web_search_domain_denylist_csv", "")
    monkeypatch.setattr(
        "ai_asistent_core.websearch.get_web_search_provider", lambda: FakeProvider()
    )
    out = web_search("apa itu postgresql")
    assert [r.url for r in out] == ["https://id.example.com/b", "https://en.example.com/a"]


def test_parse_bing_rss_indonesian_results_are_relevant() -> None:
    feed = (
        "<rss><channel>"
        "<item><title>Retrieval Augmented Generation (RAG) di Indonesia</title>"
        "<link>https://id.example.com/rag</link>"
        "<description>Panduan retrieval augmented generation untuk pemula</description></item>"
        "<item><title>Kapan RAG dipakai?</title>"
        "<link>https://id.example.com/kapan</link>"
        "<description>Retrieval augmented generation vs fine-tuning</description></item>"
        "</channel></rss>"
    )
    results = parse_bing_rss(feed, max_results=5)
    assert len(results) == 2
    query = "apa itu retrieval augmented generation"
    assert all(relevance_score(r, query) == 1.0 for r in results)
    assert rank_by_relevance(results, query) == results


class _FakeResponse:
    def __init__(self, text: str) -> None:
        self.text = text

    def raise_for_status(self) -> None:
        return None


_BING_FEED = (
    "<?xml version='1.0' encoding='UTF-8'?><rss><channel>"
    "<item><title>PostgreSQL</title><link>https://www.postgresql.org/</link>"
    "<description>Basis data relasional</description></item>"
    "</channel></rss>"
)


def test_bing_rss_sends_market_params(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_get(url: str, **kwargs: object) -> _FakeResponse:
        captured["url"] = url
        captured.update(kwargs.get("params") or {})  # type: ignore[arg-type]
        return _FakeResponse(_BING_FEED)

    monkeypatch.setattr("ai_asistent_core.websearch.httpx.get", fake_get)
    monkeypatch.setattr(get_settings(), "web_search_market", "id-ID")
    out = BingRssSearch().search("apa itu postgresql", 5)
    assert captured["url"] == "https://www.bing.com/search"
    assert captured["format"] == "rss"
    assert captured["q"] == "apa itu postgresql"
    assert captured["mkt"] == "id-ID"
    assert captured["setlang"] == "id"
    assert len(out) == 1 and out[0].url == "https://www.postgresql.org/"


def test_bing_rss_omits_market_when_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_get(url: str, **kwargs: object) -> _FakeResponse:
        captured.update(kwargs.get("params") or {})  # type: ignore[arg-type]
        return _FakeResponse(_BING_FEED)

    monkeypatch.setattr("ai_asistent_core.websearch.httpx.get", fake_get)
    monkeypatch.setattr(get_settings(), "web_search_market", "")
    BingRssSearch().search("q", 3)
    assert "mkt" not in captured
    assert "setlang" not in captured
