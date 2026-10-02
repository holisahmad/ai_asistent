"""Orkestrasi RAG (Fase 6/7): retrieve → LLM → jawaban grounded + sitasi.

No-answer behavior wajib (roadmap): bila LLM menyatakan `NO_ANSWER` (atau
tidak ada kandidat sama sekali), jawaban diganti pesan "informasi belum
tersedia" dan flag `no_answer` di-set.

Web fallback (Fase 7): HANYA bila mode `internal_plus_web` dan pemanggil
mengizinkan (`allow_web=True`) dan bukti internal tidak mencukupi. Setiap
hasil web dicatat ke `web_search_logs`, disanitasi, dan sitasinya selalu
`source_type="web"` — tidak pernah dicampur dengan sitasi internal.
"""

import json
import logging
from collections.abc import Iterator
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from ai_asistent_core.config import get_settings
from ai_asistent_core.injection import harden_context
from ai_asistent_core.llm import NO_ANSWER, LLMProvider, _is_no_answer, get_llm_provider
from ai_asistent_core.models import WebSearchLog
from ai_asistent_core.retrieval import RetrievedChunk, retrieve
from ai_asistent_core.websearch import (
    WebResult,
    fetch_page_text,
    filter_relevant,
    relevance_score,
    web_search,
)

logger = logging.getLogger("ai_asistent_core.rag")

NO_ANSWER_MESSAGE = "Informasi belum tersedia dalam knowledge base."


@dataclass(frozen=True)
class CitationOut:
    """Objek sitasi klikabel yang dikembalikan ke klien."""

    idx: int  # nomor sitasi [1], [2], ... sebagaimana dirujuk di jawaban
    chunk_id: str | None = None
    file_id: str | None = None
    filename: str = ""
    locator_type: str = "char"
    locator_start: int = 0
    locator_end: int = 0
    snippet: str = ""
    score: float = 0.0
    source_type: str = "internal"  # internal | web
    url: str | None = None  # hanya untuk source_type=web


@dataclass(frozen=True)
class RagAnswer:
    """Jawaban grounded + provenance untuk disimpan & dikirim ke klien."""

    text: str
    answer_kind: str  # "grounded" | "no_answer" | "grounded_web"
    citations: list[CitationOut] = field(default_factory=list)
    used_chunk_ids: list[str] = field(default_factory=list)
    web_fallback: dict[str, object] = field(default_factory=dict)

    @property
    def meta_json(self) -> str:
        """Metadata jawaban untuk kolom answer_meta_json."""
        return json.dumps(
            {
                "answer_kind": self.answer_kind,
                "used_chunk_ids": self.used_chunk_ids,
                "citation_count": len(self.citations),
                "web_fallback": self.web_fallback,
            },
            ensure_ascii=False,
        )


def _citations(chunks: list[RetrievedChunk]) -> list[CitationOut]:
    return [
        CitationOut(
            idx=i + 1,
            chunk_id=c.chunk_id,
            file_id=c.file_id,
            filename=c.filename,
            locator_type=c.locator_type,
            locator_start=c.locator_start,
            locator_end=c.locator_end,
            snippet=c.snippet(),
            score=round(c.score, 6),
            source_type="internal",
        )
        for i, c in enumerate(chunks)
    ]


def _select_contexts(chunks: list[RetrievedChunk]) -> list[RetrievedChunk]:
    """Batasi total konteks agar prompt hemat token (roadmap: biaya token)."""
    s = get_settings()
    total = 0
    selected: list[RetrievedChunk] = []
    for c in chunks:
        if total + len(c.content) > s.rag_max_context_chars and selected:
            break
        selected.append(c)
        total += len(c.content)
    return selected


def _context_texts(selected: list[RetrievedChunk]) -> list[str]:
    """Teks konteks siap prompt: disanitasi & dibersihkan dari injeksi (Fase 9)."""
    return [harden_context(c.content) for c in selected]


def _web_allowed(allow_web: bool) -> bool:
    """Web fallback hanya bila pemanggil izinkan DAN mode workspace mengizinkan."""
    return allow_web and get_settings().web_fallback_mode == "internal_plus_web"


def _attempt_web_fallback(
    db: Session, workspace_id: str, question: str, llm: LLMProvider
) -> RagAnswer | None:
    """Cari jawaban di web; None bila tidak diizinkan/gagal/tetap tak cukup.

    Selalu mencatat percobaan ke web_search_logs (provenance & audit biaya).
    """
    s = get_settings()
    rejected: list[dict[str, object]] = []
    try:
        results = web_search(question, audit=rejected)
    except Exception as exc:  # noqa: BLE001 - fallback tidak boleh menjatuhkan chat
        logger.warning("web search gagal: %s: %s", type(exc).__name__, exc)
        _log_web_search(db, workspace_id, question, list(rejected), error=str(exc)[:200])
        return None

    # Saring hasil berrelevansi rendah: konteks lemah tidak boleh masuk prompt.
    entries: list[dict[str, object]] = []
    for r in results:
        score = relevance_score(r, question)
        entries.append(
            {
                "title": r.title,
                "url": r.url,
                "score": round(score, 3),
                "fetched": False,
                "used": False,
                "rejected": None if score >= s.web_evidence_min_relevance else "low_relevance",
            }
        )
    entries += rejected
    kept = filter_relevant(results, question, s.web_evidence_min_relevance)
    _log_web_search(db, workspace_id, question, entries, results_count=len(kept))
    min_results = max(1, s.web_evidence_min_results)
    if len(kept) < min_results:
        logger.info(
            "bukti web tidak cukup (lolos=%d dari %d; min_relevance=%.2f, min_results=%d)",
            len(kept),
            len(results),
            s.web_evidence_min_relevance,
            min_results,
        )
        return None

    contexts: list[str] = []
    used: list[WebResult] = []
    used_urls: list[str] = []
    for r in kept[:3]:  # fetch halaman teratas saja (latency & biaya)
        body = fetch_page_text(r.url) or r.snippet
        for e in entries:
            if e["url"] == r.url:
                e["fetched"] = bool(body)
        if body:
            contexts.append(f"Sumber web: {r.title} ({r.url})\n{body}")
            used.append(r)
            used_urls.append(r.url)
    if not contexts:
        return None

    result = llm.generate(question, contexts)
    if result.no_answer or not result.text.strip():
        return None

    citations = [
        CitationOut(
            idx=i + 1,
            filename=r.title,
            locator_type="url",
            snippet=r.snippet or contexts[i][:200],
            source_type="web",
            url=r.url,
        )
        for i, r in enumerate(used)
    ]
    return RagAnswer(
        text=result.text.strip(),
        answer_kind="grounded_web",
        citations=citations,
        web_fallback={"attempted": True, "provider": s.web_search_provider, "urls": used_urls},
    )


