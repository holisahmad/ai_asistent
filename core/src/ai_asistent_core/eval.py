"""Metrik evaluasi retrieval & answer (Fase 6/10).

Fungsi murni tanpa I/O jaringan, dipakai oleh `scripts/eval_rag.py`
(laporan) dan `backend/tests/test_retrieval_eval.py` (quality gate CI).
"""

import json
import math
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class EvalDocument:
    """Dokumen contoh pada dataset evaluasi."""

    filename: str
    content: str


@dataclass(frozen=True)
class EvalQuery:
    """Kueri + dokumen yang diharapkan (None = harus no-answer)."""

    question: str
    expected_filename: str | None


@dataclass(frozen=True)
class EvalDataset:
    """Dataset evaluasi lengkap."""

    name: str
    version: int
    documents: list[EvalDocument]
    queries: list[EvalQuery]


def load_dataset(path: str | Path) -> EvalDataset:
    """Baca dataset JSON evaluasi."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return EvalDataset(
        name=str(data.get("name", "dataset")),
        version=int(data.get("version", 1)),
        documents=[
            EvalDocument(filename=str(d["filename"]), content=str(d["content"]))
            for d in data["documents"]
        ],
        queries=[
            EvalQuery(
                question=str(q["question"]),
                expected_filename=(
                    str(q["expected_filename"])
                    if q.get("expected_filename") is not None
                    else None
                ),
            )
            for q in data["queries"]
        ],
    )


def recall_at_k(ranked_filenames: list[list[str]], expected: list[str | None], k: int) -> float:
    """Fraksi kueri berjawaban yang dokumen benarnya muncul di top-k."""
    pairs = [
        (ranked[:k], exp)
        for ranked, exp in zip(ranked_filenames, expected, strict=True)
        if exp is not None
    ]
    if not pairs:
        return 0.0
    hits = sum(1 for ranked, exp in pairs if exp in ranked)
    return hits / len(pairs)


def mrr(ranked_filenames: list[list[str]], expected: list[str | None]) -> float:
    """Mean Reciprocal Rank dokumen benar (kueri berjawaban saja)."""
    scores: list[float] = []
    for ranked, exp in zip(ranked_filenames, expected, strict=True):
        if exp is None:
            continue
        for i, filename in enumerate(ranked, start=1):
            if filename == exp:
                scores.append(1.0 / i)
                break
        else:
            scores.append(0.0)
    return sum(scores) / len(scores) if scores else 0.0


def citation_correctness(
    top_citation_filenames: list[str | None], expected: list[str | None]
) -> float:
    """Fraksi kueri yang sitasi utamanya menunjuk dokumen yang benar."""
    pairs = [
        (cited, exp)
        for cited, exp in zip(top_citation_filenames, expected, strict=True)
        if exp is not None
    ]
    if not pairs:
        return 0.0
    return sum(1 for cited, exp in pairs if cited == exp) / len(pairs)


def no_answer_accuracy(
    answer_kinds: list[str], expected: list[str | None]
) -> float:
    """Fraksi kueri tanpa bukti yang benar-benar dijawab no-answer."""
    idx = [i for i, exp in enumerate(expected) if exp is None]
    if not idx:
        return 1.0
    correct = sum(1 for i in idx if answer_kinds[i] == "no_answer")
    return correct / len(idx)


def hallucination_rate(
    answer_kinds: list[str], expected: list[str | None]
) -> float:
    """Fraksi kueri tanpa bukti yang justru dijawab grounded (halusinasi)."""
    idx = [i for i, exp in enumerate(expected) if exp is None]
    if not idx:
        return 0.0
    wrong = sum(1 for i in idx if answer_kinds[i] != "no_answer")
    return wrong / len(idx)


def false_no_answer_rate(
    answer_kinds: list[str], expected: list[str | None]
) -> float:
    """Fraksi kueri berjawaban yang keliru dijawab no-answer (terlalu konservatif)."""
    idx = [i for i, exp in enumerate(expected) if exp is not None]
    if not idx:
        return 0.0
    wrong = sum(1 for i in idx if answer_kinds[i] == "no_answer")
    return wrong / len(idx)


def percentile(values: list[float], p: float) -> float:
    """Persentil (interpolasi linear) dari daftar nilai."""
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (p / 100.0) * (len(ordered) - 1)
    low = math.floor(rank)
    high = math.ceil(rank)
    if low == high:
        return ordered[int(rank)]
    frac = rank - low
    return ordered[low] * (1 - frac) + ordered[high] * frac


def estimate_tokens(text: str) -> int:
    """Estimasi token (~4 karakter/token, konsisten dengan chunking)."""
    return max(1, len(text) // 4)


def estimate_cost_usd(total_tokens: int, price_per_1k_tokens: float) -> float:
    """Estimasi biaya token (USD)."""
    return round(total_tokens / 1000.0 * price_per_1k_tokens, 6)
