"""Where plate snapshots are kept: a local folder, or any S3-compatible object store.

The rest of the code only sees the `SnapshotStorage` protocol (save / load / delete by
key), so switching from RustFS in development to a cloud bucket in production is a
settings change (`SNAPSHOT_STORAGE`, `S3_*`), not a code change.
"""

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

import anyio
import boto3
from botocore.exceptions import ClientError

from app.core.config import Settings
from app.services.errors import InvalidInputError, NotFoundError

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client

logger = logging.getLogger(__name__)

# Recognised by their first bytes ("magic numbers"), never by the uploaded file name or
# Content-Type header, which the sender controls.
_IMAGE_SIGNATURES: tuple[tuple[bytes, int, str, str], ...] = (
    (b"\xff\xd8\xff", 0, "image/jpeg", "jpg"),
    (b"\x89PNG\r\n\x1a\n", 0, "image/png", "png"),
    (b"WEBP", 8, "image/webp", "webp"),  # "RIFF" + 4-byte size + "WEBP"
)


def detect_image_type(data: bytes) -> tuple[str, str]:
    """(content type, file extension) of a JPEG, PNG or WebP image; anything else is refused."""
    for signature, offset, content_type, extension in _IMAGE_SIGNATURES:
        if data[offset : offset + len(signature)] == signature:
            if content_type == "image/webp" and not data.startswith(b"RIFF"):
                continue
            return content_type, extension
    raise InvalidInputError("Snapshot must be a JPEG, PNG or WebP image")


def content_type_for(key: str) -> str:
    extension = key.rsplit(".", 1)[-1]
    return {"jpg": "image/jpeg", "png": "image/png", "webp": "image/webp"}.get(
        extension, "application/octet-stream"
    )


class SnapshotStorage(Protocol):
    async def save(self, key: str, data: bytes, content_type: str) -> None: ...
    async def load(self, key: str) -> bytes: ...
    async def delete(self, key: str) -> None: ...


class LocalSnapshotStorage:
    """Files under one folder; the key is the relative path (e.g. 'society/2026/11/21/x.jpg')."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        # Keys are built by us, but check anyway: "../../etc/passwd" must never escape.
        if not path.is_relative_to(self.root):
            raise InvalidInputError("Invalid snapshot key")
        return path

    async def save(self, key: str, data: bytes, content_type: str) -> None:
        path = self._path(key)

        def write() -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)

        await anyio.to_thread.run_sync(write)

    async def load(self, key: str) -> bytes:
        path = self._path(key)
        try:
            return await anyio.to_thread.run_sync(path.read_bytes)
        except FileNotFoundError as exc:
            raise NotFoundError("Snapshot not found") from exc

    async def delete(self, key: str) -> None:
        await anyio.to_thread.run_sync(lambda: self._path(key).unlink(missing_ok=True))


class S3SnapshotStorage:
    """An S3 bucket (AWS, Cloudflare R2, RustFS…). boto3 is blocking, so calls run in a
    worker thread to keep the event loop free."""

    def __init__(self, client: "S3Client", bucket: str) -> None:
        self.client = client
        self.bucket = bucket
        self._bucket_checked = False

    def _ensure_bucket(self) -> None:
        """Create the bucket on first use, so a fresh dev stack works without setup."""
        if self._bucket_checked:
            return
        try:
            self.client.head_bucket(Bucket=self.bucket)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") not in {"404", "NoSuchBucket"}:
                raise
            logger.info("creating snapshot bucket", extra={"bucket": self.bucket})
            self.client.create_bucket(Bucket=self.bucket)
        self._bucket_checked = True

    async def save(self, key: str, data: bytes, content_type: str) -> None:
        def put() -> None:
            self._ensure_bucket()
            self.client.put_object(Bucket=self.bucket, Key=key, Body=data, ContentType=content_type)

        await anyio.to_thread.run_sync(put)

    async def load(self, key: str) -> bytes:
        def get() -> bytes:
            response = self.client.get_object(Bucket=self.bucket, Key=key)
            body: bytes = response["Body"].read()
            return body

        try:
            return await anyio.to_thread.run_sync(get)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in {"NoSuchKey", "404", "NoSuchBucket"}:
                raise NotFoundError("Snapshot not found") from exc
            raise

    async def delete(self, key: str) -> None:
        await anyio.to_thread.run_sync(
            lambda: self.client.delete_object(Bucket=self.bucket, Key=key)
        )


def build_snapshot_storage(settings: Settings) -> SnapshotStorage:
    if settings.snapshot_storage == "local":
        return LocalSnapshotStorage(settings.snapshot_local_dir)
    client = boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        region_name=settings.s3_region,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
    )
    return S3SnapshotStorage(client, settings.s3_bucket)
