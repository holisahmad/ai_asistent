"""Storage adapter — S3-compatible via boto3 (MinIO, Supabase Storage, AWS S3)."""

import io
from typing import Protocol

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError, EndpointResolutionError

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


def _build_endpoint_url(endpoint: str, secure: bool) -> str:
    """Normalkan endpoint ke URL lengkap untuk boto3.

    Supabase Storage S3 API membutuhkan path /storage/v1/s3.
    Endpoint bisa diberikan sebagai:
      - hostname saja           : nykffalzlxbmuatxgbhb.storage.supabase.co
      - hostname + path         : nykffalzlxbmuatxgbhb.storage.supabase.co/storage/v1/s3
      - URL lengkap             : https://nykffalzlxbmuatxgbhb.storage.supabase.co/storage/v1/s3
    """
    # Sudah URL lengkap
    if endpoint.startswith("http://") or endpoint.startswith("https://"):
        url = endpoint
    else:
        scheme = "https" if secure else "http"
        url = f"{scheme}://{endpoint}"

    # Supabase: tambahkan /storage/v1/s3 bila endpoint adalah *.supabase.co
    # dan belum mengandung path tersebut
    if "supabase.co" in url and "/storage/v1/s3" not in url:
        url = url.rstrip("/") + "/storage/v1/s3"

    return url


class S3Storage:
    """Storage adapter berbasis boto3 — kompatibel dengan MinIO, Supabase, AWS S3."""

    def __init__(self) -> None:
        s = get_settings()

        if not s.minio_endpoint or s.minio_endpoint in ("localhost:9000",):
            raise StorageUnavailableError(
                "Object storage belum dikonfigurasi. "
                "Set APP_MINIO_ENDPOINT, APP_MINIO_ACCESS_KEY, APP_MINIO_SECRET_KEY."
            )

        endpoint_url = _build_endpoint_url(s.minio_endpoint, s.minio_secure)

        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=s.minio_access_key,
            aws_secret_access_key=s.minio_secret_key,
            region_name="ap-northeast-1",
            config=Config(
                signature_version="s3v4",
                connect_timeout=10,
                read_timeout=30,
                retries={"max_attempts": 3, "mode": "standard"},
            ),
        )
        self._bucket = s.minio_bucket

    def ensure_bucket(self) -> None:
        """Buat bucket bila belum ada (idempotent). No-op bila bucket sudah ada."""
        try:
            self._client.head_bucket(Bucket=self._bucket)
        except ClientError as e:
            code = e.response["Error"]["Code"]
            if code in ("404", "NoSuchBucket"):
                try:
                    self._client.create_bucket(Bucket=self._bucket)
                except ClientError:
                    pass  # Mungkin sudah dibuat oleh request lain / Supabase manage sendiri
            # 403 = bucket ada tapi kita tidak punya akses ListBucket — OK, lanjutkan
        except Exception:
            pass

    def get(self, key: str) -> bytes:
        """Baca isi object."""
        try:
            resp = self._client.get_object(Bucket=self._bucket, Key=key)
            return resp["Body"].read()
        except ClientError as e:
            raise StorageUnavailableError(f"Storage get error: {e}") from e

    def put(self, key: str, data: bytes, content_type: str) -> None:
        """Simpan object."""
        try:
            self._client.put_object(
                Bucket=self._bucket,
                Key=key,
                Body=io.BytesIO(data),
                ContentType=content_type or "application/octet-stream",
                ContentLength=len(data),
            )
        except ClientError as e:
            raise StorageUnavailableError(f"Storage put error: {e}") from e

    def presign_get(self, key: str, expires_seconds: int) -> str:
        """URL GET presigned."""
        return self._client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self._bucket, "Key": key},
            ExpiresIn=expires_seconds,
        )

    def remove(self, key: str) -> None:
        """Hapus object."""
        try:
            self._client.delete_object(Bucket=self._bucket, Key=key)
        except ClientError as e:
            raise StorageUnavailableError(f"Storage delete error: {e}") from e


# Backward-compat alias
MinioStorage = S3Storage

_storage: S3Storage | None = None


def get_storage() -> S3Storage:
    """Singleton storage adapter. Raise StorageUnavailableError bila tidak terkonfigurasi."""
    global _storage
    if _storage is None:
        _storage = S3Storage()
    return _storage
