"""File endpoints — Fase 3: upload, list, detail, download, cancel, delete, reindex.

- Validasi: ekstensi allowlist, ukuran max, isi tidak kosong.
- Checksum sha256 untuk dedup dalam satu workspace.
- Binary di MinIO via storage adapter; metadata di Postgres.
- Status: queued | processing | indexed | failed | deleted.
"""

import hashlib
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, status
from fastapi import File as FileParam
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit as audit_mod
from app.deps import CurrentUser, DbSession, audit, require_role
from app.models import FILE_STATUSES, File, FileVersion, IngestionJob, utcnow
from app.schemas import FileOut, FileStatusOut
from app.settings import get_settings
from app.storage import get_storage, object_key

router = APIRouter(prefix="/workspaces/{workspace_id}/files", tags=["files"])

ALLOWED_EXTENSIONS = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".csv": "text/csv",
    ".html": "text/html",
    ".json": "application/json",
}


def _ext_of(filename: str) -> str:
    return ("." + filename.rsplit(".", 1)[-1].lower()) if "." in filename else ""


def _validate_size_and_ext(filename: str, size: int) -> tuple[str, str]:
    """Validasi ekstensi & ukuran; kembalikan (ext, mime)."""
    settings = get_settings()
    ext = _ext_of(filename)
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            f"Extension {ext or '(none)'} not allowed. Allowed: {sorted(ALLOWED_EXTENSIONS)}",
        )
    if size == 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Empty file")
    if size > settings.max_upload_bytes:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"File exceeds max size {settings.max_upload_bytes} bytes",
        )
    return ext, ALLOWED_EXTENSIONS[ext]


def _read_bounded(upload: UploadFile) -> bytes:
    """Baca maksimal max_upload_bytes+1 byte agar memori terbatas."""
    limit = get_settings().max_upload_bytes + 1
    return upload.file.read(limit)


def _get_file_or_404(db: Session, workspace_id: str, file_id: str) -> File:
    f = db.execute(
        select(File).where(
            File.id == file_id,
            File.workspace_id == workspace_id,
            File.is_deleted.is_(False),
        )
    ).scalar_one_or_none()
    if f is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found")
    return f


def _current_version_or_raise(db: Session, f: File) -> FileVersion:
    v = db.execute(
        select(FileVersion).where(
            FileVersion.file_id == f.id, FileVersion.version == f.current_version
        )
    ).scalar_one_or_none()
    if v is None:  # pragma: no cover - inkonsistensi data tidak diharapkan
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Missing file version")
    return v


def _file_out(f: File, storage_key: str) -> FileOut:
    return FileOut(
        id=f.id,
        workspace_id=f.workspace_id,
        filename=f.filename,
        size_bytes=f.size_bytes,
        mime_type=f.mime_type,
        checksum_sha256=f.checksum_sha256,
        status=f.status,
        error=f.error,
        current_version=f.current_version,
        created_at=f.created_at,
        storage_key=storage_key,
    )


@router.post("", response_model=FileOut, status_code=status.HTTP_201_CREATED)
def upload_file(
    workspace_id: str,
    current: CurrentUser,
    db: DbSession,
    file: Annotated[UploadFile, FileParam(description="File yang diupload")],
    role: str = Depends(require_role("contributor")),
) -> FileOut:
    """Upload file (contributor+). Dedup: isi identik di workspace → 409."""
    if not file.filename:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Filename required")
    filename = file.filename

    data = _read_bounded(file)
    ext, mime = _validate_size_and_ext(filename, len(data))
    checksum = hashlib.sha256(data).hexdigest()

    dedup = db.execute(
        select(File.id).where(
            File.workspace_id == workspace_id,
            File.checksum_sha256 == checksum,
            File.is_deleted.is_(False),
        )
    ).scalar_one_or_none()
    if dedup is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Identical content already exists in this workspace",
        )

    file_row = File(
        workspace_id=workspace_id,
        uploaded_by=current.id,
        filename=filename,
        size_bytes=len(data),
        mime_type=mime,
        checksum_sha256=checksum,
        status="queued",
    )
    db.add(file_row)
    db.flush()

    version = FileVersion(
        file_id=file_row.id,
        version=1,
        checksum_sha256=checksum,
        storage_key=object_key(workspace_id, file_row.id, 1, filename),
        size_bytes=len(data),
        mime_type=mime,
    )
    db.add(version)
    db.add(IngestionJob(file_id=file_row.id, job_type="ingest", status="queued"))

    # Simpan ke object storage sebelum commit DB; gagal storage → rollback DB.
    try:
        storage = get_storage()
        storage.ensure_bucket()
        storage.put(version.storage_key, data, mime)
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, f"Storage unavailable: {type(exc).__name__}"
        ) from exc

    audit(
        db,
        action="file.upload",
        workspace_id=workspace_id,
        user_id=current.id,
        target=filename,
        meta={"size": len(data), "checksum": checksum[:12], "file_id": file_row.id},
    )
    audit_mod.write_audit_log(
        {"action": "file.upload", "workspace_id": workspace_id,
         "user_id": current.id, "target": filename, "size": len(data)}
    )
    return _file_out(file_row, version.storage_key)


