#!/usr/bin/env python3
"""Configure Vercel project settings dan trigger production deployment.

Pemakaian:
    VERCEL_TOKEN=... python3 scripts/vercel_deploy.py
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request

TOKEN = os.environ.get("VERCEL_TOKEN", "")
PROJECT_ID = os.environ.get("VERCEL_PROJECT_ID", "prj_hyjBdtjujwvxGrgNo8pt37zs3bd4")
GITHUB_REPO = "holisahmad/ai_asistent"

if not TOKEN:
    print("ERROR: VERCEL_TOKEN tidak diset", file=sys.stderr)
    sys.exit(1)

HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json",
}


def api(method: str, path: str, body: dict | None = None) -> dict:
    url = f"https://api.vercel.com{path}"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, headers=HEADERS, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body_text = e.read().decode(errors="replace")
        return {"_error": e.code, "_body": body_text}


def step(msg: str) -> None:
    print(f"\n>> {msg}")


def ok(msg: str) -> None:
    print(f"  ✓  {msg}")


def warn(msg: str) -> None:
    print(f"  ⚠  {msg}")


def main() -> None:
    print("=" * 60)
    print("Vercel Project Config + Deploy")
    print("=" * 60)

    # ---- 1. Get project info ----
    step("1. Cek project info")
    proj = api("GET", f"/v9/projects/{PROJECT_ID}")
    if proj.get("_error"):
        print(f"  ERROR: {proj['_body']}")
        sys.exit(1)

    proj_name = proj.get("name", "?")
    ok(f"Project: {proj_name} ({PROJECT_ID})")

    # ---- 2. Update project settings ----
    step("2. Update project settings")
    update = api("PATCH", f"/v9/projects/{PROJECT_ID}", {
        "rootDirectory": "frontend",
        "buildCommand": "npm run build",
        "outputDirectory": ".next",
        "installCommand": "npm ci",
        "framework": "nextjs",
        "nodeVersion": "22.x",
    })

    if update.get("_error"):
        warn(f"Project update error: {update.get('_body', '')[:200]}")
    else:
        ok("rootDirectory=frontend, framework=nextjs, node=22.x")

    # ---- 3. Cek GitHub integration ----
    step("3. Cek GitHub repo integration")
    link = proj.get("link", {})
    repo = link.get("repo", "") or link.get("repoId", "")
    if repo:
        ok(f"GitHub repo terhubung: {repo}")
        has_github = True
    else:
        warn("GitHub repo belum terhubung ke project ini")
        warn("Gunakan Vercel CLI untuk deploy: vercel --prod --cwd frontend")
        has_github = False

    # ---- 4. Trigger deployment ----
    step("4. Trigger production deployment")

    if has_github:
        # Trigger via GitHub integration
        deploy = api("POST", "/v13/deployments", {
            "name": proj_name,
            "target": "production",
            "gitSource": {
                "type": "github",
                "org": "holisahmad",
                "repo": "ai_asistent",
                "ref": "main",
            },
        })
    else:
        # Trigger via project redeploy API
        deploy = api("POST", f"/v9/projects/{PROJECT_ID}/deployments", {
            "target": "production",
        })

    deploy_id = deploy.get("id", "")
    deploy_url = deploy.get("url", "")
    deploy_err = deploy.get("_error")

    if deploy_err or not deploy_id:
        body = deploy.get("_body", "")
        # Parse error message
        try:
            err_json = json.loads(body)
            err_msg = err_json.get("error", {}).get("message", body[:300])
        except Exception:
            err_msg = body[:300]

        warn(f"Deploy trigger gagal: {err_msg}")
        print("")
        print("  → Jalankan manual di terminal:")
        print("    cd /Users/macbookpro/www/ai_asistent/frontend")
        print("    npx vercel --prod --token $VERCEL_TOKEN")
        return

    ok(f"Deploy triggered: {deploy_id}")
    if deploy_url:
        ok(f"URL: https://{deploy_url}")

    # ---- 5. Poll deployment status ----
    step("5. Monitor deployment status (max 3 menit)")
    print("  (Ctrl+C untuk skip polling, deploy tetap berjalan di background)")

    for i in range(36):  # 36 × 5s = 3 menit
        time.sleep(5)
        status_resp = api("GET", f"/v13/deployments/{deploy_id}")
        state = status_resp.get("readyState", status_resp.get("status", "?"))
        ready_url = status_resp.get("url", "")

        print(f"  [{(i+1)*5:3d}s] state={state}")

        if state in ("READY", "ready"):
            ok(f"Deploy READY: https://{ready_url}")
            break
        elif state in ("ERROR", "error", "CANCELED", "canceled"):
            warn(f"Deploy gagal: {state}")
            err_detail = status_resp.get("errorMessage", "")
            if err_detail:
                warn(f"Error: {err_detail}")
            break
    else:
        print("  Timeout polling — deploy masih berjalan di background")
        print(f"  Cek: https://vercel.com/holisahmad/{proj_name}/deployments")

    # ---- Summary ----
    print("")
    print("=" * 60)
    print("SELESAI")
    print(f"  Dashboard: https://vercel.com/holisahmad/{proj_name}")
    print(f"  App:       https://ai-asistent-nu.vercel.app")
    print(f"  Supabase:  https://supabase.com/dashboard/project/nykffalzlxbmuatxgbhb")
    print("=" * 60)


if __name__ == "__main__":
    main()
