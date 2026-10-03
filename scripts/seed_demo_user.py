#!/usr/bin/env python
"""Seed akun demo AI Knowledge Assistant.

Membuat akun demo kalau belum ada (idempotent) memakai endpoint auth yang
sama seperti skrip eval/bench, jadi tidak ada jalur login terpisah yang bisa
menyimpang dari aplikasi. Password diambil dari argumen/ENV — tidak ada
kredensial demo yang tertanam diam-diam di kode produksi.

Pemakaian:
    python3 scripts/seed_demo_user.py --email demo@local.dev --password 'rahasia123'
    # lewat Makefile:
    APP_DEMO_PASSWORD='rahasia123' make seed-demo

Exit code 0 bila akun siap dipakai, 1 bila gagal.
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

DEFAULT_EMAIL = "demo@local.dev"
DEFAULT_BASE_URL = "http://localhost:8000/api/v1"


def _post(url: str, payload):
    """POST JSON; kembalikan (status, body). Tidak melempar pada 4xx/jaringan."""
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode("utf-8")
            status = resp.status
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8")
        status = exc.code
    except (urllib.error.URLError, OSError) as exc:
        # API belum jalan / jaringan bermasalah -> status 0, tanpa traceback.
        return 0, {"error": "%s: %s" % (type(exc).__name__, exc)}
    try:
        body = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        body = {"raw": raw[:300]}
    return status, body


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed akun demo lokal")
    parser.add_argument(
        "--email", default=os.environ.get("APP_DEMO_EMAIL", DEFAULT_EMAIL)
    )
    parser.add_argument(
        "--password",
        default=os.environ.get("APP_DEMO_PASSWORD"),
        help="wajib diisi (atau set APP_DEMO_PASSWORD)",
    )
    parser.add_argument("--name", default="Demo User")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    args = parser.parse_args()

    if not args.password:
        print(
            "Password belum diberikan. Jalankan:\n"
            "  python3 scripts/seed_demo_user.py --password '<password-anda>'\n"
            "atau set APP_DEMO_PASSWORD di environment.",
            file=sys.stderr,
        )
        return 1
    if len(args.password) < 8:
        print("Password minimal 8 karakter.", file=sys.stderr)
        return 1

    auth = f"{args.base_url.rstrip('/')}/auth"

    # 1) Register — 201 berarti akun baru dibuat.
    status, _body = _post(
        f"{auth}/register",
        {"email": args.email, "name": args.name, "password": args.password},
    )
    if status == 201:
        print(f"Akun demo dibuat: {args.email}")
        return 0
    if status == 0:
        reason = _body.get("error") if isinstance(_body, dict) else None
        print(f"Tidak bisa menghubungi API di {auth}: {reason}", file=sys.stderr)
        print("Pastikan API sudah jalan: make api", file=sys.stderr)
        return 1

    # 2) Sudah ada (409/422) — verifikasi password lewat login.
    status, body = _post(
        f"{auth}/login", {"email": args.email, "password": args.password}
    )
    if status == 200 and isinstance(body, dict) and body.get("token"):
        print(f"Akun demo sudah ada & password cocok: {args.email}")
        return 0
    if status == 0:
        reason = body.get("error") if isinstance(body, dict) else None
        print(f"Tidak bisa menghubungi API di {auth}: {reason}", file=sys.stderr)
        print("Pastikan API sudah jalan: make api", file=sys.stderr)
        return 1

    detail = body.get("detail") if isinstance(body, dict) else None
    print(
        f"Gagal menyiapkan akun demo {args.email} "
        f"(register sudah terdaftar; login={status}). Detail: {detail}",
        file=sys.stderr,
    )
    print(
        "Email sudah terdaftar dengan password lain? Pilih password baru atau "
        "pakai --email lain. Periksa juga log API: make seed-demo",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
