#!/usr/bin/env python
"""Evaluasi kualitas RAG (Fase 6/10) — recall@k, sitasi, no-answer, latensi, biaya.

Pemakaian:
    uv run --project backend python scripts/eval_rag.py                 # LLM stub (deterministik)
    uv run --project backend python scripts/eval_rag.py --llm gateway   # pakai APP_LLM_PROVIDER dari .env
    uv run --project backend python scripts/eval_rag.py --write         # tulis laporan markdown
"""

import argparse
import os
import sys
import time
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))


def _inline_ingest(file_id: str, job_id: str) -> bool:
    """Jalankan pipeline langsung (tanpa worker RQ) untuk eval."""
    from ai_asistent_core.db import get_session_factory
    from ai_asistent_core.pipeline import ingest_file

    session = get_session_factory()()
    try:
        status = ingest_file(session, file_id, job_id)
        session.commit()
        return status == "indexed"
    finally:
        session.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluasi kualitas RAG")
    parser.add_argument(
        "--dataset", default=str(REPO / "docs/eval/retrieval_dataset.json")
    )
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument(
        "--llm", choices=["stub", "gateway"], default="stub", help="stub=deterministik, gateway=APP_LLM_PROVIDER"
    )
    parser.add_argument("--write", action="store_true", help="tulis laporan markdown")
    parser.add_argument("--price-per-1k", type=float, default=0.00015, help="USD per 1K token")
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="cetak peringkat kandidat & posisi dokumen harapan per kueri",
    )
    parser.add_argument(
        "--set",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help=(
            "override setting untuk perbandingan A/B, boleh berulang "
            "(mis. --set retrieval_top_k=3 --set reranker_enabled=true)"
        ),
    )
    args = parser.parse_args()

    if args.llm == "stub":
        os.environ["APP_LLM_PROVIDER"] = "local"

    # Override diterapkan setelah --llm agar nilai eksplisit --set menang.
    overrides: dict[str, str] = {}
    for item in args.set:
        if "=" not in item:
            parser.error(f"--set harus berformat KEY=VALUE, diterima: {item!r}")
        key, value = item.split("=", 1)
        env_key = key if key.startswith("APP_") else f"APP_{key.upper()}"
        os.environ[env_key] = value
        overrides[env_key] = value

    import app.api.routes.files as files_route

    files_route.enqueue_ingest = _inline_ingest  # type: ignore[assignment]

    from ai_asistent_core.db import get_session_factory
    from ai_asistent_core.eval import (
        citation_correctness,
        estimate_cost_usd,
        estimate_tokens,
        false_no_answer_rate,
        hallucination_rate,
        load_dataset,
        mrr,
        no_answer_accuracy,
        percentile,
        recall_at_k,
    )
    from ai_asistent_core.rag import answer_question, retrieve
    from fastapi.testclient import TestClient

    from app.main import create_app

    dataset = load_dataset(args.dataset)
    client = TestClient(create_app())

    email, password = "eval@local.dev", "password123"
    r = client.post(
        "/api/v1/auth/register",
        json={"email": email, "name": "Eval", "password": password},
    )
    if r.status_code != 201:
        r = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    headers = {"Authorization": f"Bearer {r.json()['token']}"}

    # Workspace khusus per dataset agar korpus reproducible dan tidak saling
    # menyilang antar dataset (nama berkas sama bisa menyebabkan salah satu
    # dokumen tersingkir saat seeding).
    ws_slug = f"eval-{dataset.name}"
    ws_id = next(
        (w["id"] for w in client.get("/api/v1/workspaces", headers=headers).json()
         if w.get("slug") == ws_slug),
        None,
    )
    if ws_id is None:
        ws_id = client.post(
            "/api/v1/workspaces",
            headers=headers,
            json={"name": f"Eval {dataset.name}", "slug": ws_slug},
        ).json()["id"]

    # Seed dokumen (idempoten: 409 dedup → pakai file yang sudah ada)
    existing = {
        f["filename"]: f["id"]
        for f in client.get(f"/api/v1/workspaces/{ws_id}/files", headers=headers).json()
    }
    seeded = 0
    for doc in dataset.documents:
        if doc.filename in existing:
            continue
        resp = client.post(
            f"/api/v1/workspaces/{ws_id}/files",
            headers=headers,
            files={"file": (doc.filename, BytesIO(doc.content.encode()), "text/markdown")},
        )
        if resp.status_code == 201:
            seeded += 1
    suffix = f", override={overrides}" if overrides else ""
    print(f"Dataset '{dataset.name}' v{dataset.version}: {seeded} dokumen baru disemai, "
          f"{len(dataset.queries)} kueri, LLM={args.llm}{suffix}")

    session = get_session_factory()()
    ranked_filenames: list[list[str]] = []
    top_citations: list[str | None] = []
    answer_kinds: list[str] = []
    latencies: list[float] = []
    total_tokens = 0
    per_query: list[dict[str, object]] = []
    try:
        for q in dataset.queries:
            t0 = time.perf_counter()
            hits = retrieve(session, ws_id, q.question, top_k=args.k)
            ranked_filenames.append([h.filename for h in hits])
            answer = answer_question(session, ws_id, q.question)
            elapsed = time.perf_counter() - t0
            latencies.append(elapsed)
            answer_kinds.append(answer.answer_kind)
            top_citations.append(answer.citations[0].filename if answer.citations else None)
            total_tokens += estimate_tokens(q.question) + sum(
                estimate_tokens(h.content) for h in hits
            ) + estimate_tokens(answer.text)
            per_query.append(
                {
                    "question": q.question,
                    "expected": q.expected_filename,
                    "kind": answer.answer_kind,
                    "top_citation": top_citations[-1],
                    "ranked": ranked_filenames[-1][: args.k],
                    "seconds": round(elapsed, 3),
                }
            )
    finally:
        session.close()

    expected = [q.expected_filename for q in dataset.queries]
    metrics = {
        f"recall@{args.k}": recall_at_k(ranked_filenames, expected, args.k),
        "mrr": mrr(ranked_filenames, expected),
        "citation_correctness": citation_correctness(top_citations, expected),
        "no_answer_accuracy": no_answer_accuracy(answer_kinds, expected),
        "hallucination_rate": hallucination_rate(answer_kinds, expected),
        "false_no_answer_rate": false_no_answer_rate(answer_kinds, expected),
        "latency_p50_s": percentile(latencies, 50),
        "latency_p95_s": percentile(latencies, 95),
        "total_tokens_est": total_tokens,
        "cost_usd_est": estimate_cost_usd(total_tokens, args.price_per_1k),
    }

    print("\n== Metrik ==")
    for key, value in metrics.items():
        print(f"  {key:24s} {value if isinstance(value, int) else round(float(value), 4)}")

    misses = [q for q in per_query if q["expected"] and q["top_citation"] != q["expected"]]
    if misses:
        print("\n== Kueri yang tidak tepat ==")
        for m in misses:
            print(f"  - {m['question']} (harap: {m['expected']}, dapat: {m['top_citation']})")

    if args.verbose:
        print("\n== Peringkat per kueri ==")
        for row in per_query:
            ranked = row["ranked"]
            exp = row["expected"]
            pos = ranked.index(exp) + 1 if exp and exp in ranked else None
            where = f"posisi {pos}" if pos else "TIDAK ADA di top-k"
            print(f"  - {row['question']}\n      harap {exp or '—'} ({where}) | {', '.join(ranked)}")

    if args.write:
        reports = REPO / "docs/reports"
        reports.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        out = reports / f"eval-{stamp}.md"
        lines = [
            f"# Laporan Evaluasi RAG — {stamp}",
            "",
            f"- Dataset: `{dataset.name}` v{dataset.version}",
            f"- LLM: `{args.llm}`",
            f"- Override: `{overrides or '—'}`",
            f"- Kueri: {len(dataset.queries)} ({(expected.count(None))} tanpa jawaban)",
            "",
            "## Metrik",
            "",
            "| Metrik | Nilai |",
            "| --- | --- |",
        ]
        lines += [
            f"| {k} | {v if isinstance(v, int) else round(float(v), 4)} |"
            for k, v in metrics.items()
        ]
        lines += [
            "",
            "## Detail per kueri",
            "",
            "| Kueri | Harapan | Posisi | Kind | Sitasi teratas |",
            "| --- | --- | --- | --- | --- |",
        ]
        for q in per_query:
            ranked = q["ranked"]
            exp = q["expected"]
            pos = ranked.index(exp) + 1 if exp and exp in ranked else None
            lines.append(
                f"| {q['question']} | {exp or '—'} | {pos or '—'} | {q['kind']} | "
                f"{q['top_citation'] or '—'} |"
            )
        out.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"\nLaporan ditulis: {out.relative_to(REPO)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
