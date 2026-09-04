import httpx
import pytest

from services.api.adapters.google.oidc import FakeGoogleOidc
from services.api.application.ports import GoogleIdentity
from services.api.container import build_test_container, create_app
from services.api.domain.errors import (
    Conflict,
    DomainError,
    Forbidden,
    InvalidInput,
    NotFound,
    ReauthRequired,
    Unauthorized,
)


async def test_health_is_ok(client: httpx.AsyncClient) -> None:
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


async def test_post_auth_google_returns_token(client: httpx.AsyncClient) -> None:
    r = await client.post("/v1/auth/google", json={"code": "c", "redirect_uri": "http://cb"})
    assert r.status_code == 200
    assert "access_token" in r.json()


async def test_post_auth_google_token_works_on_protected_endpoint(
    client: httpx.AsyncClient,
) -> None:
    login = await client.post("/v1/auth/google", json={"code": "c", "redirect_uri": "http://cb"})
    token = login.json()["access_token"]
    r = await client.get("/v1/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert r.json()["user_id"] == login.json()["user_id"]


async def test_protected_endpoint_without_token_is_401(client: httpx.AsyncClient) -> None:
    assert (await client.get("/v1/me")).status_code == 401


async def test_protected_endpoint_with_invalid_token_is_401(client: httpx.AsyncClient) -> None:
    r = await client.get("/v1/me", headers={"Authorization": "Bearer garbage"})
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "unauthorized"


async def test_protected_endpoint_with_wrong_scheme_is_401(client: httpx.AsyncClient) -> None:
    r = await client.get("/v1/me", headers={"Authorization": "Basic abc"})
    assert r.status_code == 401


async def test_auth_headers_fixture_works(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    r = await client.get("/v1/me", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["email"] == "fixture@example.com"


async def test_login_failure_maps_to_401() -> None:
    class BrokenOidc:
        async def exchange_code(self, code: str, redirect_uri: str) -> GoogleIdentity:
            raise Unauthorized("bad code")

    c = build_test_container(oidc=BrokenOidc())
    transport = httpx.ASGITransport(app=create_app(c))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        r = await client.post("/v1/auth/google", json={"code": "c", "redirect_uri": "http://cb"})
    assert r.status_code == 401
    assert r.json() == {"error": {"code": "unauthorized", "message": "bad code"}}


@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        (NotFound("nope"), 404, "not_found"),
        (Forbidden("no"), 403, "forbidden"),
        (Conflict("dup"), 409, "conflict"),
        (InvalidInput("bad"), 422, "invalid_input"),
        (Unauthorized("who"), 401, "unauthorized"),
        (ReauthRequired("again"), 409, "reauth_required"),
        (DomainError("boom"), 500, "domain_error"),
    ],
)
async def test_domain_error_handler_maps_status_and_code(
    error: DomainError, status: int, code: str
) -> None:
    c = build_test_container(oidc=_RaisingOidc(error))
    transport = httpx.ASGITransport(app=create_app(c))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        r = await client.post("/v1/auth/google", json={"code": "c", "redirect_uri": "http://cb"})
    assert r.status_code == status
    assert r.json() == {"error": {"code": code, "message": str(error)}}


class _RaisingOidc:
    def __init__(self, error: DomainError) -> None:
        self._error = error

    async def exchange_code(self, code: str, redirect_uri: str) -> GoogleIdentity:
        raise self._error


async def test_body_validation_error_is_422(client: httpx.AsyncClient) -> None:
    r = await client.post("/v1/auth/google", json={"code": "c"})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "invalid_input"


def test_default_test_container_oidc_is_fake() -> None:
    assert isinstance(build_test_container().oidc, FakeGoogleOidc)
