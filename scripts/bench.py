#!/usr/bin/env python
"""Benchmark p50/p95/p99 & throughput (Fase 9/10).

Mengukur dua tahap terpisah agar bottleneck terlihat:
  1. retrieval hybrid (dense + keyword + fusi)
  2. chat penuh (retrieval + LLM + sitasi)

Pemakaian:
    uv run --project backend python scripts/bench.py --iterations 30
    uv run --project backend python scripts/bench.py --llm gateway --iterations 10
"""

import argparse
import os
import sys
import time
from io import BytesIO
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))


def _inline_ingest(file_id: str, job_id: str) -> bool:
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
    parser = argparse.ArgumentParser(description="Benchmark retrieval & chat")
    parser.add_argument("--iterations", type=int, default=30)
    parser.add_argument("--llm", choices=["stub", "gateway"], default="stub")
    parser.add_argument("--price-per-1k", type=float, default=0.00015)
    parser.add_argument("--dataset", default=str(REPO / "docs/eval/retrieval_dataset.json"))
    parser.add_argument(
        "--set",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help=(
            "override setting untuk perbandingan A/B, boleh berulang "
            "(mis. --set reranker_enabled=false --set answer_mode=extractive)"
        ),
    )
    args = parser.parse_args()

    if args.llm == "stub":
        os.environ["APP_LLM_PROVIDER"] = "local"

    # Override settings via env vars — diterapkan setelah --llm agar --set menang.
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
    from ai_asistent_core.eval import estimate_cost_usd, estimate_tokens, load_dataset, percentile
    from ai_asistent_core.rag import answer_question, retrieve
    from fastapi.testclient import TestClient

    from app.main import create_app

    dataset = load_dataset(args.dataset)
    client = TestClient(create_app())
    email, password = "bench@local.dev", "password123"
    r = client.post(
        "/api/v1/auth/register",
        json={"email": email, "name": "Bench", "password": password},
    )
    if r.status_code != 201:
        r = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    headers = {"Authorization": f"Bearer {r.json()['token']}"}

    ws_id = None
    for w in client.get("/api/v1/workspaces", headers=headers).json():
        ws_id = w["id"]
        break
    if ws_id is None:
        ws_id = client.post(
            "/api/v1/workspaces", headers=headers, json={"name": "Bench", "slug": "bench-ws"}
        ).json()["id"]

    existing = {
        f["filename"]
        for f in client.get(f"/api/v1/workspaces/{ws_id}/files", headers=headers).json()
    }
    seeded = 0
    for doc in dataset.documents:
        if doc.filename in existing:
            continue
        client.post(
            f"/api/v1/workspaces/{ws_id}/files",
            headers=headers,
            files={"file": (doc.filename, BytesIO(doc.content.encode()), "text/markdown")},
        )

    suffix = f", override={overrides}" if overrides else ""
    print(
        f"Benchmark — LLM={args.llm}, iterasi={args.iterations}, "
        f"kueri unik={len([q for q in dataset.queries if q.expected_filename])}{suffix}"
    )

    questions = [q.question for q in dataset.queries if q.expected_filename]

    session = get_session_factory()()
    retrieval_times: list[float] = []
    chat_times: list[float] = []
    tokens = 0
    try:
        # Warmup (cache & koneksi)
        for q in questions[:3]:
            retrieve(session, ws_id, q, top_k=5)
            answer_question(session, ws_id, q)

        for i in range(args.iterations):
            q = questions[i % len(questions)]
            t0 = time.perf_counter()
            hits = retrieve(session, ws_id, q, top_k=5)
            retrieval_times.append(time.perf_counter() - t0)

            t1 = time.perf_counter()
            answer = answer_question(session, ws_id, q)
            chat_times.append(time.perf_counter() - t1)
            tokens += (
                estimate_tokens(q)
                + sum(estimate_tokens(h.content) for h in hits)
                + estimate_tokens(answer.text)
            )
    finally:
        session.close()

    total_secs = sum(retrieval_times) + sum(chat_times)
    width = 62
    print("=" * width)
    print(f"Benchmark RAG — LLM={args.llm}, iterasi={args.iterations}, kueri unik={len(questions)}")
    if overrides:
        print(f"Override: {overrides}")
    print("=" * width)
    print(f"{'tahap':<12} {'p50 (ms)':>10} {'p95 (ms)':>10} {'p99 (ms)':>10} {'mean (ms)':>11}")
    for label, values in (("retrieval", retrieval_times), ("chat+LLM", chat_times)):
        print(
            f"{label:<12} {percentile(values, 50) * 1000:>10.1f} "
            f"{percentile(values, 95) * 1000:>10.1f} {percentile(values, 99) * 1000:>10.1f} "
            f"{(sum(values) / len(values)) * 1000:>11.1f}"
        )
    print("-" * width)
    print(f"throughput  : {args.iterations / total_secs:.2f} kueri/detik (end-to-end, 1 proses)")
    print(f"token (est) : {tokens} ≈ ${estimate_cost_usd(tokens, args.price_per_1k)} "
          f"@ ${args.price_per_1k}/1K token")
    print("=" * width)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
