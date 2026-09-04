"""RateLimitMiddleware is mounted by `create_app` when the setting asks for it."""

from uuid import UUID

import httpx
import pytest

from services.api.container import ApiContainer, build_test_container, create_app
from services.api.settings import ApiSettings

LIMIT = 3


@pytest.fixture
def limited_container() -> ApiContainer:
    settings: ApiSettings = build_test_container().settings.model_copy(
        update={"rate_limit_per_minute": LIMIT}
    )
    return build_test_container(settings=settings)


@pytest.fixture
async def limited_client(limited_container: ApiContainer) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=create_app(limited_container))
    return httpx.AsyncClient(transport=transport, base_url="http://testserver")


@pytest.fixture
async def limited_headers(limited_container: ApiContainer) -> dict[str, str]:
    user = await limited_container.users.create("limited@example.com", "limited-sub")
    await limited_container.profiles.upsert(user.id, {}, "UTC")
    user_id: UUID = user.id
    return {"Authorization": f"Bearer {limited_container.tokens.issue(user_id)}"}


async def test_requests_over_the_budget_are_429(
    limited_client: httpx.AsyncClient, limited_headers: dict[str, str]
) -> None:
    for _ in range(LIMIT):
        assert (await limited_client.get("/v1/me", headers=limited_headers)).status_code == 200
    response = await limited_client.get("/v1/me", headers=limited_headers)
    assert response.status_code == 429
    assert response.headers["Retry-After"] == "60"
    assert response.json()["error"]["code"] == "rate_limited"


async def test_health_is_never_limited(limited_client: httpx.AsyncClient) -> None:
    for _ in range(LIMIT * 3):
        assert (await limited_client.get("/health")).status_code == 200


async def test_default_test_container_is_not_limited(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    for _ in range(70):
        assert (await client.get("/v1/me", headers=auth_headers)).status_code == 200
