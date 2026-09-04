"""GoogleOAuthPort implementations: `GoogleOAuth` for production, `FakeOAuth` for tests."""

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import httpx

from services.api.application.ports import InvalidGrant, OAuthTokens
from services.api.domain.errors import DomainError

__all__ = [
    "GOOGLE_AUTHORIZE_URL",
    "GOOGLE_REVOKE_URL",
    "GOOGLE_TOKEN_URL",
    "FakeOAuth",
    "GoogleOAuth",
]

GOOGLE_AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_REVOKE_URL = "https://oauth2.googleapis.com/revoke"


def _tokens_from(body: dict[str, Any], fallback_refresh_token: str | None) -> OAuthTokens:
    """Google omits `refresh_token` on refresh, so the caller's token is carried forward."""
    access_token = body.get("access_token")
    if not isinstance(access_token, str) or not access_token:
        raise DomainError("google token response has no access_token")
    expires_in = body.get("expires_in")
    expires_at = (
        datetime.now(UTC) + timedelta(seconds=int(expires_in))
        if isinstance(expires_in, int | float | str) and str(expires_in).isdigit()
        else None
    )
    refresh_token = body.get("refresh_token")
    scope = body.get("scope")
    return OAuthTokens(
        access_token=access_token,
        refresh_token=refresh_token if isinstance(refresh_token, str) else fallback_refresh_token,
        expires_at=expires_at,
        scopes=scope.split() if isinstance(scope, str) else [],
    )


class GoogleOAuth:
    """Talks to Google's OAuth 2.0 endpoints over HTTPS."""

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._redirect_uri = redirect_uri
        self._client = client
        self._timeout_seconds = timeout_seconds

    def authorize_url(self, state: str, scopes: Sequence[str]) -> str:
        # `access_type=offline` + `prompt=consent` are what make Google hand back a refresh
        # token; without them a returning user gets an access token we cannot renew.
        query = urlencode(
            {
                "client_id": self._client_id,
                "redirect_uri": self._redirect_uri,
                "response_type": "code",
                "scope": " ".join(scopes),
                "access_type": "offline",
                "prompt": "consent",
                "include_granted_scopes": "true",
                "state": state,
            }
        )
        return f"{GOOGLE_AUTHORIZE_URL}?{query}"

    async def exchange_code(self, code: str) -> OAuthTokens:
        body = await self._post_form(
            GOOGLE_TOKEN_URL,
            {
                "code": code,
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "redirect_uri": self._redirect_uri,
                "grant_type": "authorization_code",
            },
        )
        return _tokens_from(body, None)

    async def refresh(self, refresh_token: str) -> OAuthTokens:
        body = await self._post_form(
            GOOGLE_TOKEN_URL,
            {
                "refresh_token": refresh_token,
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "grant_type": "refresh_token",
            },
        )
        return _tokens_from(body, refresh_token)

    async def revoke(self, refresh_token: str) -> None:
        """Best effort: a token Google has already forgotten must not block disconnecting."""
        try:
            await self._request("POST", GOOGLE_REVOKE_URL, data={"token": refresh_token})
        except httpx.HTTPError:
            return

    async def _post_form(self, url: str, form: dict[str, str]) -> dict[str, Any]:
        response = await self._request("POST", url, data=form)
        body = response.json() if response.content else {}
        if not isinstance(body, dict):
            body = {}
        if response.status_code != httpx.codes.OK:
            if body.get("error") == "invalid_grant":
                raise InvalidGrant("google rejected the grant: invalid_grant")
            raise DomainError(f"google oauth call failed: {response.status_code}")
        return body

    async def _request(
        self, method: str, url: str, data: dict[str, str] | None = None
    ) -> httpx.Response:
        if self._client is not None:
            return await self._client.request(method, url, data=data)
        async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
            return await client.request(method, url, data=data)


class FakeOAuth:
    """Test double: hands out a fixed token pair and records what it was asked to do."""

    def __init__(
        self,
        tokens: OAuthTokens | None = None,
        refresh_raises: Exception | None = None,
    ) -> None:
        self.tokens = tokens or OAuthTokens(
            access_token="fake-access-token",
            refresh_token="refresh-abc",
            expires_at=datetime.now(UTC) + timedelta(hours=1),
            scopes=[
                "https://www.googleapis.com/auth/calendar.readonly",
                "https://www.googleapis.com/auth/calendar.events",
                "https://www.googleapis.com/auth/spreadsheets",
            ],
        )
        self.refresh_raises = refresh_raises
        self.exchange_calls: list[str] = []
        self.refresh_calls = 0
        self.revoked: list[str] = []
        self.authorize_calls: list[tuple[str, list[str]]] = []

    def authorize_url(self, state: str, scopes: Sequence[str]) -> str:
        self.authorize_calls.append((state, list(scopes)))
        query = urlencode({"state": state, "scope": " ".join(scopes)})
        return f"https://fake-google.test/authorize?{query}"

    async def exchange_code(self, code: str) -> OAuthTokens:
        self.exchange_calls.append(code)
        return self.tokens

    async def refresh(self, refresh_token: str) -> OAuthTokens:
        self.refresh_calls += 1
        if self.refresh_raises is not None:
            raise self.refresh_raises
        return self.tokens

    async def revoke(self, refresh_token: str) -> None:
        self.revoked.append(refresh_token)
