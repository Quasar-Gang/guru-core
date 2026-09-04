from datetime import UTC, datetime

import httpx
import pytest
from fastapi import FastAPI

from packages.cache import DictCache
from services.api.adapters.clock import FakeClock
from services.api.adapters.http.middleware import RateLimitMiddleware
from services.api.adapters.jwt_issuer import HmacTokenIssuer

SECRET = "rate-limit-test-secret"
START = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(START)


@pytest.fixture
def issuer(clock: FakeClock) -> HmacTokenIssuer:
    return HmacTokenIssuer(SECRET, ttl_seconds=3600, clock=clock)


@pytest.fixture
def client(clock: FakeClock, issuer: HmacTokenIssuer) -> httpx.AsyncClient:
    app = FastAPI()

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/v1/files/{key:path}")
    async def files(key: str) -> dict[str, str]:
        return {"key": key}

    @app.get("/v1/thing")
    async def thing() -> dict[str, bool]:
        return {"ok": True}

    app.add_middleware(
        RateLimitMiddleware,
        cache=DictCache(clock=lambda: clock.now().timestamp()),
        tokens=issuer,
        clock=clock,
        limit=3,
        window_seconds=60,
    )
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver")


async def _get(client: httpx.AsyncClient, path: str = "/v1/thing", **kw) -> httpx.Response:
    return await client.get(path, **kw)


async def test_requests_under_the_limit_pass(client):
    for _ in range(3):
        assert (await _get(client)).status_code == 200


async def test_request_over_the_limit_is_429_with_retry_after(client):
    for _ in range(3):
        await _get(client)
    response = await _get(client)
    assert response.status_code == 429
    assert response.headers["Retry-After"] == "60"
    assert response.json()["error"]["code"] == "rate_limited"


async def test_two_users_have_separate_budgets(client, issuer):
    from uuid import uuid4

    alice = {"authorization": f"Bearer {issuer.issue(uuid4())}"}
    bob = {"authorization": f"Bearer {issuer.issue(uuid4())}"}
    for _ in range(3):
        assert (await _get(client, headers=alice)).status_code == 200
    assert (await _get(client, headers=alice)).status_code == 429
    assert (await _get(client, headers=bob)).status_code == 200


async def test_budget_resets_in_the_next_window(client, clock):
    for _ in range(4):
        await _get(client)
    clock.advance(seconds=60)
    assert (await _get(client)).status_code == 200


async def test_health_is_exempt(client):
    for _ in range(10):
        assert (await _get(client, "/health")).status_code == 200


async def test_files_are_exempt(client):
    for _ in range(10):
        assert (await _get(client, "/v1/files/imports/a/b.csv")).status_code == 200


async def test_invalid_token_falls_back_to_the_client_address(client):
    bad = {"authorization": "Bearer not-a-jwt"}
    for _ in range(3):
        assert (await _get(client, headers=bad)).status_code == 200
    assert (await _get(client, headers=bad)).status_code == 429
