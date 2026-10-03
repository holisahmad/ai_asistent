"""Query rewriting — Fase 3 upgrade: memperbaiki kueri "berisik" deterministik.

Pola: buang frasa meta (carikan, tolong, di internet, saya mau tahu), parafrase
sinonim, hasilkan varian untuk retrieval hybrid.

Default: OFF (`APP_QUERY_REWRITE_ENABLED=false`). Uplift diukur via eval dataset.
"""

import re
from dataclasses import dataclass

# Frasa meta yang dibuang (Bahasa Indonesia + English).
META_PHRASES = {
    # Indonesian
    r"\bcarikan\b",
    r"\bcarilah\b",
    r"\btolong\b",
    r"\bmohan\b",
    r"\bberikan\b",
    r"\bdi\s+internet\b",
    r"\bdi\s+web\b",
    r"\bsaya\s+mau\s+tahu\b",
    r"\bsaya\s+ingin\s+tahu\b",
    r"\bi\s+want\s+to\s+know\b",
    r"\bplease\s+find\b",
    r"\bfind\s+me\b",
    r"\bsearch\s+for\b",
    r"\btell\s+me\b",
    r"\bapakah\b",  # pembuka pertanyaan umum
    r"\badakah\b",
    r"\bapa\s+saja\b",
}

# Sinonim untuk expansi (key: term → list[synonyms]).
SYNONYMS = {
    "biaya": ["harga", "tarif", "ongkos", "cost", "fee"],
    "cuti": ["libur", "liburan", "vacation", "leave"],
    "kesehatan": ["medis", "kesek", "health", "medical"],
    "kendaraan": ["mobil", "motor", "kendaraan operasional", "vehicle"],
    "gaji": ["upah", "salary", "bayaran"],
    "kantor": ["lokasi kerja", "tempat kerja", "office"],
    "pertemuan": ["rapat", "meeting", "diskusi"],
    "proyek": ["project", "pekerjaan", "tugas"],
}


@dataclass(frozen=True)
class RewrittenQuery:
    """Hasil rewriting: varian kueri untuk retrieval hybrid."""

    original: str
    cleaned: str  # buang meta phrases
    semantic: str  # varian semantik (bisa == cleaned)
    keyword: str  # varian keyword (term penting saja)
    entity: str | None = None  # entity-centric (opsional)


def _remove_meta_phrases(query: str) -> str:
    """Buang frasa meta + normalize whitespace."""
    q = query.lower().strip()
    for pattern in META_PHRASES:
        q = re.sub(pattern, " ", q, flags=re.IGNORECASE)
    # Normalize whitespace
    q = " ".join(q.split())
    return q


def _extract_keywords(query: str) -> list[str]:
    """Ekstrak term penting (> 3 char atau bukan stopword pendek)."""
    basic_stopwords = {
        # Indonesian
        "yang", "dan", "atau", "di", "ke", "dari", "untuk", "pada",
        "ini", "itu", "ada", "apa", "hal", "saat", "jika", "maka",
        "bisa", "akan", "sudah", "juga", "dengan", "oleh", "atas",
        "bagi", "agar", "kami", "kita", "saya", "anda", "mereka",
        # English
        "the", "and", "or", "in", "to", "from", "for", "at", "is",
        "a", "an", "by", "with", "of", "as", "it", "be", "its", "are",
    }
    tokens = re.findall(r"\b[a-z0-9]+\b", query.lower())
    return [t for t in tokens if len(t) >= 4 and t not in basic_stopwords]


def _expand_synonyms(keywords: list[str]) -> list[str]:
    """Tambah sinonim untuk keywords yang dikenali."""
    expanded = list(keywords)
    for kw in keywords:
        if kw in SYNONYMS:
            expanded.extend(SYNONYMS[kw][:2])  # max 2 sinonim per term
    return expanded


def rewrite_query(query: str) -> RewrittenQuery:
    """Rewrite query untuk retrieval hybrid (semantic + keyword + entity).

    Args:
        query: Pertanyaan user (bisa dengan basa-basi).

    Returns:
        RewrittenQuery dengan varian-varian untuk dicoba.
    """
    cleaned = _remove_meta_phrases(query)
    if not cleaned:
        # Query kosong setelah pembersihan → gunakan original
        cleaned = query.strip()

    # Keyword extraction + expansion
    kws = _extract_keywords(cleaned)
    kws_expanded = _expand_synonyms(kws)
    keyword_query = " ".join(kws_expanded) if kws_expanded else cleaned

    # Semantic variant: minimal processing (hanya bersihkan, jaga struktur).
    semantic_query = cleaned

    return RewrittenQuery(
        original=query,
        cleaned=cleaned,
        semantic=semantic_query,
        keyword=keyword_query,
        entity=None,  # Reserved untuk future entity extraction.
    )


def should_use_rewrite(query: str) -> bool:
    """Heuristic: apakah query layak di-rewrite?

    Rewrite bermanfaat jika query punya meta phrases atau panjangnya >= 50 char.
    """
    if len(query) < 10:
        return False
    has_meta = any(
        re.search(pattern, query.lower()) for pattern in META_PHRASES
    )
    is_long = len(query) > 50
    return has_meta or is_long
