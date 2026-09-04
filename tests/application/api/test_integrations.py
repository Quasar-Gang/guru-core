"""Google OAuth connection management: authorize, callback, list, disconnect, token refresh."""

from datetime import UTC, datetime
from uuid import UUID

import httpx
import pytest
from cryptography.fernet import Fernet

from services.api.adapters.crypto import FernetTokenCipher, PlainTokenCipher
from services.api.adapters.google.oauth import GOOGLE_AUTHORIZE_URL, FakeOAuth, GoogleOAuth
from services.api.application.authorize_integration import CALENDAR_SCOPES
from services.api.application.google_access_token import GOOGLE_TOKEN_CACHE_PREFIX
from services.api.application.ports import InvalidGrant, OAuthTokens
from services.api.container import ApiContainer, build_test_container
from services.api.domain.errors import DomainError, InvalidInput, NotFound, ReauthRequired


async def _user(container: ApiContainer) -> UUID:
    user = await container.users.create("integration@example.com", "integration-sub")
    return user.id


# --- use cases -------------------------------------------------------------------------


async def test_authorize_url_contains_calendar_scopes(container: ApiContainer) -> None:
    user_id = await _user(container)
    url = await container.authorize_integration(user_id, "google")
    assert "calendar.events" in url
    assert "calendar.readonly" in url
    assert "spreadsheets" in url


async def test_authorize_rejects_unknown_provider(container: ApiContainer) -> None:
    user_id = await _user(container)
    with pytest.raises(InvalidInput):
        await container.authorize_integration(user_id, "notion")


async def test_callback_stores_encrypted_refresh_token(container: ApiContainer) -> None:
    user_id = await _user(container)
    view = await container.complete_integration(user_id, "google", "code")

    assert view.connected is True
    assert view.needs_reauth is False
    assert view.scopes == CALENDAR_SCOPES

    conn = await container.oauth_connections.get(user_id, "google")
    assert conn is not None
    assert container.cipher.decrypt(conn.encrypted_refresh_token) == "refresh-abc"


async def test_callback_stores_the_refresh_token_encrypted() -> None:
    """The default test container uses PlainTokenCipher, so check the real one separately."""
    cipher = FernetTokenCipher(Fernet.generate_key().decode())
    container = build_test_container(cipher=cipher)
    user_id = await _user(container)
    await container.complete_integration(user_id, "google", "code")

    conn = await container.oauth_connections.get(user_id, "google")
    assert conn is not None
    assert conn.encrypted_refresh_token != b"refresh-abc"
    assert cipher.decrypt(conn.encrypted_refresh_token) == "refresh-abc"


async def test_callback_without_refresh_token_is_rejected() -> None:
    oauth = FakeOAuth(
        tokens=OAuthTokens(
            access_token="access-1", refresh_token=None, expires_at=None, scopes=CALENDAR_SCOPES
        )
    )
    container = build_test_container(google_oauth=oauth)
    user_id = await _user(container)
    with pytest.raises(InvalidInput):
        await container.complete_integration(user_id, "google", "code")


async def test_list_integrations_is_empty_before_connecting(container: ApiContainer) -> None:
    user_id = await _user(container)
    assert await container.list_integrations(user_id) == []


async def test_list_integrations_flags_needs_reauth_after_revoke(container: ApiContainer) -> None:
    user_id = await _user(container)
    await container.complete_integration(user_id, "google", "code")
    await container.oauth_connections.mark_revoked(user_id, "google", datetime.now(UTC))

    [view] = await container.list_integrations(user_id)
    assert view.provider == "google"
    assert view.needs_reauth is True
    assert view.connected is False
    assert view.connected_at is not None


async def test_disconnect_revokes_token_and_clears_cached_access_token(
    container: ApiContainer,
) -> None:
    user_id = await _user(container)
    await container.complete_integration(user_id, "google", "code")
    await container.google_token_provider.get(user_id)

    await container.disconnect_integration(user_id, "google")

    assert isinstance(container.google_oauth, FakeOAuth)
    assert container.google_oauth.revoked == ["refresh-abc"]
    conn = await container.oauth_connections.get(user_id, "google")
    assert conn is not None and conn.revoked_at is not None
    assert await container.cache.get(f"{GOOGLE_TOKEN_CACHE_PREFIX}{user_id}") is None


async def test_disconnect_unknown_connection_raises_not_found(container: ApiContainer) -> None:
    user_id = await _user(container)
    with pytest.raises(NotFound):
        await container.disconnect_integration(user_id, "google")


async def test_access_token_provider_raises_reauth_without_connection(
    container: ApiContainer,
) -> None:
    user_id = await _user(container)
    with pytest.raises(ReauthRequired):
        await container.google_token_provider.get(user_id)


async def test_access_token_provider_raises_reauth_on_invalid_grant() -> None:
    container = build_test_container(google_oauth=FakeOAuth(refresh_raises=InvalidGrant()))
    user_id = await _user(container)
    await container.complete_integration(user_id, "google", "code")

    with pytest.raises(ReauthRequired):
        await container.google_token_provider.get(user_id)

    conn = await container.oauth_connections.get(user_id, "google")
    assert conn is not None and conn.revoked_at is not None


async def test_access_token_provider_raises_reauth_when_already_revoked(
    container: ApiContainer,
) -> None:
    user_id = await _user(container)
    await container.complete_integration(user_id, "google", "code")
    await container.oauth_connections.mark_revoked(user_id, "google", datetime.now(UTC))

    with pytest.raises(ReauthRequired):
        await container.google_token_provider.get(user_id)


