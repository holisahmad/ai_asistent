"""Workspace & membership endpoints dengan RBAC."""

import re

from ai_asistent_core.models import Membership, User, Workspace
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select

from app import audit as audit_mod
from app.deps import CurrentUser, DbSession, audit, get_role, require_role
from app.schemas import (
    MemberAddIn,
    MemberOut,
    WorkspaceCreateIn,
    WorkspaceDetailOut,
    WorkspaceOut,
    WorkspaceUpdateIn,
)

router = APIRouter(prefix="/workspaces", tags=["workspaces"])

_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug[:100]


@router.post("", response_model=WorkspaceOut, status_code=status.HTTP_201_CREATED)
def create_workspace(
    payload: WorkspaceCreateIn, current: CurrentUser, db: DbSession
) -> WorkspaceOut:
    """Buat workspace; pembuat otomatis menjadi admin."""
    slug = payload.slug
    if db.execute(select(Workspace).where(Workspace.slug == slug)).scalar_one_or_none():
        raise HTTPException(status.HTTP_409_CONFLICT, "Slug already taken")

    ws = Workspace(name=payload.name, slug=slug)
    db.add(ws)
    db.flush()
    db.add(Membership(user_id=current.id, workspace_id=ws.id, role="admin"))
    audit(db, action="workspace.create", workspace_id=ws.id, user_id=current.id, target=slug)
    audit_mod.write_audit_log(
        {"action": "workspace.create", "workspace_id": ws.id, "user_id": current.id, "target": slug}
    )
    return WorkspaceOut(id=ws.id, name=ws.name, slug=ws.slug)


@router.get("", response_model=list[WorkspaceOut])
def list_workspaces(current: CurrentUser, db: DbSession) -> list[WorkspaceOut]:
    """Daftar workspace tempat user menjadi anggota."""
    rows = db.execute(
        select(Workspace)
        .join(Membership, Membership.workspace_id == Workspace.id)
        .where(Membership.user_id == current.id)
        .order_by(Workspace.created_at)
    ).scalars().all()
    return [WorkspaceOut(id=w.id, name=w.name, slug=w.slug) for w in rows]


@router.get("/{workspace_id}", response_model=WorkspaceDetailOut)
def get_workspace(
    workspace_id: str,
    current: CurrentUser,
    db: DbSession,
    role: str = Depends(require_role("viewer")),
) -> WorkspaceDetailOut:
    """Detail workspace + anggota. Bukan anggota → 404 (anti enumeration)."""
    ws = db.get(Workspace, workspace_id)
    if ws is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workspace not found")
    members = db.execute(
        select(Membership, User)
        .join(User, User.id == Membership.user_id)
        .where(Membership.workspace_id == workspace_id)
    ).all()
    return WorkspaceDetailOut(
        id=ws.id,
        name=ws.name,
        slug=ws.slug,
        members=[
            MemberOut(user_id=u.id, email=u.email, name=u.name, role=m.role)
            for m, u in members
        ],
    )


@router.patch("/{workspace_id}", response_model=WorkspaceOut)
def update_workspace(
    workspace_id: str,
    payload: WorkspaceUpdateIn,
    current: CurrentUser,
    db: DbSession,
    role: str = Depends(require_role("admin")),
) -> WorkspaceOut:
    """Ubah nama workspace (admin saja)."""
    ws = db.get(Workspace, workspace_id)
    if ws is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workspace not found")
    ws.name = payload.name
    audit(db, action="workspace.update", workspace_id=ws.id, user_id=current.id, target=ws.slug)
    audit_mod.write_audit_log(
        {"action": "workspace.update", "workspace_id": ws.id, "user_id": current.id}
    )
    return WorkspaceOut(id=ws.id, name=ws.name, slug=ws.slug)


@router.post(
    "/{workspace_id}/members",
    response_model=MemberOut,
    status_code=status.HTTP_201_CREATED,
)
def add_member(
    workspace_id: str,
    payload: MemberAddIn,
    current: CurrentUser,
    db: DbSession,
    role: str = Depends(require_role("admin")),
) -> MemberOut:
    """Tambah anggota (admin saja)."""
    ws = db.get(Workspace, workspace_id)
    if ws is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workspace not found")
    user = db.execute(select(User).where(User.email == payload.email.lower())).scalar_one_or_none()
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User with that email not found")
    if get_role(db, user.id, workspace_id) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Already a member")

    db.add(Membership(user_id=user.id, workspace_id=workspace_id, role=payload.role))
    audit(
        db,
        action="workspace.member_add",
        workspace_id=workspace_id,
        user_id=current.id,
        target=user.email,
        meta={"role": payload.role},
    )
    audit_mod.write_audit_log(
        {"action": "workspace.member_add", "workspace_id": workspace_id,
         "user_id": current.id, "target": user.email, "role": payload.role}
    )
    return MemberOut(user_id=user.id, email=user.email, name=user.name, role=payload.role)


@router.delete("/{workspace_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_member(
    workspace_id: str,
    user_id: str,
    current: CurrentUser,
    db: DbSession,
    role: str = Depends(require_role("admin")),
) -> None:
    """Hapus anggota (admin saja). Admin terakhir tidak boleh dihapus."""
    ws = db.get(Workspace, workspace_id)
    if ws is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workspace not found")
    target = db.execute(
        select(Membership).where(
            Membership.workspace_id == workspace_id, Membership.user_id == user_id
        )
    ).scalar_one_or_none()
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Member not found")
    if target.role == "admin":
        admins = db.execute(
            select(Membership).where(
                Membership.workspace_id == workspace_id, Membership.role == "admin"
            )
        ).scalars().all()
        if len(admins) <= 1:
            raise HTTPException(status.HTTP_409_CONFLICT, "Cannot remove the last admin")

    db.delete(target)
    audit(
        db,
        action="workspace.member_remove",
        workspace_id=workspace_id,
        user_id=current.id,
        target=user_id,
    )
    audit_mod.write_audit_log(
        {"action": "workspace.member_remove", "workspace_id": workspace_id,
         "user_id": current.id, "target": user_id}
    )
