"""GoogleOidcPort implementations: `GoogleOidc` for production, `FakeGoogleOidc` for tests."""

import base64
import binascii
import hashlib
import json
from typing import Any

import httpx

from services.api.application.ports import GoogleIdentity
from services.api.domain.errors import Unauthorized

__all__ = ["FAKE_CODE_PREFIX", "GOOGLE_TOKEN_URL", "FakeGoogleOidc", "GoogleOidc"]

GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"

#: Prefix of the authorization codes `FakeGoogleOidc(derive_from_code=True)` understands.
FAKE_CODE_PREFIX = "fake:"


def _decode_id_token_payload(id_token: str) -> dict[str, Any]:
    """Decode the id_token payload.

    MVP shortcut: base64url decode only, **no signature verification**. That is acceptable
    here because we fetch the id_token ourselves from Google's token endpoint over TLS using
    our client_secret, so it never passes through the user. Before production this should
    verify against Google's JWKS and check `aud` / `iss` / `exp` (`PyJWKClient` +
    `jwt.decode`).
    """
    parts = id_token.split(".")
    if len(parts) != 3:
        raise Unauthorized("malformed id_token")
    payload = parts[1]
    padded = payload + "=" * (-len(payload) % 4)
    try:
        decoded = json.loads(base64.urlsafe_b64decode(padded))
    except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise Unauthorized("malformed id_token") from exc
    if not isinstance(decoded, dict):
        raise Unauthorized("malformed id_token")
    return decoded


class GoogleOidc:
    """Exchanges an authorization code with Google for an id_token and reads `sub` / `email`."""

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._client = client
        self._timeout_seconds = timeout_seconds

    async def exchange_code(self, code: str, redirect_uri: str) -> GoogleIdentity:
        form = {
            "code": code,
            "client_id": self._client_id,
            "client_secret": self._client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        }
        if self._client is not None:
            response = await self._client.post(GOOGLE_TOKEN_URL, data=form)
        else:
            async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
                response = await client.post(GOOGLE_TOKEN_URL, data=form)

        if response.status_code != httpx.codes.OK:
            raise Unauthorized(f"google token exchange failed: {response.status_code}")

        body = response.json()
        id_token = body.get("id_token") if isinstance(body, dict) else None
        if not isinstance(id_token, str) or not id_token:
            raise Unauthorized("google token response has no id_token")

        claims = _decode_id_token_payload(id_token)
        google_sub = claims.get("sub")
        email = claims.get("email")
        if not isinstance(google_sub, str) or not google_sub:
            raise Unauthorized("google id_token has no sub")
        if not isinstance(email, str):
            email = ""
        return GoogleIdentity(google_sub=google_sub, email=email)


class FakeGoogleOidc:
    """Test double: returns a canned identity and records the arguments it got.

    With `derive_from_code=True` a code of the form `fake:<email>` is turned into an
    identity for that email, its `google_sub` being a hash of the address so the same
    email always maps to the same user. That mode is what `scripts/smoke.sh` uses; see
    `ApiSettings.allow_fake_login` for why it must never be enabled in production.
    """

    def __init__(
        self, identity: GoogleIdentity | None = None, *, derive_from_code: bool = False
    ) -> None:
        self.identity = identity or GoogleIdentity(google_sub="fake-sub", email="fake@example.com")
        self.derive_from_code = derive_from_code
        self.calls: list[tuple[str, str]] = []

    async def exchange_code(self, code: str, redirect_uri: str) -> GoogleIdentity:
        self.calls.append((code, redirect_uri))
        if not self.derive_from_code:
            return self.identity
        if not code.startswith(FAKE_CODE_PREFIX):
            raise Unauthorized(f"fake login expects a code of the form {FAKE_CODE_PREFIX}<email>")
        email = code.removeprefix(FAKE_CODE_PREFIX)
        if not email:
            raise Unauthorized("fake login code carries no email")
        digest = hashlib.sha256(email.encode("utf-8")).hexdigest()[:32]
        return GoogleIdentity(google_sub=f"fake-{digest}", email=email)
