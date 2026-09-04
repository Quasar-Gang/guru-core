"""GoogleOidcPort 的實作：正式的 `GoogleOidc` 與測試用的 `FakeGoogleOidc`。"""

import base64
import binascii
import json
from typing import Any

import httpx

from services.api.application.ports import GoogleIdentity
from services.api.domain.errors import Unauthorized

__all__ = ["GOOGLE_TOKEN_URL", "FakeGoogleOidc", "GoogleOidc"]

GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"


def _decode_id_token_payload(id_token: str) -> dict[str, Any]:
    """讀出 id_token 的 payload。

    MVP 簡化：只做 base64url 解碼，**不驗簽**。這在此處是可接受的，因為
    id_token 是我們自己用 client_secret 直接向 Google 的 token endpoint（TLS）
    換來的，中間沒有經過使用者。上線前仍應換成用 Google 的 JWKS 驗簽 +
    檢查 `aud` / `iss` / `exp` 的版本（`PyJWKClient` + `jwt.decode`）。
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
    """用授權碼向 Google 換 id_token，解出 `sub` / `email`。"""

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
    """測試用：永遠回同一個身分，並記下被呼叫的參數。"""

    def __init__(self, identity: GoogleIdentity | None = None) -> None:
        self.identity = identity or GoogleIdentity(google_sub="fake-sub", email="fake@example.com")
        self.calls: list[tuple[str, str]] = []

    async def exchange_code(self, code: str, redirect_uri: str) -> GoogleIdentity:
        self.calls.append((code, redirect_uri))
        return self.identity
