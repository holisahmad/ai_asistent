"""Idempotensi request tulis (Fase 9).

Klien mengirim header `Idempotency-Key`; retry dengan key yang sama
mengembalikan respons tersimpan (bukan membuat resource duplikat).
Dipakai untuk endpoint tulis yang mahal/sensitif (upload, chat).
"""

import hashlib
import json
from typing import Annotated, Any

from ai_asistent_core.models import IdempotencyKey
from fastapi import Header
from sqlalchemy import select
from sqlalchemy.orm import Session

IdempotencyKeyHeader = Annotated[
    str | None,
    Header(
        alias="Idempotency-Key",
        max_length=200,
        description=(
            "Kunci idempotensi; request ulang dengan kunci sama "
            "mengembalikan respons tersimpan"
        ),
    ),
]


def hash_request(payload: bytes) -> str:
    """Hash isi request (deteksi pemakaian ulang kunci dengan body berbeda)."""
    return hashlib.sha256(payload).hexdigest()


def lookup(
    db: Session, *, user_id: str, endpoint: str, key: str
) -> dict[str, Any] | None:
    """Respons tersimpan untuk (user, endpoint, key), atau None."""
    row = db.execute(
        select(IdempotencyKey).where(
            IdempotencyKey.user_id == user_id,
            IdempotencyKey.endpoint == endpoint,
            IdempotencyKey.key == key,
        )
    ).scalar_one_or_none()
    if row is None or not row.response_json:
        return None
    try:
        data = json.loads(row.response_json)
    except json.JSONDecodeError:  # pragma: no cover - data korup
        return None
    return data if isinstance(data, dict) else None


def store(
    db: Session,
    *,
    user_id: str,
    endpoint: str,
    key: str,
    response: dict[str, Any],
    request_hash: str | None = None,
) -> None:
    """Simpan respons agar request ulang mengembalikan hasil yang sama."""
    db.add(
        IdempotencyKey(
            user_id=user_id,
            endpoint=endpoint,
            key=key,
            request_hash=request_hash,
            response_json=json.dumps(response, default=str, ensure_ascii=False),
        )
    )
    db.flush()
