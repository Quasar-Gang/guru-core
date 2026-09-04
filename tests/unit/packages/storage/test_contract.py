import hashlib
import hmac
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from packages.storage import InMemoryStorage, LocalFileStorage, ObjectNotFound
from tests.unit.packages.storage.test_r2 import mock_r2


@pytest.fixture(params=["memory", "local", "r2"])
def storage(request, tmp_path: Path) -> Iterator[object]:
    if request.param == "memory":
        yield InMemoryStorage()
    elif request.param == "local":
        yield LocalFileStorage(tmp_path, "http://x/v1/files", "secret")
    else:
        with mock_r2() as r2:
            yield r2


async def test_put_then_get_roundtrip(storage):
    await storage.put("a/b.txt", b"hello", "text/plain")
    assert await storage.get("a/b.txt") == b"hello"


async def test_get_missing_raises(storage):
    with pytest.raises(ObjectNotFound):
        await storage.get("nope")


async def test_delete_is_idempotent(storage):
    await storage.put("k", b"x", "text/plain")
    await storage.delete("k")
    await storage.delete("k")
    assert await storage.exists("k") is False


async def test_presign_put_contains_key(storage):
    url = await storage.presign_put("up/1.pdf", "application/pdf", 900)
    assert "up/1.pdf" in url


def test_local_signature_roundtrip(tmp_path: Path):
    exp = int(datetime.now(UTC).timestamp()) + 900
    sig = hmac.new(b"secret", b"get:k:%d" % exp, hashlib.sha256).hexdigest()
    assert (
        LocalFileStorage.verify_signature("secret", "get", "k", exp, sig, datetime.now(UTC)) is True
    )
    assert (
        LocalFileStorage.verify_signature("secret", "get", "k", exp, "bad", datetime.now(UTC))
        is False
    )


def test_local_rejects_path_traversal(tmp_path: Path):
    s = LocalFileStorage(tmp_path, "http://x", "secret")
    with pytest.raises(ValueError):
        s._resolve("../escape")
