"""Role Model Service CRUD — application 與 HTTP 兩層（Task 27 Step 1）。"""

import shutil
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
import yaml
from httpx import ASGITransport, AsyncClient

from packages.config import CONFIG_DIR
from services.role_model.adapters.http.app import create_app
from services.role_model.container import RoleModelContainer, build_test_container

API_KEY = "test-key"

PERSONA_CONTENT: dict[str, Any] = {
    "summary": "八成訓練量放在輕鬆配速，靠週期化累積耐力。",
    "sections": {
        "principles": ["八成的訓練量以輕鬆配速進行。"],
        "weekly_structure": "一週五次：三次輕鬆跑、一次強度課、一次長距離。",
        "progress_metrics": ["同配速心率逐週下降"],
        "pitfalls": ["輕鬆跑跑太快"],
    },
}

TRAIT_CONTENT: dict[str, Any] = {
    "summary": "固定節奏、線性漸進。",
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
    """真實 vocab 的副本；測試一律只寫 tmp_path。"""
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


# --- 建立後可 GET -----------------------------------------------------------


async def test_create_persona_then_get(client: AsyncClient) -> None:
    created = await _create(
        client, _persona_body("Kipchoge 型", ["domain:fitness", "goal:endurance"])
    )
    assert created["kind"] == "persona"
    assert created["active"] is True
    assert created["version"] == 1

    got = await client.get(f"/role-models/{created['id']}")
    assert got.status_code == 200
    assert got.json()["name"] == "Kipchoge 型"
    assert got.json()["content"]["summary"] == PERSONA_CONTENT["summary"]


async def test_get_unknown_id_returns_404(client: AsyncClient) -> None:
    resp = await client.get("/role-models/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"


async def test_put_updates_and_bumps_version(client: AsyncClient) -> None:
    created = await _create(client, _persona_body("原名", ["domain:fitness", "goal:endurance"]))
    body = _persona_body("新名", ["domain:fitness", "goal:endurance"])
    resp = await client.put(
        f"/role-models/{created['id']}", json=body, headers={"X-API-Key": API_KEY}
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "新名"
    assert resp.json()["version"] == 2
    assert resp.json()["id"] == created["id"]


# --- 驗證 -------------------------------------------------------------------


async def test_invalid_tag_returns_422(client: AsyncClient) -> None:
    body = _persona_body("壞 tag", ["domain:fitness", "goal:endurance", "nope:bad"])
    resp = await client.post("/role-models", json=body, headers={"X-API-Key": API_KEY})
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "invalid_input"
    assert "nope" in resp.json()["error"]["message"]


async def test_persona_missing_required_namespace_returns_422(client: AsyncClient) -> None:
    resp = await client.post(
        "/role-models",
        json=_persona_body("缺 goal", ["domain:fitness"]),
        headers={"X-API-Key": API_KEY},
    )
    assert resp.status_code == 422


async def test_invalid_content_returns_422(client: AsyncClient) -> None:
    body = _persona_body("壞 content", ["domain:fitness", "goal:endurance"])
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
    created = await _create(client, _persona_body("受保護", ["domain:fitness", "goal:endurance"]))
    body = _persona_body("受保護", ["domain:fitness", "goal:endurance"])
    assert (await client.put(f"/role-models/{created['id']}", json=body)).status_code == 401
    assert (await client.delete(f"/role-models/{created['id']}")).status_code == 401


async def test_get_endpoints_need_no_api_key(client: AsyncClient) -> None:
    assert (await client.get("/role-models")).status_code == 200
    assert (await client.get("/role-models/tags")).status_code == 200


# --- 列表查詢 ---------------------------------------------------------------


async def test_list_filters_by_kind(client: AsyncClient) -> None:
    await _create(client, _trait_body("穩扎穩打", ["cadence:5x-week"]))
    await _create(client, _persona_body("Kipchoge", ["domain:fitness", "goal:endurance"]))

    resp = await client.get("/role-models", params={"kind": "trait"})
    assert resp.status_code == 200
    items = resp.json()
    assert [i["name"] for i in items] == ["穩扎穩打"]
    assert items[0]["summary"] == TRAIT_CONTENT["summary"]


async def test_list_match_all_requires_every_tag(client: AsyncClient) -> None:
    await _create(client, _persona_body("兩個都有", ["domain:fitness", "goal:endurance"]))
    await _create(client, _persona_body("只有一個", ["domain:fitness", "goal:fat-loss"]))

    params: list[tuple[str, str | int | float | bool | None]] = [
        ("tags", "domain:fitness"),
        ("tags", "goal:endurance"),
        ("match", "all"),
    ]
    resp = await client.get("/role-models", params=params)
    assert [i["name"] for i in resp.json()] == ["兩個都有"]

    any_params: list[tuple[str, str | int | float | bool | None]] = [
        ("tags", "domain:fitness"),
        ("tags", "goal:endurance"),
        ("match", "any"),
    ]
    any_resp = await client.get("/role-models", params=any_params)
    assert {i["name"] for i in any_resp.json()} == {"兩個都有", "只有一個"}


async def test_summary_defaults_to_empty_string(container: RoleModelContainer) -> None:
    await container.role_models.upsert(
        role_model_id=None,
        kind="persona",
        name="無 summary",
        tags=["domain:fitness", "goal:endurance"],
        content={},
    )
    items = await container.list_role_models(kind=None, tags=[])
    assert [i.summary for i in items] == [""]


# --- 停用 -------------------------------------------------------------------


async def test_delete_deactivates_and_hides_from_default_list(client: AsyncClient) -> None:
    created = await _create(client, _persona_body("要停用的", ["domain:fitness", "goal:endurance"]))
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


# --- tag vocab 寫回 ---------------------------------------------------------


async def test_upsert_learns_new_values_into_vocab_file(
    client: AsyncClient, tag_vocab_path: Path
) -> None:
    await _create(client, _persona_body("新領域", ["domain:cooking", "goal:endurance"]))
    vocab = yaml.safe_load(tag_vocab_path.read_text(encoding="utf-8"))
    assert "cooking" in vocab["known_values"]["domain"]


async def test_rejected_upsert_does_not_touch_vocab_file(
    client: AsyncClient, tag_vocab_path: Path
) -> None:
    before = tag_vocab_path.read_text(encoding="utf-8")
    await client.post(
        "/role-models",
        json=_persona_body("壞的", ["nope:bad"]),
        headers={"X-API-Key": API_KEY},
    )
    assert tag_vocab_path.read_text(encoding="utf-8") == before
