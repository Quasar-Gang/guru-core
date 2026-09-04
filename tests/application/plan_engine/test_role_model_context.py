"""Role model context reaches the Plan Engine prompts and the snapshot (plan Task 29).

The seeds are read straight into the Plan Engine's own repo: services must not import each
other, so the two sides meet at `role_models.content`, not at a shared renderer object.
"""

from pathlib import Path
from typing import Any
from uuid import UUID

import yaml

from packages.llm.fake import FakeLLM
from packages.queue.jobs import PlanGenerateJobV1
from services.plan_engine.container import PlanEngineContainer, build_test_container
from tests.application.plan_engine.helpers import FIXTURES_DIR, ScriptedLLM, seed_session, tpl

SEEDS_DIR = Path(__file__).resolve().parents[3] / "seeds" / "role_models"

READY = {"ready": True, "missing": [], "questions": []}


def _seed_row(name: str) -> dict[str, Any]:
    for path in sorted(SEEDS_DIR.glob("*.yaml")):
        for row in yaml.safe_load(path.read_text(encoding="utf-8"))["role_models"]:
            if row["name"] == name:
                return row
    raise AssertionError(f"no seed named {name}")


async def _seed_role_model(container: PlanEngineContainer, name: str) -> UUID:
    row = _seed_row(name)
    role_model = await container.role_models.upsert(
        None, row["kind"], row["name"], list(row["tags"]), dict(row["content"])
    )
    return role_model.id


def _ready_llm() -> FakeLLM:
    return FakeLLM(FIXTURES_DIR, overrides={"evaluate_readiness": READY})


async def test_plan_engine_context_includes_trait_pacing_sentence() -> None:
    llm = _ready_llm()
    c = build_test_container(llm=llm)
    trait_id = await _seed_role_model(c, "穩扎穩打型")
    sid = await seed_session(c, trait_role_model_id=trait_id)

    await c.evaluate_session(PlanGenerateJobV1(session_id=sid))

    evaluate_context = llm.calls[0][2]
    generate_context = llm.calls[1][2]
    assert "預設強度中等" in evaluate_context["trait_context"]  # evaluate budget: intensity only
    assert "節奏約束：每週 4–5 次" in generate_context["trait_context"]
    assert generate_context["pacing_context"] == generate_context["trait_context"]


async def test_plan_engine_context_includes_persona_methodology() -> None:
    llm = _ready_llm()
    c = build_test_container(llm=llm)
    persona_id = await _seed_role_model(c, "Eliud Kipchoge 型")
    session = await c.sessions.create(
        user_id=(await c.profiles.upsert(UUID(int=7), {}, "UTC")).user_id,
        goal="run a 5k under 30 minutes",
        intake={},
        import_ids=[],
        use_calendar=False,
        trait_role_model_id=None,
        persona_role_model_id=persona_id,
    )

    await c.evaluate_session(PlanGenerateJobV1(session_id=session.id))

    generate_context = llm.calls[1][2]
    assert "## 原則" in generate_context["persona_context"]
    assert "## 每週結構" in generate_context["persona_context"]


async def test_context_snapshot_is_persisted_for_reproducibility() -> None:
    c = build_test_container(llm=_ready_llm())
    trait_id = await _seed_role_model(c, "穩扎穩打型")
    sid = await seed_session(c, trait_role_model_id=trait_id)

    await c.evaluate_session(PlanGenerateJobV1(session_id=sid))

    s = await c.sessions.get_unscoped(sid)
    assert s is not None
    snapshot = s.context_snapshot or {}
    assert snapshot["trait_context"]
    assert "節奏約束：每週 4–5 次" in snapshot["trait_context"]


async def test_trait_pacing_constrains_generated_plan() -> None:
    # 輕鬆寫意型 allows at most three sessions a week; the LLM asks for six.
    llm = ScriptedLLM([tpl(times=6), tpl(times=3)])
    c = build_test_container(llm=llm)
    trait_id = await _seed_role_model(c, "輕鬆寫意型")
    sid = await seed_session(c, status="generating", trait_role_model_id=trait_id)

    await c.generate_plans(sid)

    for plan in await c.plans.list_for_session(sid):
        tasks = await c.plan_tasks.list(plan.id, None, None)
        weekly = len([t for t in tasks if t.week_index == 0 and t.task_type == "session"])
        assert weekly <= 3, f"{plan.difficulty} exceeds the trait pacing"


async def test_no_role_model_leaves_the_context_blocks_empty() -> None:
    llm = _ready_llm()
    c = build_test_container(llm=llm)
    sid = await seed_session(c)

    await c.evaluate_session(PlanGenerateJobV1(session_id=sid))

    assert llm.calls[0][2]["trait_context"] == ""
    assert llm.calls[0][2]["persona_context"] == ""
