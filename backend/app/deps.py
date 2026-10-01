"""Shared FastAPI dependencies: current user, RBAC roles, audit writer."""

import json
from collections.abc import Callable
from typing import Annotated

from ai_asistent_core.db import get_db
from ai_asistent_core.models import AuditEvent, AuthSession, Membership, User, utcnow
from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.security import hash_token

ROLE_ADMIN = "admin"
ROLE_EDITOR = "editor"
ROLE_CONTRIBUTOR = "contributor"
ROLE_VIEWER = "viewer"
ROLE_ORDER = [ROLE_VIEWER, ROLE_CONTRIBUTOR, ROLE_EDITOR, ROLE_ADMIN]

DbSession = Annotated[Session, Depends(get_db)]


def get_current_user(
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
    db: DbSession = None,  # type: ignore[assignment]
) -> User:
    """Resolve user dari header `Authorization: Bearer <token>`."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    token = authorization.removeprefix("Bearer ").strip()
    row = db.execute(
        select(AuthSession).where(AuthSession.token_hash == hash_token(token))
    ).scalar_one_or_none()
    if row is None or row.revoked_at is not None or row.expires_at <= utcnow():
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired session")
    user = db.get(User, row.user_id)
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User inactive")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def get_role(db: Session, user_id: str, workspace_id: str) -> str | None:
    """Kembalikan role user di workspace, atau None bila bukan anggota."""
    return db.execute(
        select(Membership.role).where(
            Membership.user_id == user_id, Membership.workspace_id == workspace_id
        )
    ).scalar_one_or_none()


def require_role(minimum: str) -> Callable[[str, User, Session], str]:
    """Dependency factory: cek role minimal di path param `workspace_id`.

    Bukan anggota -> 404 (anti enumeration); role kurang -> 403.
    """

    def _dep(workspace_id: str, current: CurrentUser, db: DbSession) -> str:
        role = get_role(db, current.id, workspace_id)
        if role is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Workspace not found")
        if ROLE_ORDER.index(role) < ROLE_ORDER.index(minimum):
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Requires role {minimum}+")
        return role

    return _dep


def audit(
    db: Session,
    *,
    action: str,
    workspace_id: str | None = None,
    user_id: str | None = None,
    target: str | None = None,
    meta: dict[str, object] | None = None,
) -> None:
    """Tulis satu audit event (append-only) ke tabel audit_events."""
    db.add(
        AuditEvent(
            action=action,
            workspace_id=workspace_id,
            user_id=user_id,
            target=target,
            metadata_json=json.dumps(meta, ensure_ascii=False) if meta else None,
        )
    )
