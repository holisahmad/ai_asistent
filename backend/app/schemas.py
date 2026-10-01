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


# --- Fase 3: files ---


class FileOut(BaseModel):
    """Metadata file; storage_key untuk debug, akses via /download."""

    id: str
    workspace_id: str
    filename: str
    size_bytes: int
    mime_type: str
    checksum_sha256: str
    status: str
    error: str | None
    current_version: int
    created_at: datetime
    storage_key: str


class FileStatusOut(BaseModel):
    """Respons singkat perubahan status (cancel/delete/reindex)."""

    id: str
    status: str


# --- Fase 6: chat & RAG ---


class ChatCreateIn(BaseModel):
    """Pertanyaan baru (chat dibuat otomatis; title dari pertanyaan)."""

    question: str = Field(min_length=1, max_length=4000)
    chat_id: str | None = Field(
        default=None, description="Lanjutkan chat yang ada (opsional)"
    )


class CitationOut(BaseModel):
    """Sitasi klikabel (file + locator + potongan pendukung)."""

    idx: int
    chunk_id: str
    file_id: str
    filename: str
    locator_type: str
    locator_start: int
    locator_end: int
    snippet: str
    score: float


class MessageOut(BaseModel):
    """Pesan chat (user/assistant) + sitasi untuk jawaban assistant."""

    id: str
    role: str
    content: str
    answer_kind: str | None
    citations: list[CitationOut]
    created_at: datetime


class ChatOut(BaseModel):
    """Ringkasan chat untuk daftar."""

    id: str
    title: str
    created_at: datetime
    message_count: int


class ChatDetailOut(ChatOut):
    """Chat + seluruh pesan berurutan."""

    messages: list[MessageOut]
