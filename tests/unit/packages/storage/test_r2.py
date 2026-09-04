"""Tests for R2Storage, backed by moto's in-process S3 mock (no network)."""

from collections.abc import Iterator
from contextlib import contextmanager

import boto3
import pytest
from moto import mock_aws

from packages.storage import ObjectNotFound, R2Storage
from services.api.container import build_container
from services.api.settings import ApiSettings

BUCKET = "guru-core-test"
ACCESS_KEY_ID = "test-access-key"
SECRET_ACCESS_KEY = "test-secret-key"


@contextmanager
def mock_r2() -> Iterator[R2Storage]:
    """Start moto's S3 mock, create the bucket, and yield an R2Storage pointed at it."""
    with mock_aws():
        boto3.client(
            "s3",
            region_name="us-east-1",
            aws_access_key_id=ACCESS_KEY_ID,
            aws_secret_access_key=SECRET_ACCESS_KEY,
        ).create_bucket(Bucket=BUCKET)
        # No account id and no endpoint: boto3 keeps its default endpoint, which the mock
        # intercepts. Production always supplies an account id (see `_build_storage`).
        yield R2Storage(
            account_id="",
            access_key_id=ACCESS_KEY_ID,
            secret_access_key=SECRET_ACCESS_KEY,
            bucket=BUCKET,
            endpoint_url=None,
        )


@pytest.fixture
def r2_storage() -> Iterator[R2Storage]:
    with mock_r2() as storage:
        yield storage


async def test_put_returns_metadata(r2_storage: R2Storage):
    stored = await r2_storage.put("a/b.txt", b"hello", "text/plain")
    assert stored.key == "a/b.txt"
    assert stored.size == 5
    assert stored.content_type == "text/plain"


async def test_put_then_get_roundtrip(r2_storage: R2Storage):
    await r2_storage.put("a/b.txt", b"hello", "text/plain")
    assert await r2_storage.get("a/b.txt") == b"hello"


async def test_get_missing_raises_object_not_found(r2_storage: R2Storage):
    with pytest.raises(ObjectNotFound):
        await r2_storage.get("nope")


async def test_delete_is_idempotent(r2_storage: R2Storage):
    await r2_storage.put("k", b"x", "text/plain")
    await r2_storage.delete("k")
    await r2_storage.delete("k")
    assert await r2_storage.exists("k") is False


async def test_exists_reflects_put(r2_storage: R2Storage):
    assert await r2_storage.exists("k") is False
    await r2_storage.put("k", b"x", "text/plain")
    assert await r2_storage.exists("k") is True


async def test_presign_put_contains_bucket_and_key(r2_storage: R2Storage):
    url = await r2_storage.presign_put("up/1.pdf", "application/pdf", 900)
    assert BUCKET in url
    assert "up/1.pdf" in url


async def test_presign_get_contains_bucket_and_key(r2_storage: R2Storage):
    url = await r2_storage.presign_get("up/1.pdf", 900)
    assert BUCKET in url
    assert "up/1.pdf" in url


def _r2_settings(bucket: str = BUCKET) -> ApiSettings:
    return ApiSettings(
        _env_file=None,
        database_url="postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/guru_core_test",
        redis_url="redis://127.0.0.1:6379/15",
        jwt_secret="test-jwt-secret-at-least-32-bytes-long",
        storage_backend="r2",
        storage_public_base_url="http://testserver/v1/files",
        storage_signing_secret="test-storage-secret",
        r2_account_id="test-account",
        r2_access_key_id=ACCESS_KEY_ID,
        r2_secret_access_key=SECRET_ACCESS_KEY,
        r2_bucket=bucket,
    )


def test_build_container_selects_r2_storage():
    container = build_container(_r2_settings())
    assert isinstance(container.storage, R2Storage)


def test_build_container_rejects_incomplete_r2_settings():
    with pytest.raises(ValueError, match="r2_bucket"):
        build_container(_r2_settings(bucket=""))
