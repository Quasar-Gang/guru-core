"""Tests for the presigned upload/download endpoints backed by `LocalFileStorage`.

The default test container uses `InMemoryStorage`, whose presigned URLs are `memory://`
and carry no signature, so these tests build their own container with a real
`LocalFileStorage` rooted at pytest's `tmp_path`.
"""

import hashlib
import hmac
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from packages.storage import LocalFileStorage
from services.api.container import ApiContainer, build_test_container, create_app

BASE_URL = "http://testserver/v1/files"
SECRET = "test-storage-secret"
KEY = "imports/user/import/a.csv"
BODY = b"title,start\n"


def _sign(op: str, key: str, exp: int) -> str:
    return hmac.new(SECRET.encode(), f"{op}:{key}:{exp}".encode(), hashlib.sha256).hexdigest()


def _url(op: str, key: str, exp: int, sig: str) -> str:
    return f"{BASE_URL}/{key}?exp={exp}&op={op}&sig={sig}"


@pytest.fixture
def local_container(tmp_path: Path) -> ApiContainer:
    return build_test_container(storage=LocalFileStorage(tmp_path, BASE_URL, SECRET))


@pytest.fixture
async def local_client(local_container: ApiContainer) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=create_app(local_container))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


async def test_signed_url_round_trip(
    local_client: httpx.AsyncClient, local_container: ApiContainer
) -> None:
    put_url = await local_container.storage.presign_put(KEY, "text/csv", 900)
    put = await local_client.put(put_url, content=BODY, headers={"Content-Type": "text/csv"})
    assert put.status_code == 200
    assert await local_container.storage.get(KEY) == BODY

    get_url = await local_container.storage.presign_get(KEY, 900)
    got = await local_client.get(get_url)
    assert got.status_code == 200
    assert got.content == BODY


async def test_expired_signature_is_403(local_client: httpx.AsyncClient) -> None:
    exp = int(datetime.now(UTC).timestamp()) - 1
    r = await local_client.put(_url("put", KEY, exp, _sign("put", KEY, exp)), content=BODY)
    assert r.status_code == 403


async def test_tampered_key_is_403(local_client: httpx.AsyncClient) -> None:
    exp = int(datetime.now(UTC).timestamp()) + 900
    url = _url("put", "imports/user/import/evil.csv", exp, _sign("put", KEY, exp))
    r = await local_client.put(url, content=BODY)
    assert r.status_code == 403


async def test_wrong_operation_is_403(local_client: httpx.AsyncClient) -> None:
    exp = int(datetime.now(UTC).timestamp()) + 900
    r = await local_client.put(_url("get", KEY, exp, _sign("get", KEY, exp)), content=BODY)
    assert r.status_code == 403


async def test_download_of_missing_object_is_404(local_client: httpx.AsyncClient) -> None:
    exp = int(datetime.now(UTC).timestamp()) + 900
    key = "imports/u/i/nope.csv"
    r = await local_client.get(_url("get", key, exp, _sign("get", key, exp)))
    assert r.status_code == 404
