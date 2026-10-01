"""Auth endpoints: /api/v1/auth/register, /login, /logout, /me."""

from datetime import UTC, datetime

from ai_asistent_core.models import AuthSession, User
from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit as audit_mod
from app.deps import CurrentUser, DbSession, audit
from app.schemas import LoginIn, RegisterIn, SessionOut, UserOut
from app.security import (
    hash_password,
    hash_token,
    new_session_token,
    session_expiry,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def _create_session(db: Session, user: User) -> tuple[str, datetime]:
    """Buat session baru; kembalikan (token mentah, expires_at)."""
    token = new_session_token()
    expires_at = session_expiry(datetime.now(UTC))
    db.add(
        AuthSession(user_id=user.id, token_hash=hash_token(token), expires_at=expires_at)
    )
    return token, expires_at


@router.post("/register", response_model=SessionOut, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterIn, db: DbSession) -> SessionOut:
    """Daftar akun baru; langsung login (dapatkan token)."""
    exists = db.execute(
        select(User).where(User.email == payload.email.lower())
    ).scalar_one_or_none()
    if exists is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Email already registered")

    user = User(
        email=payload.email.lower(),
        name=payload.name,
        password_hash=hash_password(payload.password),
    )
    db.add(user)
    db.flush()

    token, expires_at = _create_session(db, user)
    audit(db, action="auth.register", user_id=user.id, target=user.email)
    audit_mod.write_audit_log(
        {"action": "auth.register", "user_id": user.id, "target": user.email}
    )
    return SessionOut(token=token, expires_at=expires_at)


@router.post("/login", response_model=SessionOut)
def login(payload: LoginIn, db: DbSession) -> SessionOut:
    """Login email+password; buat session baru."""
    user = db.execute(
        select(User).where(User.email == payload.email.lower())
    ).scalar_one_or_none()
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")
    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Account disabled")

    token, expires_at = _create_session(db, user)
    audit(db, action="auth.login", user_id=user.id, target=user.email)
    audit_mod.write_audit_log(
        {"action": "auth.login", "user_id": user.id, "target": user.email}
    )
    return SessionOut(token=token, expires_at=expires_at)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(current: CurrentUser, db: DbSession) -> None:
    """Revoke semua session aktif milik user (sederhana & aman)."""
    now = datetime.now(UTC)
    sessions = db.execute(
        select(AuthSession).where(
            AuthSession.user_id == current.id, AuthSession.revoked_at.is_(None)
        )
    ).scalars().all()
    for s in sessions:
        if s.expires_at > now:
            s.revoked_at = now
    audit(db, action="auth.logout", user_id=current.id, target=current.email)
    audit_mod.write_audit_log({"action": "auth.logout", "user_id": current.id})


@router.get("/me", response_model=UserOut)
def me(current: CurrentUser) -> UserOut:
    """Profil user yang sedang login."""
    return UserOut(id=current.id, email=current.email, name=current.name)
