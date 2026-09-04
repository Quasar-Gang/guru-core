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


async def test_fake_oidc_derives_the_identity_from_the_code() -> None:
    fake = FakeGoogleOidc(derive_from_code=True)
    identity = await fake.exchange_code("fake:smoke@example.com", "http://cb")
    assert identity.email == "smoke@example.com"
    assert (
        identity.google_sub == (await fake.exchange_code("fake:smoke@example.com", "x")).google_sub
    )
    assert (
        identity.google_sub != (await fake.exchange_code("fake:other@example.com", "x")).google_sub
    )


async def test_fake_oidc_rejects_a_code_without_the_prefix() -> None:
    fake = FakeGoogleOidc(derive_from_code=True)
    with pytest.raises(Unauthorized):
        await fake.exchange_code("c", "http://cb")
