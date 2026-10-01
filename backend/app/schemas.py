"""Pydantic v2 request/response schemas untuk auth & workspace."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class RegisterIn(BaseModel):
    """Pendaftaran akun baru."""

    email: EmailStr
    name: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=8, max_length=128)


class LoginIn(BaseModel):
    """Login dengan email & password."""

    model_config = ConfigDict()

    email: EmailStr
    password: str


class SessionOut(BaseModel):
    """Token session opaque (hanya dikembalikan saat login/register)."""

    token: str
    expires_at: datetime


class UserOut(BaseModel):
    """Profil user."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    email: EmailStr
    name: str


class WorkspaceCreateIn(BaseModel):
    """Buat workspace baru."""

    name: str = Field(min_length=1, max_length=200)
    slug: str = Field(
        min_length=3,
        max_length=100,
        pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
        description="lowercase, angka, dash; tanpa spasi",
    )


class WorkspaceUpdateIn(BaseModel):
    """Update nama workspace."""

    name: str = Field(min_length=1, max_length=200)


class MemberAddIn(BaseModel):
    """Tambah anggota workspace dengan role."""

    email: EmailStr
    role: str = Field(pattern=r"^(admin|editor|contributor|viewer)$")


class MemberOut(BaseModel):
    """Anggota workspace."""

    model_config = ConfigDict(from_attributes=True)

    user_id: str
    email: EmailStr
    name: str
    role: str


class WorkspaceOut(BaseModel):
    """Detail workspace."""

    id: str
    name: str
    slug: str


class WorkspaceDetailOut(WorkspaceOut):
    """Workspace + daftar anggota."""

    members: list[MemberOut]
