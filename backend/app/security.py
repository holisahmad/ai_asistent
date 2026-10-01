"""Password hashing (bcrypt) dan token session opaque + hash SHA-256."""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from bcrypt import checkpw, gensalt, hashpw

SESSION_TOKEN_BYTES = 32
DEFAULT_SESSION_TTL_HOURS = 24


def hash_password(password: str) -> str:
    """Hash password dengan bcrypt (cost default)."""
    return hashpw(password.encode("utf-8"), gensalt()).decode("ascii")


def verify_password(password: str, password_hash: str) -> bool:
    """Verifikasi password terhadap hash bcrypt."""
    try:
        return checkpw(password.encode("utf-8"), password_hash.encode("ascii"))
    except ValueError:
        return False


def new_session_token() -> str:
    """Token opaque acak untuk dikirim ke client (hanya tampil sekali)."""
    return secrets.token_urlsafe(SESSION_TOKEN_BYTES)


def hash_token(token: str) -> str:
    """SHA-256 hex dari token — yang disimpan di DB."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def session_expiry(now: datetime | None = None, hours: int = DEFAULT_SESSION_TTL_HOURS) -> datetime:
    """Waktu kedaluwarsa session."""
    return (now or datetime.now(UTC)) + timedelta(hours=hours)
