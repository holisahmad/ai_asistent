"""Test unit Fase 10 — metrik evaluasi retrieval & answer."""

from ai_asistent_core.eval import (
    citation_correctness,
    estimate_cost_usd,
    estimate_tokens,
    false_no_answer_rate,
    hallucination_rate,
    mrr,
    no_answer_accuracy,
    percentile,
    recall_at_k,
)


def test_recall_at_k_counts_hits_within_top_k() -> None:
    ranked = [["a.md", "b.md"], ["y.md", "x.md"], ["c.md"]]
    expected = ["a.md", "x.md", None]
    assert recall_at_k(ranked, expected, k=5) == 1.0
    # k=1: dokumen benar "x.md" ada di peringkat 2 → hanya 1 dari 2 yang cocok
    assert recall_at_k(ranked, expected, k=1) == 0.5
    # Kueri tanpa jawaban tidak dihitung
    assert recall_at_k([["b.md"]], [None], k=5) == 0.0


def test_mrr_rewards_earlier_position() -> None:
    assert mrr([["a.md", "b.md"]], ["a.md"]) == 1.0
    assert mrr([["b.md", "a.md"]], ["a.md"]) == 0.5
    assert mrr([["b.md"]], ["a.md"]) == 0.0


def test_citation_correctness_and_no_answer_metrics() -> None:
    cited = ["a.md", "wrong.md", None]
    expected = ["a.md", "b.md", None]
    assert citation_correctness(cited, expected) == 0.5
    kinds = ["grounded", "grounded", "no_answer"]
    assert no_answer_accuracy(kinds, expected) == 1.0
    assert hallucination_rate(kinds, expected) == 0.0
    assert false_no_answer_rate(kinds, expected) == 0.0

    # Terlalu konservatif: kueri berjawaban dijawab no-answer (1 dari 2 hilang),
    # tetapi kueri tanpa bukti tetap benar di-no-answer.
    over_cautious = ["grounded", "no_answer", "no_answer"]
    assert no_answer_accuracy(over_cautious, expected) == 1.0
    assert hallucination_rate(over_cautious, expected) == 0.0
    assert false_no_answer_rate(over_cautious, expected) == 0.5


def test_percentile_interpolates() -> None:
    values = [1.0, 2.0, 3.0, 4.0]
    assert percentile(values, 50) == 2.5
    assert percentile(values, 0) == 1.0
    assert percentile(values, 100) == 4.0
    assert percentile([], 95) == 0.0
    assert percentile([7.0], 95) == 7.0


def test_token_and_cost_estimation() -> None:
    assert estimate_tokens("abcd" * 10) == 10
    assert estimate_tokens("") == 1  # minimum 1 token
    assert estimate_cost_usd(1000, 0.00015) == 0.00015
    assert estimate_cost_usd(0, 0.00015) == 0.0
