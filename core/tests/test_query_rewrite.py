"""Test query_rewrite.py — Fase 3."""

from ai_asistent_core.query_rewrite import (
    RewrittenQuery,
    _expand_synonyms,
    _extract_keywords,
    _remove_meta_phrases,
    rewrite_query,
    should_use_rewrite,
)


class TestRemoveMetaPhrases:
    """Frasa meta dihapus."""

    def test_buang_carikan(self) -> None:
        q = "carikan informasi tentang cuti tahunan"
        cleaned = _remove_meta_phrases(q)
        assert "carikan" not in cleaned
        assert "cuti" in cleaned
        assert "tahunan" in cleaned

    def test_buang_tolong(self) -> None:
        q = "tolong cari biaya kesehatan"
        cleaned = _remove_meta_phrases(q)
        assert "tolong" not in cleaned
        assert "biaya" in cleaned

    def test_buang_di_internet(self) -> None:
        q = "cari informasi tentang gaji di internet"
        cleaned = _remove_meta_phrases(q)
        assert "di internet" not in cleaned
        assert "gaji" in cleaned

    def test_preserve_normal_query(self) -> None:
        q = "berapa biaya perjalanan dinas ke luar kota"
        cleaned = _remove_meta_phrases(q)
        # "berapa" adalah pembuka standard, boleh tetap
        assert "biaya" in cleaned
        assert "perjalanan" in cleaned

    def test_normalize_whitespace(self) -> None:
        q = "  carikan   informasi  tentang  cuti  "
        cleaned = _remove_meta_phrases(q)
        assert "  " not in cleaned
        assert cleaned == cleaned.strip()


class TestExtractKeywords:
    """Ekstrak term penting >= 3 char, filter stopword."""

    def test_basic_keywords(self) -> None:
        q = "berapa biaya perjalanan dinas ke luar kota"
        kws = _extract_keywords(q)
        assert "biaya" in kws
        assert "perjalanan" in kws
        assert "dinas" in kws
        assert "luar" in kws
        assert "kota" in kws

    def test_filter_stopwords(self) -> None:
        q = "apa yang menjadi bagian dari gaji karyawan"
        kws = _extract_keywords(q)
        assert "gaji" in kws
        assert "karyawan" in kws
        # Stopword tidak hadir
        assert "yang" not in kws
        assert "dari" not in kws

    def test_filter_short_terms(self) -> None:
        q = "apa itu penghasilan di kota"
        kws = _extract_keywords(q)
        assert "penghasilan" in kws
        assert "kota" in kws
        # "itu" dan "di" terlalu pendek
        assert "itu" not in kws
        assert "di" not in kws

    def test_empty_query(self) -> None:
        kws = _extract_keywords("")
        assert kws == []


class TestExpandSynonyms:
    """Ekspansi sinonim untuk keywords yang dikenali."""

    def test_expand_biaya(self) -> None:
        kws = ["biaya"]
        expanded = _expand_synonyms(kws)
        assert "harga" in expanded or "tarif" in expanded

    def test_expand_cuti(self) -> None:
        kws = ["cuti"]
        expanded = _expand_synonyms(kws)
        assert "libur" in expanded or "liburan" in expanded

    def test_no_expand_unknown(self) -> None:
        kws = ["xyz123"]
        expanded = _expand_synonyms(kws)
        assert "xyz123" in expanded
        # Tidak ada sinonim yang ditambah
        assert len(expanded) == 1

    def test_mixed_keywords(self) -> None:
        kws = ["biaya", "kesehatan", "xyz"]
        expanded = _expand_synonyms(kws)
        assert "biaya" in expanded
        assert "kesehatan" in expanded
        assert "xyz" in expanded
        # Jumlah expanded >= jumlah original
        assert len(expanded) >= len(kws)


class TestRewriteQuery:
    """Rewrite penuh: original → cleaned + semantic + keyword."""

    def test_typical_noisy_query(self) -> None:
        q = "carikan informasi tentang biaya kesehatan"
        r = rewrite_query(q)
        assert r.original == q
        assert "carikan" not in r.cleaned
        assert "biaya" in r.keyword
        assert "kesehatan" in r.keyword

    def test_clean_query_unchanged(self) -> None:
        q = "berapa biaya perjalanan ke luar kota"
        r = rewrite_query(q)
        assert r.original == q
        # Cleaned harus mirip dengan original (tidak ada meta phrases)
        assert r.cleaned  # non-empty
        assert "biaya" in r.cleaned

    def test_return_type(self) -> None:
        q = "cari gaji karyawan"
        r = rewrite_query(q)
        assert isinstance(r, RewrittenQuery)
        assert r.original == q
        assert isinstance(r.cleaned, str)
        assert isinstance(r.semantic, str)
        assert isinstance(r.keyword, str)

    def test_varian_semantic_keyword_differ(self) -> None:
        # Query panjang dengan banyak stopword
        q = "carikan informasi yang detail tentang biaya kesehatan dan asuransi"
        r = rewrite_query(q)
        # Semantic adalah cleaned query (semua term bermakna + stopword minimal)
        # Keyword adalah extracted keywords + sinonim (bisa lebih panjang karena sinonim)
        # Yang penting: keduanya mengandung term inti
        assert "biaya" in r.semantic or "biaya" in r.keyword
        assert "kesehatan" in r.semantic or "kesehatan" in r.keyword
        # Keduanya berbeda dari original (meta phrase "carikan" dibuang)
        assert "carikan" not in r.semantic
        assert "carikan" not in (r.keyword or "")


class TestShouldUseRewrite:
    """Heuristic: kapan rewrite worthwhile?"""

    def test_short_query_no_rewrite(self) -> None:
        q = "gaji"
        assert not should_use_rewrite(q)

    def test_query_with_meta_phrase_use_rewrite(self) -> None:
        q = "carikan informasi tentang cuti tahunan"
        assert should_use_rewrite(q)

    def test_long_query_use_rewrite(self) -> None:
        q = (
            "berapa total biaya kesehatan dan asuransi yang ditanggung "
            "perusahaan untuk karyawan full time"
        )
        assert should_use_rewrite(q)

    def test_medium_clean_query_no_rewrite(self) -> None:
        q = "berapa gaji pokok karyawan baru"
        # Tidak ada meta phrase, panjang < 50
        assert not should_use_rewrite(q)
