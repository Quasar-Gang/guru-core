from services.api.adapters.google.oidc import FakeGoogleOidc
from services.api.application.ports import GoogleIdentity
from services.api.container import build_test_container


async def test_first_login_creates_user_and_profile() -> None:
    c = build_test_container(oidc=FakeGoogleOidc(GoogleIdentity(google_sub="g1", email="a@b.c")))
    r = await c.login_with_google("code", "http://cb")
    assert r.is_new_user is True
    assert r.email == "a@b.c"
    assert await c.users.get_by_google_sub("g1") is not None
    assert (await c.profiles.get(r.user_id)) is not None
    assert c.tokens.verify(r.access_token) == r.user_id


async def test_second_login_reuses_user() -> None:
    c = build_test_container(oidc=FakeGoogleOidc(GoogleIdentity(google_sub="g1", email="a@b.c")))
    first = await c.login_with_google("code", "http://cb")
    second = await c.login_with_google("code", "http://cb")
    assert second.user_id == first.user_id
    assert second.is_new_user is False


async def test_default_profile_timezone_is_utc() -> None:
    c = build_test_container(oidc=FakeGoogleOidc(GoogleIdentity(google_sub="g1", email="a@b.c")))
    r = await c.login_with_google("code", "http://cb")
    profile = await c.profiles.get(r.user_id)
    assert profile is not None
    assert profile.timezone == "UTC"
    assert profile.answers == {}


async def test_overrides_are_visible_to_use_cases() -> None:
    """被覆蓋的元件必須是 use case 實際使用的那一個。"""
    users = build_test_container().users
    c = build_test_container(
        users=users,
        oidc=FakeGoogleOidc(GoogleIdentity(google_sub="g9", email="z@b.c")),
    )
    r = await c.login_with_google("code", "http://cb")
    assert c.users is users
    assert await users.get(r.user_id) is not None
