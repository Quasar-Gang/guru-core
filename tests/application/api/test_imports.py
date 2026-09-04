from uuid import UUID, uuid4

import httpx
import pytest

from packages.queue import ImportParseJobV1, InMemoryQueue
from services.api.application.presign_import import PresignImport
from services.api.container import ApiContainer
from services.api.domain.errors import InvalidInput, NotFound


async def test_presign_rejects_oversize(container: ApiContainer, auth_user_id: UUID) -> None:
    with pytest.raises(InvalidInput, match="20"):
        await container.presign_import(auth_user_id, "a.pdf", "application/pdf", 21 * 1024 * 1024)


async def test_presign_rejects_unsupported_format(
    container: ApiContainer, auth_user_id: UUID
) -> None:
    with pytest.raises(InvalidInput):
        await container.presign_import(auth_user_id, "a.exe", "application/x-msdownload", 10)


async def test_presign_creates_pending_import_with_scoped_key(
    container: ApiContainer, auth_user_id: UUID
) -> None:
    result = await container.presign_import(auth_user_id, "a.csv", "text/csv", 100)
    assert result.storage_key.startswith(f"imports/{auth_user_id}/")
    assert result.storage_key.endswith("/a.csv")
    assert result.expires_in == PresignImport.EXPIRES_IN
    record = await container.imports.get(auth_user_id, result.import_id)
    assert record is not None
    assert record.status == "pending"
    assert record.source == "upload"
    assert record.format == "csv"


async def test_presign_strips_path_from_filename(
    container: ApiContainer, auth_user_id: UUID
) -> None:
    result = await container.presign_import(auth_user_id, "../../etc/pass wd.csv", "text/csv", 10)
    assert result.storage_key.endswith("/pass wd.csv")
    assert ".." not in result.storage_key


async def test_complete_requires_uploaded_object(
    container: ApiContainer, auth_user_id: UUID
) -> None:
    result = await container.presign_import(auth_user_id, "a.csv", "text/csv", 100)
    with pytest.raises(InvalidInput):
        await container.complete_import(auth_user_id, result.import_id)


async def test_complete_enqueues_parse_job(container: ApiContainer, auth_user_id: UUID) -> None:
    result = await container.presign_import(auth_user_id, "a.csv", "text/csv", 100)
    await container.storage.put(result.storage_key, b"title,start\n", "text/csv")
    view = await container.complete_import(auth_user_id, result.import_id)
    assert view.status == "queued"
    assert isinstance(container.queue, InMemoryQueue)
    assert container.queue.enqueued == [ImportParseJobV1(import_id=result.import_id)]


async def test_complete_on_unknown_import_is_not_found(
    container: ApiContainer, auth_user_id: UUID
) -> None:
    with pytest.raises(NotFound):
        await container.complete_import(auth_user_id, uuid4())


async def test_list_imports_is_user_scoped(container: ApiContainer, auth_user_id: UUID) -> None:
    other = await container.users.create("other@example.com", "other-sub")
    mine = await container.presign_import(auth_user_id, "mine.csv", "text/csv", 10)
    await container.presign_import(other.id, "theirs.csv", "text/csv", 10)

    views = await container.list_imports(auth_user_id)
    assert [v.id for v in views] == [mine.import_id]
    assert views[0].filename == "mine.csv"
    assert views[0].event_count == 0
    assert views[0].chunk_count == 0


async def test_presign_over_http_returns_upload_url(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    r = await client.post(
        "/v1/imports/presign",
        json={"filename": "a.csv", "content_type": "text/csv", "size_bytes": 12},
        headers=auth_headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["upload_url"]
    assert body["expires_in"] == PresignImport.EXPIRES_IN


async def test_oversize_presign_over_http_is_422(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    r = await client.post(
        "/v1/imports/presign",
        json={"filename": "a.csv", "content_type": "text/csv", "size_bytes": 99 * 1024 * 1024},
        headers=auth_headers,
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "invalid_input"


async def test_complete_and_list_over_http(
    client: httpx.AsyncClient,
    container: ApiContainer,
    auth_headers: dict[str, str],
) -> None:
    presign = await client.post(
        "/v1/imports/presign",
        json={"filename": "a.csv", "content_type": "text/csv", "size_bytes": 12},
        headers=auth_headers,
    )
    body = presign.json()
    await container.storage.put(body["storage_key"], b"title,start\n", "text/csv")

    complete = await client.post(f"/v1/imports/{body['import_id']}/complete", headers=auth_headers)
    assert complete.status_code == 200
    assert complete.json()["status"] == "queued"

    listed = await client.get("/v1/imports", headers=auth_headers)
    assert listed.status_code == 200
    assert [i["id"] for i in listed.json()] == [body["import_id"]]


async def test_imports_endpoints_require_auth(client: httpx.AsyncClient) -> None:
    assert (await client.get("/v1/imports")).status_code == 401
