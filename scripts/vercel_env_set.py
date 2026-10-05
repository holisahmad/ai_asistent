#!/usr/bin/env python3
"""Set semua env vars di Vercel via REST API.

Pemakaian:
    VERCEL_TOKEN=... VERCEL_PROJECT_ID=... python3 scripts/vercel_env_set.py
"""

import json
import os
import sys
import urllib.error
import urllib.request

TOKEN = os.environ.get("VERCEL_TOKEN", "")
PROJECT_ID = os.environ.get("VERCEL_PROJECT_ID", "prj_hyjBdtjujwvxGrgNo8pt37zs3bd4")
DB_URL = os.environ.get("SUPABASE_DB_URL", "")

if not TOKEN:
    print("ERROR: VERCEL_TOKEN tidak diset", file=sys.stderr)
    sys.exit(1)
if not DB_URL:
    print("ERROR: SUPABASE_DB_URL tidak diset", file=sys.stderr)
    sys.exit(1)

HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json",
}

VERCEL_DOMAIN = "https://ai-asistent-nu.vercel.app"

# Semua env vars yang akan diset (key, value, type, targets)
ENV_VARS = [
    # --- Frontend ---
    ("NEXT_PUBLIC_API_BASE", VERCEL_DOMAIN, "plain", ["production", "preview"]),

    # --- App core ---
    ("APP_ENVIRONMENT",            "production",       "encrypted", ["production"]),
    ("APP_LOG_LEVEL",              "INFO",             "encrypted", ["production"]),

    # --- Database (Supabase via pooler) ---
    ("APP_DATABASE_URL",           DB_URL,             "sensitive", ["production"]),

    # --- Redis (Upstash-compatible placeholder — update bila ada Redis prod) ---
    # Untuk MVP tanpa worker terpisah: bisa skip Redis dan disable queue
    # ("APP_REDIS_URL", "redis://...", "sensitive", ["production"]),

    # --- Embedding ---
    ("APP_EMBEDDING_PROVIDER",     "local",            "encrypted", ["production"]),
    ("APP_EMBEDDING_DIM",          "384",              "encrypted", ["production"]),

    # --- LLM ---
    ("APP_LLM_PROVIDER",           "local",            "encrypted", ["production"]),
    ("APP_OPENAI_CHAT_MODEL",      "gpt-4o-mini",      "encrypted", ["production"]),

    # --- Answer mode ---
    ("APP_ANSWER_MODE",            "auto",             "encrypted", ["production"]),
    ("APP_ANSWER_EXTRACTIVE_THRESHOLD", "0.40",        "encrypted", ["production"]),
    ("APP_ANSWER_MIN_MARGIN",      "0.05",             "encrypted", ["production"]),
    ("APP_ANSWER_MAX_CHARS",       "800",              "encrypted", ["production"]),

    # --- Retrieval ---
    ("APP_RETRIEVAL_TOP_K",        "6",                "encrypted", ["production"]),
    ("APP_RETRIEVAL_CANDIDATES",   "24",               "encrypted", ["production"]),
    ("APP_RETRIEVAL_MIN_SCORE",    "0.05",             "encrypted", ["production"]),
    ("APP_RERANKER_ENABLED",       "true",             "encrypted", ["production"]),
    ("APP_RERANKER_PROVIDER",      "lexical",          "encrypted", ["production"]),
    ("APP_RERANKER_TOP_N",         "0",                "encrypted", ["production"]),
    ("APP_RAG_MAX_CONTEXT_CHARS",  "6000",             "encrypted", ["production"]),

    # --- Web fallback (off by default) ---
    ("APP_WEB_FALLBACK_MODE",      "internal_only",    "encrypted", ["production"]),
    ("APP_WEB_SEARCH_PROVIDER",    "none",             "encrypted", ["production"]),

    # --- CORS ---
    ("APP_CORS_ORIGINS_CSV",       VERCEL_DOMAIN,      "encrypted", ["production"]),

    # --- Security ---
    ("APP_API_RATE_LIMIT_PER_MIN", "120",              "encrypted", ["production"]),
    ("APP_API_RATE_LIMIT_BURST",   "0",                "encrypted", ["production"]),
    ("APP_URL_VALIDATION_ENABLED", "true",             "encrypted", ["production"]),
    ("APP_URL_FETCH_MAX_BYTES",    "200000",           "encrypted", ["production"]),

    # --- Resilience ---
    ("APP_EXTERNAL_MAX_ATTEMPTS",  "3",                "encrypted", ["production"]),
    ("APP_EXTERNAL_RETRY_BASE_SECONDS", "0.5",         "encrypted", ["production"]),
    ("APP_EXTERNAL_RETRY_MAX_SECONDS",  "8.0",         "encrypted", ["production"]),
    ("APP_BREAKER_FAILURE_THRESHOLD",   "5",           "encrypted", ["production"]),
    ("APP_BREAKER_RECOVERY_SECONDS",    "60.0",        "encrypted", ["production"]),

    # --- Storage (MinIO — placeholder, update ke S3/prod storage bila ada) ---
    ("APP_MINIO_ENDPOINT",         "localhost:9000",   "encrypted", ["production"]),
    ("APP_MINIO_ACCESS_KEY",       "minioadmin",       "encrypted", ["production"]),
    ("APP_MINIO_SECRET_KEY",       "minioadmin",       "sensitive", ["production"]),
    ("APP_MINIO_BUCKET",           "ai-assistant",     "encrypted", ["production"]),
    ("APP_MINIO_SECURE",           "false",            "encrypted", ["production"]),
]


def api(method: str, path: str, body: dict | None = None) -> dict:
    """Simple Vercel API call."""
    url = f"https://api.vercel.com{path}"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, headers=HEADERS, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body_text = e.read().decode(errors="replace")
        return {"_error": e.code, "_body": body_text}


def get_existing_env_ids() -> dict[str, str]:
    """Ambil semua env ID yang sudah ada di project."""
    resp = api("GET", f"/v9/projects/{PROJECT_ID}/env?decrypt=false&limit=100")
    envs = resp.get("envs", [])
    return {e["key"]: e["id"] for e in envs}


def delete_env(env_id: str) -> None:
    api("DELETE", f"/v9/projects/{PROJECT_ID}/env/{env_id}")


def create_env(key: str, value: str, env_type: str, targets: list[str]) -> dict:
    # Vercel API type: "plain" | "encrypted" | "sensitive"
    # "sensitive" = encrypted + tidak bisa di-decrypt dari UI
    vtype = env_type if env_type in ("plain", "encrypted", "sensitive") else "encrypted"
    return api("POST", f"/v10/projects/{PROJECT_ID}/env", {
        "key": key,
        "value": value,
        "type": vtype,
        "target": targets,
    })


def main() -> None:
    print(f"Project: {PROJECT_ID}")
    print(f"Vars to set: {len(ENV_VARS)}")
    print("")

    print("Fetching existing env vars...")
    existing = get_existing_env_ids()
    print(f"  Found {len(existing)} existing vars")
    print("")

    ok_count = 0
    fail_count = 0

    for key, value, env_type, targets in ENV_VARS:
        # Hapus yang lama dulu (upsert)
        if key in existing:
            delete_env(existing[key])

        result = create_env(key, value, env_type, targets)

        if result.get("id") or result.get("created"):
            print(f"  ✓  {key}")
            ok_count += 1
        else:
            err = result.get("_body") or result.get("error", {})
            print(f"  ✗  {key} — {err}")
            fail_count += 1

    print("")
    print(f"Done: {ok_count} OK, {fail_count} FAIL")

    if fail_count > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