@router.get("", response_model=list[FileOut])
def list_files(
    workspace_id: str,
    current: CurrentUser,
    db: DbSession,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    role: str = Depends(require_role("viewer")),
) -> list[FileOut]:
    """Daftar file workspace (viewer+). Filter opsional ?status=queued|indexed|..."""
    if status_filter and status_filter not in FILE_STATUSES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid status filter")

    stmt = (
        select(File)
        .where(File.workspace_id == workspace_id, File.is_deleted.is_(False))
        .order_by(File.created_at.desc())
    )
    if status_filter:
        stmt = stmt.where(File.status == status_filter)
    rows = db.execute(stmt).scalars().all()
    if not rows:
        return []

    versions = db.execute(
        select(FileVersion).where(
            FileVersion.file_id.in_([f.id for f in rows]),
            FileVersion.version == File.current_version,
        )
    ).scalars().all()
    keys = {v.file_id: v.storage_key for v in versions}
    return [_file_out(f, keys.get(f.id, "")) for f in rows]


@router.get("/{file_id}", response_model=FileOut)
def get_file(
    workspace_id: str,
    file_id: str,
    current: CurrentUser,
    db: DbSession,
    role: str = Depends(require_role("viewer")),
) -> FileOut:
    """Detail satu file."""
    f = _get_file_or_404(db, workspace_id, file_id)
    v = _current_version_or_raise(db, f)
    return _file_out(f, v.storage_key)


@router.get("/{file_id}/download")
def download_file(
    workspace_id: str,
    file_id: str,
    current: CurrentUser,
    db: DbSession,
    role: str = Depends(require_role("viewer")),
) -> RedirectResponse:
    """Redirect ke presigned GET URL MinIO (signed URL, TTL dari settings)."""
    f = _get_file_or_404(db, workspace_id, file_id)
    v = _current_version_or_raise(db, f)
    url = get_storage().presign_get(v.storage_key, get_settings().presign_expiry_seconds)
    return RedirectResponse(url, status_code=status.HTTP_307_TEMPORARY_REDIRECT)


@router.post("/{file_id}/cancel", response_model=FileStatusOut)
def cancel_file(
    workspace_id: str,
    file_id: str,
    current: CurrentUser,
    db: DbSession,
    role: str = Depends(require_role("contributor")),
) -> FileStatusOut:
    """Batalkan file yang masih `queued` (contributor+)."""
    f = _get_file_or_404(db, workspace_id, file_id)
    if f.status != "queued":
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"Cannot cancel file in status {f.status}"
        )
    f.status = "deleted"
    f.error = "cancelled by user"
    for j in db.execute(
        select(IngestionJob).where(
            IngestionJob.file_id == f.id, IngestionJob.status == "queued"
        )
    ).scalars().all():
        j.status = "cancelled"
        j.finished_at = utcnow()
    audit(
        db, action="file.cancel", workspace_id=workspace_id,
        user_id=current.id, target=f.filename,
    )
    audit_mod.write_audit_log(
        {"action": "file.cancel", "workspace_id": workspace_id,
         "user_id": current.id, "target": f.filename}
    )
    return FileStatusOut(id=f.id, status=f.status)


@router.delete("/{file_id}", response_model=FileStatusOut)
def delete_file(
    workspace_id: str,
    file_id: str,
    current: CurrentUser,
    db: DbSession,
    role: str = Depends(require_role("editor")),
) -> FileStatusOut:
    """Soft delete (editor+); object storage tetap sampai purge (Fase 9)."""
    f = _get_file_or_404(db, workspace_id, file_id)
    f.is_deleted = True
    f.status = "deleted"
    audit(
        db, action="file.delete", workspace_id=workspace_id,
        user_id=current.id, target=f.filename,
    )
    audit_mod.write_audit_log(
        {"action": "file.delete", "workspace_id": workspace_id,
         "user_id": current.id, "target": f.filename}
    )
    return FileStatusOut(id=f.id, status=f.status)


@router.post("/{file_id}/reindex", response_model=FileStatusOut)
def reindex_file(
    workspace_id: str,
    file_id: str,
    current: CurrentUser,
    db: DbSession,
    role: str = Depends(require_role("contributor")),
) -> FileStatusOut:
    """Jadwalkan ulang indexing (contributor+)."""
    f = _get_file_or_404(db, workspace_id, file_id)
    if f.status == "queued":
        raise HTTPException(status.HTTP_409_CONFLICT, "File is already queued")
    f.status = "queued"
    f.error = None
    db.add(IngestionJob(file_id=f.id, job_type="reindex", status="queued"))
    audit(
        db, action="file.reindex", workspace_id=workspace_id,
        user_id=current.id, target=f.filename,
    )
    audit_mod.write_audit_log(
        {"action": "file.reindex", "workspace_id": workspace_id,
         "user_id": current.id, "target": f.filename}
    )
    return FileStatusOut(id=f.id, status=f.status)
