"""Role Model Service CRUD across the application and HTTP layers (Task 27 Step 1)."""

import shutil
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from packages.config import CONFIG_DIR
from services.role_model.adapters.http.app import create_app
from services.role_model.container import RoleModelContainer, build_test_container

API_KEY = "test-key"

PERSONA_CONTENT: dict[str, Any] = {
    "summary": "Eighty percent easy running, building endurance through periodization.",
    "sections": {
        "principles": ["Run 80% of your volume at an easy pace."],
        "weekly_structure": "Five sessions a week: three easy runs, one hard, one long run.",
        "progress_metrics": ["Heart rate at the same pace drops week over week"],
        "pitfalls": ["Running the easy days too fast"],
    },
}

TRAIT_CONTENT: dict[str, Any] = {
    "summary": "Fixed cadence, linear progression.",
    "pacing": {
        "sessions_per_week": [4, 5],
        "session_minutes": [30, 60],
        "rest_days_min": 1,
        "progression_rate": 0.10,
        "missed_policy": "same-week",
        "deload_every_weeks": None,
        "intensity_bias": "medium",
    },
}


@pytest.fixture
def tag_vocab_path(tmp_path: Path) -> Path:
    """A copy of the real vocab file; tests only ever write inside tmp_path."""
    target = tmp_path / "tag_vocab.yaml"
    shutil.copyfile(CONFIG_DIR / "tag_vocab.yaml", target)
    return target


@pytest.fixture
def container(tag_vocab_path: Path) -> RoleModelContainer:
    return build_test_container(
        tag_vocab_path=tag_vocab_path,
        role_model_api_key=API_KEY,
    )


@pytest.fixture
async def client(container: RoleModelContainer) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=create_app(container))
    async with AsyncClient(transport=transport, base_url="http://rm") as c:
        yield c


def _persona_body(name: str, tags: list[str]) -> dict[str, Any]:
    return {"kind": "persona", "name": name, "tags": tags, "content": PERSONA_CONTENT}


def _trait_body(name: str, tags: list[str]) -> dict[str, Any]:
    return {"kind": "trait", "name": name, "tags": tags, "content": TRAIT_CONTENT}


async def _create(client: AsyncClient, body: dict[str, Any]) -> dict[str, Any]:
    resp = await client.post("/role-models", json=body, headers={"X-API-Key": API_KEY})
    assert resp.status_code == 201, resp.text
    created: dict[str, Any] = resp.json()
    return created


# --- create then read -------------------------------------------------------


async def test_create_persona_then_get(client: AsyncClient) -> None:
    created = await _create(client, _persona_body("Kipchoge", ["domain:fitness", "goal:endurance"]))
    assert created["kind"] == "persona"
    assert created["active"] is True
    assert created["version"] == 1

    got = await client.get(f"/role-models/{created['id']}")
    assert got.status_code == 200
    assert got.json()["name"] == "Kipchoge"
    assert got.json()["content"]["summary"] == PERSONA_CONTENT["summary"]


