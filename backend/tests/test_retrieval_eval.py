"""Quality gate retrieval & answer (Fase 6/10) dijalankan di CI.

Memakai dataset `docs/eval/retrieval_dataset.json` dan LLM stub
deterministik, sehingga hasilnya reproducible tanpa API eksternal.
"""

import uuid
from io import BytesIO
from pathlib import Path
from typing import Any

from ai_asistent_core.db import get_session_factory
from ai_asistent_core.eval import (
    citation_correctness,
    false_no_answer_rate,
    hallucination_rate,
    load_dataset,
    mrr,
    no_answer_accuracy,
    recall_at_k,
)
from ai_asistent_core.llm import LocalStubLLM
from ai_asistent_core.rag import answer_question, retrieve

WS = "/api/v1/workspaces"
DATASET = Path(__file__).resolve().parents[2] / "docs" / "eval" / "retrieval_dataset.json"
K = 5


def _mk_user(client: Any, email: str) -> dict[str, str]:
    r = client.post(
        "/api/v1/auth/register",
        json={"email": email, "name": email.split("@")[0], "password": "password123"},
    )
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _mk_ws(client: Any, headers: dict[str, str]) -> str:
    r = client.post(
        WS,
        headers=headers,
        json={"name": "Eval", "slug": f"eval-{uuid.uuid4().hex[:8]}"},
    )
    return r.json()["id"]


def test_retrieval_and_answer_quality_gate(
    client: Any, ingest_mode: list[Any], monkeypatch: Any
) -> None:
    """Gerbang kualitas: recall@5, sitasi, no-answer, dan halusinasi."""
    import ai_asistent_core.rag as rag_mod

    monkeypatch.setattr(rag_mod, "get_llm_provider", lambda: LocalStubLLM())

    dataset = load_dataset(DATASET)
    headers = _mk_user(client, "eval-gate@example.com")
    ws_id = _mk_ws(client, headers)
    for doc in dataset.documents:
        resp = client.post(
            f"{WS}/{ws_id}/files",
            headers=headers,
            files={"file": (doc.filename, BytesIO(doc.content.encode()), "text/markdown")},
        )
        assert resp.status_code == 201, resp.text

    expected: list[str | None] = []
    ranked: list[list[str]] = []
    citations: list[str | None] = []
    kinds: list[str] = []

    session = get_session_factory()()
    try:
        for query in dataset.queries:
            hits = retrieve(session, ws_id, query.question, top_k=K)
            ranked.append([h.filename for h in hits])
            answer = answer_question(session, ws_id, query.question)
            expected.append(query.expected_filename)
            kinds.append(answer.answer_kind)
            citations.append(answer.citations[0].filename if answer.citations else None)
    finally:
        session.close()

    recall = recall_at_k(ranked, expected, K)
    citation_acc = citation_correctness(citations, expected)
    no_answer_acc = no_answer_accuracy(kinds, expected)
    halluc = hallucination_rate(kinds, expected)

    assert recall >= 0.8, f"recall@{K} terlalu rendah: {recall:.3f}"
    assert mrr(ranked, expected) >= 0.6, f"MRR terlalu rendah: {mrr(ranked, expected):.3f}"
    assert citation_acc >= 0.8, f"akurasi sitasi terlalu rendah: {citation_acc:.3f}"
    assert no_answer_acc == 1.0, f"no-answer gagal untuk kueri tanpa bukti: {no_answer_acc:.3f}"
    assert halluc <= 0.0, f"ada jawaban grounded pada kueri tanpa bukti: {halluc:.3f}"
    over_cautious = false_no_answer_rate(kinds, expected)
    assert over_cautious <= 0.2, (
        f"terlalu sering no-answer pada kueri berjawaban: {over_cautious:.3f}"
    )


def test_dataset_is_well_formed() -> None:
    """Dataset harus punya dokumen & kueri no-answer (kunci evaluasi)."""
    dataset = load_dataset(DATASET)
    assert len(dataset.documents) >= 5
    assert len(dataset.queries) >= 10
    assert any(q.expected_filename is None for q in dataset.queries)
    assert all(
        q.expected_filename is None
        or q.expected_filename in {d.filename for d in dataset.documents}
        for q in dataset.queries
    )
