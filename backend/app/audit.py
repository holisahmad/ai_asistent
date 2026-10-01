"""Audit logging: DB rows + JSONL file sink for operations.

Fase 2 requirement (roadmap): audit event untuk upload, delete, reindex,
chat, dan perubahan setting. Event ditulis ke tabel audit_events dan
dicadangkan ke file JSONL terpisah agar operasi bisa tailing log.
"""

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger("app.audit")

_audit_logger = logging.getLogger("app.audit.jsonl")
_audit_logger.setLevel(logging.INFO)
_audit_logger.propagate = False

_FILE_CONFIGURED = False


def configure_audit_logging(path: str | None) -> None:
    """Pasang file handler JSONL untuk audit (sekali saja)."""
    global _FILE_CONFIGURED
    if _FILE_CONFIGURED or not path:
        return
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(path, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(message)s"))
    _audit_logger.addHandler(handler)
    _FILE_CONFIGURED = True


def write_audit_log(event: dict[str, Any]) -> None:
    """Log event audit ke file JSONL (backup dari tabel audit_events)."""
    entry = {"timestamp": datetime.now(UTC).isoformat(), **event}
    _audit_logger.info(json.dumps(entry, ensure_ascii=False, default=str))
    logger.debug("audit: %s", entry["action"])
