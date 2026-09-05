"""The `/v1` boundary itself: status codes, the error envelope, and who may read what.

These are the guarantees a client is entitled to depend on, so they are tested at the
highest useful interception rather than through the use cases.
"""

from uuid import uuid4

import httpx
import pytest

from services.api.container import ApiContainer, build_test_container, create_app


async def test_health_needs_no_token(client: httpx.AsyncClient):
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/v1/profile"),
        ("POST", "/v1/direction/runs"),
        ("GET", "/v1/direction/runs/latest"),
        ("GET", "/v1/questions"),
        ("GET", "/v1/quota"),
        ("GET", "/v1/role-models"),
        ("GET", "/v1/hypotheses"),
        ("GET", "/v1/plans"),
        ("GET", "/v1/imports"),
    ],
)
async def test_every_endpoint_requires_a_bearer_token(
    client: httpx.AsyncClient, method: str, path: str
):
    response = await client.request(method, path)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


async def test_a_malformed_token_reads_the_same_as_a_missing_one(client: httpx.AsyncClient):
    response = await client.get("/v1/profile", headers={"Authorization": "Bearer nonsense"})
    assert response.status_code == 401


async def test_the_profile_of_a_user_with_no_uploads_is_an_empty_read_not_an_error(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
):
    response = await client.get("/v1/profile", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["coverage"] == {}


async def test_the_three_questions_are_served_with_their_purpose(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
):
    response = await client.get("/v1/questions", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert [item["key"] for item in body] == ["q1", "q2", "q3"]
    assert all(item["purpose"] for item in body)
    assert body[2]["choices"] == ["career", "relationships", "health"]


async def test_q3_rejects_prose_with_the_error_envelope(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
):
    response = await client.put(
        "/v1/questions/q3", headers=auth_headers, json={"answer": "all of them"}
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_input"


async def test_an_unknown_question_is_rejected(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
):
    response = await client.put("/v1/questions/q9", headers=auth_headers, json={"answer": "x"})
    assert response.status_code == 422


async def test_starting_an_analysis_with_no_data_conflicts(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
):
    response = await client.post("/v1/direction/runs", headers=auth_headers)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"


async def test_reading_a_run_before_one_exists_is_a_404(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
):
    response = await client.get("/v1/direction/runs/latest", headers=auth_headers)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


async def test_a_user_authored_shape_must_state_its_cost(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
):
    body = {
        "code": "MY-1",
        "name": "The Quiet Maintainer",
        "vision": "Keep the things other people depend on working.",
        "five_year_path": "Be the person a system outlives.",
        "must_accumulate": "Patience.",
        "cost": "",
    }
    response = await client.post("/v1/role-models", headers=auth_headers, json=body)
    assert response.status_code == 422

    response = await client.post(
        "/v1/role-models", headers=auth_headers, json={**body, "cost": "Invisible work."}
    )
    assert response.status_code == 201
    assert response.json()["author"] == "user"


async def test_another_users_shape_is_invisible(
    client: httpx.AsyncClient, container: ApiContainer, auth_headers: dict[str, str]
):
    await client.post(
        "/v1/role-models",
        headers=auth_headers,
        json={
            "code": "MY-1",
            "name": "Mine",
            "vision": "v",
            "five_year_path": "p",
            "must_accumulate": "a",
            "cost": "c",
        },
    )
    stranger = await container.users.create("other@example.com", "other-sub")
    headers = {"Authorization": f"Bearer {container.tokens.issue(stranger.id)}"}
    response = await client.get("/v1/role-models", headers=headers)
    assert response.status_code == 200
    assert [item["code"] for item in response.json()] == []


async def test_another_users_plan_reads_as_missing_rather_than_forbidden(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
):
    response = await client.get(f"/v1/plans/{uuid4()}", headers=auth_headers)
    assert response.status_code == 404


async def test_the_rate_limiter_answers_in_the_same_envelope():
    settings = build_test_container().settings.model_copy(update={"rate_limit_per_minute": 1})
    container = build_test_container(settings=settings)
    user = await container.users.create("limited@example.com", "limited-sub")
    headers = {"Authorization": f"Bearer {container.tokens.issue(user.id)}"}
    transport = httpx.ASGITransport(app=create_app(container))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        assert (await client.get("/v1/questions", headers=headers)).status_code == 200
        throttled = await client.get("/v1/questions", headers=headers)
    assert throttled.status_code == 429
    assert throttled.json()["error"]["code"] == "rate_limited"