async def test_get_unknown_id_returns_404(client: AsyncClient) -> None:
    resp = await client.get("/role-models/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"


async def test_put_updates_and_bumps_version(client: AsyncClient) -> None:
    created = await _create(client, _persona_body("old name", ["domain:fitness", "goal:endurance"]))
    body = _persona_body("new name", ["domain:fitness", "goal:endurance"])
    resp = await client.put(
        f"/role-models/{created['id']}", json=body, headers={"X-API-Key": API_KEY}
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "new name"
    assert resp.json()["version"] == 2
    assert resp.json()["id"] == created["id"]


# --- validation -------------------------------------------------------------


async def test_invalid_tag_returns_422(client: AsyncClient) -> None:
    body = _persona_body("bad tag", ["domain:fitness", "goal:endurance", "nope:bad"])
    resp = await client.post("/role-models", json=body, headers={"X-API-Key": API_KEY})
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "invalid_input"
    assert "nope" in resp.json()["error"]["message"]


async def test_persona_missing_required_namespace_returns_422(client: AsyncClient) -> None:
    resp = await client.post(
        "/role-models",
        json=_persona_body("missing goal", ["domain:fitness"]),
        headers={"X-API-Key": API_KEY},
    )
    assert resp.status_code == 422


async def test_invalid_content_returns_422(client: AsyncClient) -> None:
    body = _persona_body("bad content", ["domain:fitness", "goal:endurance"])
    body["content"] = {"summary": "x", "sections": {"unknown_field": 1}}
    resp = await client.post("/role-models", json=body, headers={"X-API-Key": API_KEY})
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "invalid_input"


# --- API key ----------------------------------------------------------------


async def test_post_without_api_key_returns_401(client: AsyncClient) -> None:
    resp = await client.post("/role-models", json=_persona_body("x", ["domain:fitness"]))
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "unauthorized"


async def test_post_with_wrong_api_key_returns_401(client: AsyncClient) -> None:
    resp = await client.post(
        "/role-models",
        json=_persona_body("x", ["domain:fitness"]),
        headers={"X-API-Key": "wrong"},
    )
    assert resp.status_code == 401


async def test_put_and_delete_require_api_key(client: AsyncClient) -> None:
    created = await _create(
        client, _persona_body("protected", ["domain:fitness", "goal:endurance"])
    )
    body = _persona_body("protected", ["domain:fitness", "goal:endurance"])
    assert (await client.put(f"/role-models/{created['id']}", json=body)).status_code == 401
    assert (await client.delete(f"/role-models/{created['id']}")).status_code == 401


async def test_get_endpoints_need_no_api_key(client: AsyncClient) -> None:
    assert (await client.get("/role-models")).status_code == 200
    assert (await client.get("/role-models/tags")).status_code == 200


# --- list queries -----------------------------------------------------------


async def test_list_filters_by_kind(client: AsyncClient) -> None:
    await _create(client, _trait_body("steady progress", ["cadence:5x-week"]))
    await _create(client, _persona_body("Kipchoge", ["domain:fitness", "goal:endurance"]))

    resp = await client.get("/role-models", params={"kind": "trait"})
    assert resp.status_code == 200
    items = resp.json()
    assert [i["name"] for i in items] == ["steady progress"]
    assert items[0]["summary"] == TRAIT_CONTENT["summary"]


async def test_list_match_all_requires_every_tag(client: AsyncClient) -> None:
    await _create(client, _persona_body("both tags", ["domain:fitness", "goal:endurance"]))
    await _create(client, _persona_body("one tag only", ["domain:fitness", "goal:fat-loss"]))

    params: list[tuple[str, str | int | float | bool | None]] = [
        ("tags", "domain:fitness"),
        ("tags", "goal:endurance"),
        ("match", "all"),
    ]
    resp = await client.get("/role-models", params=params)
    assert [i["name"] for i in resp.json()] == ["both tags"]

    any_params: list[tuple[str, str | int | float | bool | None]] = [
        ("tags", "domain:fitness"),
        ("tags", "goal:endurance"),
        ("match", "any"),
    ]
    any_resp = await client.get("/role-models", params=any_params)
    assert {i["name"] for i in any_resp.json()} == {"both tags", "one tag only"}


async def test_summary_defaults_to_empty_string(container: RoleModelContainer) -> None:
    await container.role_models.upsert(
        role_model_id=None,
        kind="persona",
        name="no summary",
        tags=["domain:fitness", "goal:endurance"],
        content={},
    )
    items = await container.list_role_models(kind=None, tags=[])
    assert [i.summary for i in items] == [""]


# --- deactivation -----------------------------------------------------------


async def test_delete_deactivates_and_hides_from_default_list(client: AsyncClient) -> None:
    created = await _create(
        client, _persona_body("to be deactivated", ["domain:fitness", "goal:endurance"])
    )
    resp = await client.delete(f"/role-models/{created['id']}", headers={"X-API-Key": API_KEY})
    assert resp.status_code == 204

    assert (await client.get(f"/role-models/{created['id']}")).json()["active"] is False
    assert (await client.get("/role-models")).json() == []


async def test_delete_unknown_id_returns_404(client: AsyncClient) -> None:
    resp = await client.delete(
        "/role-models/00000000-0000-0000-0000-000000000000",
        headers={"X-API-Key": API_KEY},
    )
    assert resp.status_code == 404


# --- tags -------------------------------------------------------------------


async def test_list_tags_groups_by_namespace(client: AsyncClient) -> None:
    await _create(client, _persona_body("A", ["domain:fitness", "goal:endurance"]))
    await _create(client, _persona_body("B", ["domain:learning", "goal:exam"]))

    resp = await client.get("/role-models/tags")
    assert resp.status_code == 200
    assert resp.json() == {
        "domain": ["fitness", "learning"],
        "goal": ["endurance", "exam"],
    }


# --- tag vocabulary ---------------------------------------------------------


async def test_new_tag_values_surface_through_the_tags_endpoint(client: AsyncClient) -> None:
    """PRD 12.3 wants newly seen values discoverable; they come from the database,
    not from a rewritten config file, so `config/tag_vocab.yaml` keeps its comments."""
    await _create(client, _persona_body("new domain", ["domain:cooking", "goal:endurance"]))
    tags = (await client.get("/role-models/tags")).json()
    assert "cooking" in tags["domain"]


async def test_upsert_never_rewrites_the_vocab_file(
    client: AsyncClient, tag_vocab_path: Path
) -> None:
    before = tag_vocab_path.read_text(encoding="utf-8")
    await _create(client, _persona_body("new domain 2", ["domain:sailing", "goal:endurance"]))
    assert tag_vocab_path.read_text(encoding="utf-8") == before


async def test_rejected_upsert_does_not_touch_vocab_file(
    client: AsyncClient, tag_vocab_path: Path
) -> None:
    before = tag_vocab_path.read_text(encoding="utf-8")
    await client.post(
        "/role-models",
        json=_persona_body("rejected", ["nope:bad"]),
        headers={"X-API-Key": API_KEY},
    )
    assert tag_vocab_path.read_text(encoding="utf-8") == before