async def test_access_token_is_cached(container: ApiContainer) -> None:
    user_id = await _user(container)
    await container.complete_integration(user_id, "google", "code")

    first = await container.google_token_provider.get(user_id)
    second = await container.google_token_provider.get(user_id)

    assert first == second
    assert isinstance(container.google_oauth, FakeOAuth)
    assert container.google_oauth.refresh_calls == 1


async def test_expired_access_token_is_not_cached() -> None:
    """A token that is already inside the 60s safety margin must be refreshed every time."""
    oauth = FakeOAuth(
        tokens=OAuthTokens(
            access_token="access-1",
            refresh_token="refresh-abc",
            expires_at=datetime.now(UTC),
            scopes=CALENDAR_SCOPES,
        )
    )
    container = build_test_container(google_oauth=oauth)
    user_id = await _user(container)
    await container.complete_integration(user_id, "google", "code")

    await container.google_token_provider.get(user_id)
    await container.google_token_provider.get(user_id)

    assert oauth.refresh_calls == 2


# --- HTTP endpoints --------------------------------------------------------------------


async def test_integrations_endpoints_round_trip(
    client: httpx.AsyncClient, container: ApiContainer, auth_headers: dict[str, str]
) -> None:
    authorize = await client.get("/v1/integrations/google/authorize", headers=auth_headers)
    assert authorize.status_code == 200
    assert "spreadsheets" in authorize.json()["authorize_url"]

    callback = await client.post(
        "/v1/integrations/google/callback", headers=auth_headers, json={"code": "the-code"}
    )
    assert callback.status_code == 200
    assert callback.json()["connected"] is True

    listed = await client.get("/v1/integrations", headers=auth_headers)
    assert [v["provider"] for v in listed.json()] == ["google"]

    deleted = await client.delete("/v1/integrations/google", headers=auth_headers)
    assert deleted.status_code == 204

    listed_again = await client.get("/v1/integrations", headers=auth_headers)
    assert listed_again.json()[0]["needs_reauth"] is True


async def test_integrations_endpoints_require_auth(client: httpx.AsyncClient) -> None:
    assert (await client.get("/v1/integrations")).status_code == 401


# --- GoogleOAuth adapter (httpx.MockTransport) -----------------------------------------


def _oauth(transport: httpx.MockTransport) -> GoogleOAuth:
    return GoogleOAuth(
        client_id="cid",
        client_secret="csecret",
        redirect_uri="http://cb",
        client=httpx.AsyncClient(transport=transport),
    )


def test_google_oauth_authorize_url_asks_for_offline_access() -> None:
    url = _oauth(httpx.MockTransport(lambda _r: httpx.Response(200))).authorize_url(
        "st4te", CALENDAR_SCOPES
    )
    assert url.startswith(GOOGLE_AUTHORIZE_URL)
    assert "access_type=offline" in url
    assert "state=st4te" in url
    assert "client_id=cid" in url
    assert "calendar.events" in url


async def test_google_oauth_exchange_code_returns_tokens() -> None:
    seen: dict[str, str] = {}

    def handle(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = request.content.decode()
        return httpx.Response(
            200,
            json={
                "access_token": "at",
                "refresh_token": "rt",
                "expires_in": 3600,
                "scope": "a b",
            },
        )

    tokens = await _oauth(httpx.MockTransport(handle)).exchange_code("the-code")

    assert tokens.access_token == "at"
    assert tokens.refresh_token == "rt"
    assert tokens.scopes == ["a", "b"]
    assert tokens.expires_at is not None and tokens.expires_at > datetime.now(UTC)
    assert seen["url"] == "https://oauth2.googleapis.com/token"
    assert "grant_type=authorization_code" in seen["body"]


async def test_google_oauth_exchange_code_failure_raises() -> None:
    transport = httpx.MockTransport(lambda _r: httpx.Response(400, json={"error": "bad"}))
    with pytest.raises(DomainError):
        await _oauth(transport).exchange_code("c")


async def test_google_oauth_refresh_maps_invalid_grant() -> None:
    transport = httpx.MockTransport(lambda _r: httpx.Response(400, json={"error": "invalid_grant"}))
    with pytest.raises(InvalidGrant):
        await _oauth(transport).refresh("rt")


async def test_google_oauth_refresh_keeps_the_refresh_token() -> None:
    transport = httpx.MockTransport(
        lambda _r: httpx.Response(200, json={"access_token": "at", "expires_in": 60})
    )
    tokens = await _oauth(transport).refresh("rt")
    assert tokens.access_token == "at"
    assert tokens.refresh_token == "rt"


async def test_google_oauth_revoke_posts_the_token_and_ignores_failure() -> None:
    seen: dict[str, str] = {}

    def handle(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = request.content.decode()
        return httpx.Response(400, json={"error": "invalid_token"})

    await _oauth(httpx.MockTransport(handle)).revoke("rt")

    assert seen["url"] == "https://oauth2.googleapis.com/revoke"
    assert "token=rt" in seen["body"]


# --- FakeOAuth / PlainTokenCipher -------------------------------------------------------


async def test_fake_oauth_records_calls() -> None:
    fake = FakeOAuth()
    assert (await fake.exchange_code("c")).refresh_token == "refresh-abc"
    assert fake.exchange_calls == ["c"]
    await fake.refresh("refresh-abc")
    assert fake.refresh_calls == 1


def test_plain_cipher_is_reversible_by_anyone() -> None:
    assert PlainTokenCipher().encrypt("x") == b"x"