def _log_web_search(
    db: Session,
    workspace_id: str,
    query: str,
    entries: list[dict[str, object]],
    *,
    results_count: int | None = None,
    error: str | None = None,
) -> None:
    """Simpan satu baris web_search_logs (best-effort; jangan ganggu chat)."""
    try:
        db.add(
            WebSearchLog(
                workspace_id=workspace_id,
                query=query[:2000],
                provider=get_settings().web_search_provider,
                results_count=len(entries) if results_count is None else results_count,
                log_json=json.dumps({"results": entries, "error": error}, ensure_ascii=False),
            )
        )
        db.commit()
    except Exception:  # noqa: BLE001
        db.rollback()
        logger.warning("gagal menulis web_search_logs", exc_info=True)


def _no_answer(web_fallback: dict[str, object] | None = None) -> RagAnswer:
    return RagAnswer(
        text=NO_ANSWER_MESSAGE,
        answer_kind="no_answer",
        web_fallback=web_fallback or {},
    )


def answer_question(
    db: Session,
    workspace_id: str,
    question: str,
    *,
    provider: LLMProvider | None = None,
    allow_web: bool = False,
) -> RagAnswer:
    """Pipeline penuh: hybrid retrieval → LLM grounded → sitasi/no-answer/web."""
    llm: LLMProvider = provider if provider is not None else get_llm_provider()

    chunks = retrieve(db, workspace_id, question)
    if not chunks:
        if _web_allowed(allow_web):
            web = _attempt_web_fallback(db, workspace_id, question, llm)
            if web is not None:
                return web
        return _no_answer()

    selected = _select_contexts(chunks)
    result = llm.generate(question, _context_texts(selected))
    text = result.text.strip()
    if not result.no_answer and text and text != NO_ANSWER:
        return RagAnswer(
            text=text,
            answer_kind="grounded",
            citations=_citations(selected),
            used_chunk_ids=[c.chunk_id for c in selected],
        )

    # Bukti internal tidak mencukupi → web fallback (bila diizinkan).
    if _web_allowed(allow_web):
        web = _attempt_web_fallback(db, workspace_id, question, llm)
        if web is not None:
            return web
    return _no_answer({"attempted": _web_allowed(allow_web)})


class _AnswerStream:
    """Iterator delta teks + `final()` untuk getter hasil akhir."""

    def __init__(self, gen: "Iterator[str]", finals: list[RagAnswer]) -> None:
        self._gen = gen
        self._finals = finals

    def __iter__(self) -> "Iterator[str]":
        return self._gen

    def final(self) -> RagAnswer:
        for _ in self._gen:  # pastikan generator habis
            pass
        return self._finals[-1] if self._finals else _no_answer()


def answer_stream(
    db: Session,
    workspace_id: str,
    question: str,
    *,
    provider: LLMProvider | None = None,
    allow_web: bool = False,
) -> _AnswerStream:
    """Versi streaming: iterasi untuk delta, `final()` setelah habis."""
    llm: LLMProvider = provider if provider is not None else get_llm_provider()

    deltas: list[str] = []
    finals: list[RagAnswer] = []

    def generate() -> "Iterator[str]":
        chunks = retrieve(db, workspace_id, question)
        selected = _select_contexts(chunks)
        if selected:
            # Tahan keluaran awal selama masih mungkin sentinel NO_ANSWER agar
            # sentinel tidak sempat terlihat di UI klien.
            held = ""
            try:
                for delta in llm.stream_generate(question, _context_texts(selected)):
                    deltas.append(delta)
                    held += delta
                    if len(held) <= len(NO_ANSWER) and NO_ANSWER.startswith(held.strip()):
                        continue
                    yield held
                    held = ""
                if held:
                    yield held
            except Exception as exc:  # noqa: BLE001 - error LLM → jalur no-answer
                logger.warning("stream LLM gagal: %s: %s", type(exc).__name__, exc)
                deltas.clear()

        text = "".join(deltas).strip()
        if selected and text and not _is_no_answer(text):
            finals.append(
                RagAnswer(
                    text=text,
                    answer_kind="grounded",
                    citations=_citations(selected),
                    used_chunk_ids=[c.chunk_id for c in selected],
                )
            )
            return

        if _web_allowed(allow_web):
            web = _attempt_web_fallback(db, workspace_id, question, llm)
            if web is not None:
                finals.append(web)
                yield web.text
                return
        finals.append(_no_answer({"attempted": _web_allowed(allow_web)}))

    return _AnswerStream(generate(), finals)
