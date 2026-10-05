"""Storage adapter — S3-compatible (MinIO / Supabase Storage) di balik interface."""

import io
from datetime import timedelta
from typing import Protocol

from minio import Minio
from minio.error import S3Error

from ai_asistent_core.config import get_settings


class StorageProtocol(Protocol):
    """Kontrak minimal storage object."""

    def get(self, key: str) -> bytes: ...
    def put(self, key: str, data: bytes, content_type: str) -> None: ...
    def presign_get(self, key: str, expires_seconds: int) -> str: ...
    def remove(self, key: str) -> None: ...


def object_key(workspace_id: str, file_id: str, version: int, filename: str) -> str:
    """Key object: per-workspace, per-version; tidak mengandung secret."""
    return f"workspaces/{workspace_id}/files/{file_id}/v{version}/{filename}"


class StorageUnavailableError(RuntimeError):
    """Dilempar bila storage tidak terkonfigurasi atau tidak bisa dicapai."""
    pass


class MinioStorage:
    """Implementasi MinIO / S3-compatible dari StorageProtocol."""

    def __init__(self) -> None:
        s = get_settings()

        # Validasi konfigurasi — endpoint kosong berarti storage tidak dikonfigurasi
        if not s.minio_endpoint or s.minio_endpoint in ("localhost:9000", ""):
            raise StorageUnavailableError(
                "Object storage belum dikonfigurasi. "
                "Set APP_MINIO_ENDPOINT, APP_MINIO_ACCESS_KEY, APP_MINIO_SECRET_KEY "
                "di environment variables."
            )

        # Supabase Storage S3: endpoint-nya adalah URL lengkap, bukan host:port.
        # Minio client butuh host tanpa scheme; kalau ada https:// strip dulu.
        endpoint = s.minio_endpoint
        secure = s.minio_secure
        if endpoint.startswith("https://"):
            endpoint = endpoint[len("https://"):]
            secure = True
        elif endpoint.startswith("http://"):
            endpoint = endpoint[len("http://"):]
            secure = False

        self._client = Minio(
            endpoint,
            access_key=s.minio_access_key,
            secret_key=s.minio_secret_key,
            secure=secure,
        )
        self._bucket = s.minio_bucket

    def ensure_bucket(self) -> None:
        """Buat bucket bila belum ada (idempotent). Skip untuk Supabase (bucket = folder)."""
        try:
            if not self._client.bucket_exists(self._bucket):
                self._client.make_bucket(self._bucket)
        except S3Error:
            pass  # Supabase Storage mungkin tidak support ListBuckets

    def get(self, key: str) -> bytes:
        """Baca isi object."""
        resp = self._client.get_object(self._bucket, key)
        try:
            return resp.read()
        finally:
            resp.close()
            resp.release_conn()

    def put(self, key: str, data: bytes, content_type: str) -> None:
        """Simpan object."""
        self._client.put_object(
            self._bucket,
            key,
            io.BytesIO(data),
            length=len(data),
            content_type=content_type or "application/octet-stream",
        )

    def presign_get(self, key: str, expires_seconds: int) -> str:
        """URL GET presigned."""
        return self._client.presigned_get_object(
            self._bucket, key, expires=timedelta(seconds=expires_seconds)
        )

    def remove(self, key: str) -> None:
        """Hapus object."""
        self._client.remove_object(self._bucket, key)


_storage: MinioStorage | None = None


def get_storage() -> MinioStorage:
    """Singleton storage adapter. Raise StorageUnavailableError bila tidak terkonfigurasi."""
    global _storage
    if _storage is None:
        _storage = MinioStorage()
    return _storage
