"""Snapshot storage: the local-folder backend and the S3 backend (S3 faked with moto)."""

from collections.abc import Iterator
from pathlib import Path

import boto3
import pytest
from moto import mock_aws

from app.core.config import Settings
from app.services.errors import InvalidInputError, NotFoundError
from app.services.storage import (
    LocalSnapshotStorage,
    S3SnapshotStorage,
    build_snapshot_storage,
    content_type_for,
    detect_image_type,
)

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 32
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
WEBP = b"RIFF\x24\x00\x00\x00WEBPVP8 " + b"\x00" * 32


@pytest.mark.parametrize(
    ("data", "expected"),
    [(JPEG, ("image/jpeg", "jpg")), (PNG, ("image/png", "png")), (WEBP, ("image/webp", "webp"))],
)
def test_image_types_are_detected_from_their_bytes(data: bytes, expected: tuple[str, str]) -> None:
    assert detect_image_type(data) == expected


@pytest.mark.parametrize(
    "data", [b"", b"GIF89a....", b"<html>not an image</html>", b"XXXX\x00\x00\x00\x00WEBP"]
)
def test_other_files_are_refused(data: bytes) -> None:
    with pytest.raises(InvalidInputError):
        detect_image_type(data)


def test_content_type_from_key() -> None:
    assert content_type_for("a/b.jpg") == "image/jpeg"
    assert content_type_for("a/b.webp") == "image/webp"
    assert content_type_for("a/b.bin") == "application/octet-stream"


async def test_local_storage_round_trip(tmp_path: Path) -> None:
    storage = LocalSnapshotStorage(tmp_path)
    await storage.save("soc/2026/11/21/event.jpg", JPEG, "image/jpeg")

    assert (tmp_path / "soc/2026/11/21/event.jpg").read_bytes() == JPEG
    assert await storage.load("soc/2026/11/21/event.jpg") == JPEG

    await storage.delete("soc/2026/11/21/event.jpg")
    with pytest.raises(NotFoundError):
        await storage.load("soc/2026/11/21/event.jpg")
    await storage.delete("soc/2026/11/21/event.jpg")  # deleting twice is fine


async def test_local_storage_refuses_keys_that_escape_its_folder(tmp_path: Path) -> None:
    storage = LocalSnapshotStorage(tmp_path / "snapshots")
    with pytest.raises(InvalidInputError):
        await storage.save("../outside.jpg", JPEG, "image/jpeg")


@pytest.fixture
def s3_client() -> Iterator[object]:
    with mock_aws():
        yield boto3.client("s3", region_name="us-east-1")


async def test_s3_storage_creates_its_bucket_and_round_trips(s3_client: object) -> None:
    storage = S3SnapshotStorage(s3_client, "gatesense-test")  # type: ignore[arg-type]
    await storage.save("soc/event.png", PNG, "image/png")

    assert await storage.load("soc/event.png") == PNG
    head = storage.client.head_object(Bucket="gatesense-test", Key="soc/event.png")
    assert head["ContentType"] == "image/png"

    await storage.delete("soc/event.png")
    with pytest.raises(NotFoundError):
        await storage.load("soc/event.png")


async def test_s3_storage_reuses_an_existing_bucket(s3_client: object) -> None:
    storage = S3SnapshotStorage(s3_client, "already-there")  # type: ignore[arg-type]
    storage.client.create_bucket(Bucket="already-there")
    await storage.save("x.jpg", JPEG, "image/jpeg")
    await storage.save("y.jpg", JPEG, "image/jpeg")  # bucket check only runs once
    assert await storage.load("y.jpg") == JPEG


async def test_s3_missing_bucket_reads_as_not_found(s3_client: object) -> None:
    storage = S3SnapshotStorage(s3_client, "never-created")  # type: ignore[arg-type]
    with pytest.raises(NotFoundError):
        await storage.load("x.jpg")


def test_settings_choose_the_backend(tmp_path: Path) -> None:
    local = build_snapshot_storage(Settings(snapshot_storage="local", snapshot_local_dir=tmp_path))
    assert isinstance(local, LocalSnapshotStorage)
    s3 = build_snapshot_storage(Settings(snapshot_storage="s3", s3_bucket="b"))
    assert isinstance(s3, S3SnapshotStorage)
    assert s3.bucket == "b"
