"""API service `/v1/role-models*` forwarding (plan Task 28 Step 5).

Every request is answered by an `httpx.MockTransport`; nothing here touches the network.
"""

import json
from typing import Any
from uuid import uuid4

import httpx
import pytest

from services.api.adapters.role_model_client import RoleModelClient
from services.api.container import ApiContainer, build_test_container, create_app

ROLE_MODEL_ID = uuid4()
UPSTREAM = "http://role-model.test"


@pytest.fixture
def seen() -> list[httpx.Request]:
    return []


@pytest.fixture
def container(seen: list[httpx.Request]) -> ApiContainer:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path.endswith("/recommend"):
            return httpx.Response(
                200,
                json=[
                    {
                        "role_model_id": str(ROLE_MODEL_ID),
                        "name": "Eliud Kipchoge",
                        "reason": "matches your cadence",
                    }
                ],
            )
        if request.method == "DELETE":
            return httpx.Response(204)
        return httpx.Response(200, json={"ok": True, "path": request.url.path})

    return build_test_container(
        role_model_client=RoleModelClient(UPSTREAM, transport=httpx.MockTransport(handler))
    )


@pytest.fixture
async def client(container: ApiContainer) -> Any:
    transport = httpx.ASGITransport(app=create_app(container))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


@pytest.fixture
async def auth_headers(container: ApiContainer) -> dict[str, str]:
    user = await container.users.create("rm@example.com", "rm-sub")
    await container.profiles.upsert(user.id, {"level": "beginner"}, "UTC")
    return {"Authorization": f"Bearer {container.tokens.issue(user.id)}"}


async def test_list_is_forwarded_with_query_params(
    client: httpx.AsyncClient, auth_headers: dict[str, str], seen: list[httpx.Request]
) -> None:
    r = await client.get(
        "/v1/role-models",
        params={"kind": "persona", "tags": ["domain:fitness"]},
        headers=auth_headers,
    )
    assert r.status_code == 200
    assert seen[0].url.path == "/role-models"
    assert "kind=persona" in str(seen[0].url)
    assert "tags=domain%3Afitness" in str(seen[0].url)


async def test_list_requires_a_jwt(client: httpx.AsyncClient, seen: list[httpx.Request]) -> None:
    r = await client.get("/v1/role-models")
    assert r.status_code == 401
    assert seen == []


async def test_tags_and_detail_are_forwarded(
    client: httpx.AsyncClient, auth_headers: dict[str, str], seen: list[httpx.Request]
) -> None:
    assert (await client.get("/v1/role-models/tags", headers=auth_headers)).status_code == 200
    detail = await client.get(f"/v1/role-models/{ROLE_MODEL_ID}", headers=auth_headers)
    assert detail.status_code == 200
    assert [request.url.path for request in seen] == [
        "/role-models/tags",
        f"/role-models/{ROLE_MODEL_ID}",
    ]


async def test_recommend_sends_the_profile_and_returns_recommendations(
    client: httpx.AsyncClient, auth_headers: dict[str, str], seen: list[httpx.Request]
) -> None:
    r = await client.get(
        "/v1/role-models/recommend",
        params={"goal": "run a 5k", "domains": ["fitness"]},
        headers=auth_headers,
    )
    assert r.status_code == 200
    assert r.json()[0]["name"] == "Eliud Kipchoge"

    body = json.loads(seen[0].content)
    assert seen[0].method == "POST"
    assert body["goal"] == "run a 5k"
    assert body["domains"] == ["fitness"]
    assert body["profile_answers"] == {"level": "beginner"}


async def test_write_endpoints_pass_the_api_key_through_without_a_jwt(
    client: httpx.AsyncClient, seen: list[httpx.Request]
) -> None:
    payload = {"kind": "persona", "name": "n", "tags": [], "content": {"summary": "s"}}
    created = await client.post("/v1/role-models", json=payload, headers={"X-API-Key": "team-key"})
    assert created.status_code == 200
    updated = await client.put(
        f"/v1/role-models/{ROLE_MODEL_ID}", json=payload, headers={"X-API-Key": "team-key"}
    )
    assert updated.status_code == 200
    removed = await client.delete(
        f"/v1/role-models/{ROLE_MODEL_ID}", headers={"X-API-Key": "team-key"}
    )
    assert removed.status_code == 204

    assert [request.method for request in seen] == ["POST", "PUT", "DELETE"]
    assert {request.headers["X-API-Key"] for request in seen} == {"team-key"}
