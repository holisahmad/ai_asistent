"""Unit test fungsi security (tanpa DB/API)."""

from app.security import hash_password, hash_token, new_session_token, verify_password


def test_password_hash_roundtrip() -> None:
    hashed = hash_password("s3cret-pass")
    assert hashed != "s3cret-pass"
    assert verify_password("s3cret-pass", hashed) is True
    assert verify_password("wrong-pass", hashed) is False


def test_password_hash_is_salted() -> None:
    assert hash_password("same") != hash_password("same")


def test_token_hash_is_deterministic_sha256() -> None:
    token = new_session_token()
    assert len(token) >= 32
    assert hash_token(token) == hash_token(token)
    assert len(hash_token(token)) == 64
