"""Storage adapter — S3-compatible (MinIO) di balik interface.

Interface `StorageProtocol` membuat vendor bisa diganti (roadmap:
adapter agar provider dapat diganti) tanpa menyentuh kode pemanggil.
"""

from typing import Protocol

from minio import Minio

from app.settings import get_settings


class StorageProtocol(Protocol):
    """Kontrak minimal storage object."""

    def put(self, key: str, data: bytes, content_type: str) -> None: ...
    def presign_get(self, key: str, expires_seconds: int) -> str: ...
    def remove(self, key: str) -> None: ...


def object_key(workspace_id: str, file_id: str, version: int, filename: str) -> str:
    """Key object: per-workspace, per-version; tidak mengandung secret."""
    return f"workspaces/{workspace_id}/files/{file_id}/v{version}/{filename}"


class MinioStorage:
    """Implementasi MinIO dari StorageProtocol."""

    def __init__(self) -> None:
        s = get_settings()
        self._client = Minio(
            s.minio_endpoint,
            access_key=s.minio_access_key,
            secret_key=s.minio_secret_key,
            secure=s.minio_secure,
        )
        self._bucket = s.minio_bucket

    def ensure_bucket(self) -> None:
        """Buat bucket bila belum ada (idempotent)."""
        if not self._client.bucket_exists(self._bucket):
            self._client.make_bucket(self._bucket)

    def put(self, key: str, data: bytes, content_type: str) -> None:
        import io

        self._client.put_object(
            self._bucket,
            key,
            io.BytesIO(data),
            length=len(data),
            content_type=content_type or "application/octet-stream",
        )

    def presign_get(self, key: str, expires_seconds: int) -> str:
        from datetime import timedelta

        return self._client.presigned_get_object(
            self._bucket, key, expires=timedelta(seconds=expires_seconds)
        )

    def remove(self, key: str) -> None:
        self._client.remove_object(self._bucket, key)


def get_storage() -> MinioStorage:
    """Singleton storage adapter."""
    global _storage
    if _storage is None:
        _storage = MinioStorage()
    return _storage


_storage: MinioStorage | None = None
