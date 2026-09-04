import base64
import json

import httpx
import pytest

from services.api.adapters.google.oidc import FakeGoogleOidc, GoogleOidc
from services.api.application.ports import GoogleIdentity
from services.api.domain.errors import Unauthorized


def _id_token(payload: dict[str, object]) -> str:
    def seg(data: dict[str, object]) -> str:
        raw = json.dumps(data).encode()
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    return f"{seg({'alg': 'RS256'})}.{seg(payload)}.sig"


def _oidc(handler: httpx.MockTransport) -> GoogleOidc:
    return GoogleOidc(
        client_id="cid",
        client_secret="csecret",
        client=httpx.AsyncClient(transport=handler),
    )


async def test_exchange_code_returns_identity() -> None:
    seen: dict[str, object] = {}

    def handle(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = request.content.decode()
        return httpx.Response(
            200,
            json={"id_token": _id_token({"sub": "g1", "email": "a@b.c"})},
        )

    identity = await _oidc(httpx.MockTransport(handle)).exchange_code("the-code", "http://cb")

    assert identity == GoogleIdentity(google_sub="g1", email="a@b.c")
    assert seen["url"] == "https://oauth2.googleapis.com/token"
    body = str(seen["body"])
    assert "code=the-code" in body
    assert "client_id=cid" in body
    assert "grant_type=authorization_code" in body


async def test_exchange_code_non_200_raises_unauthorized() -> None:
    transport = httpx.MockTransport(lambda _r: httpx.Response(400, json={"error": "bad_code"}))
    with pytest.raises(Unauthorized):
        await _oidc(transport).exchange_code("c", "http://cb")


async def test_exchange_code_without_id_token_raises_unauthorized() -> None:
    transport = httpx.MockTransport(lambda _r: httpx.Response(200, json={"access_token": "a"}))
    with pytest.raises(Unauthorized):
        await _oidc(transport).exchange_code("c", "http://cb")


async def test_exchange_code_with_unparsable_id_token_raises_unauthorized() -> None:
    transport = httpx.MockTransport(lambda _r: httpx.Response(200, json={"id_token": "nope"}))
    with pytest.raises(Unauthorized):
        await _oidc(transport).exchange_code("c", "http://cb")


async def test_exchange_code_without_sub_raises_unauthorized() -> None:
    token = _id_token({"email": "a@b.c"})
    transport = httpx.MockTransport(lambda _r: httpx.Response(200, json={"id_token": token}))
    with pytest.raises(Unauthorized):
        await _oidc(transport).exchange_code("c", "http://cb")


async def test_fake_oidc_records_calls() -> None:
    fake = FakeGoogleOidc(GoogleIdentity(google_sub="g1", email="a@b.c"))
    assert await fake.exchange_code("c", "http://cb") == GoogleIdentity(
        google_sub="g1", email="a@b.c"
    )
    assert fake.calls == [("c", "http://cb")]
