from typing import Any
from uuid import UUID

import httpx
import pytest

from services.api.container import ApiContainer
from services.api.domain.errors import InvalidInput


async def _new_user_headers(container: ApiContainer, email: str) -> dict[str, str]:
    """Create a user with no profile row and return its Bearer header."""
    user = await container.users.create(email, f"sub-{email}")
    return {"Authorization": f"Bearer {container.tokens.issue(user.id)}"}


async def test_get_profile_returns_defaults_when_row_is_missing(container: ApiContainer) -> None:
    user = await container.users.create("nobody@example.com", "nobody-sub")
    view = await container.get_profile(user.id)
    assert view.user_id == user.id
    assert view.answers == {}
    assert view.timezone == "UTC"


async def test_get_profile_over_http_returns_defaults_when_row_is_missing(
    client: httpx.AsyncClient, container: ApiContainer
) -> None:
    headers = await _new_user_headers(container, "fresh@example.com")
    r = await client.get("/v1/profile", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["answers"] == {}
    assert body["timezone"] == "UTC"


async def test_put_profile_then_get_reads_it_back(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    payload = {
        "answers": {"difficulty_preference": "hard", "accountability": "solo"},
        "timezone": "Asia/Taipei",
    }
    put = await client.put("/v1/profile", json=payload, headers=auth_headers)
    assert put.status_code == 200
    assert put.json()["timezone"] == "Asia/Taipei"

    get = await client.get("/v1/profile", headers=auth_headers)
    assert get.status_code == 200
    assert get.json()["answers"] == payload["answers"]
    assert get.json()["timezone"] == "Asia/Taipei"


async def test_put_profile_with_invalid_timezone_is_422(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    r = await client.put(
        "/v1/profile",
        json={"answers": {}, "timezone": "Mars/Olympus"},
        headers=auth_headers,
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "invalid_input"


async def test_put_profile_without_timezone_keeps_the_current_one(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    await client.put(
        "/v1/profile",
        json={"answers": {}, "timezone": "Europe/Berlin"},
        headers=auth_headers,
    )
    r = await client.put(
        "/v1/profile", json={"answers": {"time_method": "pomodoro"}}, headers=auth_headers
    )
    assert r.status_code == 200
    assert r.json()["timezone"] == "Europe/Berlin"


async def test_profile_is_not_readable_across_users(
    client: httpx.AsyncClient, container: ApiContainer, auth_headers: dict[str, str]
) -> None:
    await client.put(
        "/v1/profile",
        json={"answers": {"accountability": "coach"}, "timezone": "Asia/Taipei"},
        headers=auth_headers,
    )
    other = await _new_user_headers(container, "other@example.com")
    r = await client.get("/v1/profile", headers=other)
    assert r.status_code == 200
    assert r.json()["answers"] == {}
    assert r.json()["timezone"] == "UTC"


async def test_update_profile_rejects_invalid_timezone(
    container: ApiContainer, auth_user_id: UUID
) -> None:
    with pytest.raises(InvalidInput):
        await container.update_profile(auth_user_id, {}, "Not/AZone")


async def test_update_profile_rejects_non_string_answer_keys(
    container: ApiContainer, auth_user_id: UUID
) -> None:
    bad_keys: Any = {1: "x"}
    with pytest.raises(InvalidInput):
        await container.update_profile(auth_user_id, bad_keys, None)


async def test_update_profile_rejects_non_dict_answers(
    container: ApiContainer, auth_user_id: UUID
) -> None:
    not_a_dict: Any = ["not", "a", "dict"]
    with pytest.raises(InvalidInput):
        await container.update_profile(auth_user_id, not_a_dict, None)
