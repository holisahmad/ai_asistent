"""Orkestrasi RAG (Fase 6): retrieve → LLM → jawaban grounded + sitasi.

No-answer behavior wajib (roadmap): bila LLM menyatakan `NO_ANSWER` (atau
tidak ada kandidat sama sekali), jawaban diganti pesan "informasi belum
tersedia" dan flag `no_answer` di-set — web fallback menyusul di Fase 7.
Sitasi dirakit dari kandidat yang dipakai sebagai konteks (ACL sudah
dijamin `retrieve` via filter workspace di SQL).
"""

import json
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from ai_asistent_core.config import get_settings
from ai_asistent_core.llm import NO_ANSWER, LLMProvider, get_llm_provider
from ai_asistent_core.retrieval import RetrievedChunk, retrieve

NO_ANSWER_MESSAGE = "Informasi belum tersedia dalam knowledge base."


@dataclass(frozen=True)
class CitationOut:
    """Objek sitasi klikabel yang dikembalikan ke klien."""

    idx: int  # nomor sitasi [1], [2], ... sebagaimana dirujuk di jawaban
    chunk_id: str
    file_id: str
    filename: str
    locator_type: str
    locator_start: int
    locator_end: int
    snippet: str
    score: float


@dataclass(frozen=True)
class RagAnswer:
    """Jawaban grounded + provenance untuk disimpan & dikirim ke klien."""

    text: str
    answer_kind: str  # "grounded" | "no_answer"
    citations: list[CitationOut] = field(default_factory=list)
    used_chunk_ids: list[str] = field(default_factory=list)

    @property
    def meta_json(self) -> str:
        """Metadata jawaban untuk kolom answer_meta_json."""
        return json.dumps(
            {
                "answer_kind": self.answer_kind,
                "used_chunk_ids": self.used_chunk_ids,
                "citation_count": len(self.citations),
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
        )
        for i, c in enumerate(chunks)
    ]


def answer_question(
    db: Session,
    workspace_id: str,
    question: str,
    *,
    provider: LLMProvider | None = None,
) -> RagAnswer:
    """Pipeline penuh: hybrid retrieval → LLM grounded → sitasi/no-answer."""
    s = get_settings()
    llm: LLMProvider = provider if provider is not None else get_llm_provider()

    chunks = retrieve(db, workspace_id, question)
    if not chunks:
        return RagAnswer(text=NO_ANSWER_MESSAGE, answer_kind="no_answer")

    # Batasi total konteks agar prompt hemat token (roadmap: biaya token).
    total = 0
    selected: list[RetrievedChunk] = []
    for c in chunks:
        if total + len(c.content) > s.rag_max_context_chars and selected:
            break
        selected.append(c)
        total += len(c.content)

    result = llm.generate(question, [c.content for c in selected])
    if result.no_answer:
        return RagAnswer(text=NO_ANSWER_MESSAGE, answer_kind="no_answer")

    text = result.text.strip() or NO_ANSWER_MESSAGE
    if text == NO_ANSWER:  # paranoid: teks persis sentinel tanpa flag
        return RagAnswer(text=NO_ANSWER_MESSAGE, answer_kind="no_answer")
    return RagAnswer(
        text=text,
        answer_kind="grounded",
        citations=_citations(selected),
        used_chunk_ids=[c.chunk_id for c in selected],
    )
