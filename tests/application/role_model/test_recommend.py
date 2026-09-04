"""LLM-backed role model recommendation (plan Task 28, PRD 3.9 / 12.5)."""

from typing import Any
from uuid import UUID, uuid4

from packages.llm.ports import OutputT, Purpose
from services.role_model.application.recommend_role_models import RecommendInput
from services.role_model.container import RoleModelContainer, build_test_container


def _persona_content(summary: str, good_for: list[str]) -> dict[str, Any]:
    return {
        "summary": summary,
        "sections": {
            "principles": ["train easy most of the time"],
            "weekly_structure": "three easy sessions and one hard session",
            "applicability": {"good_for": good_for, "not_for": ["people with no time at all"]},
        },
    }


def _trait_content() -> dict[str, Any]:
    return {
        "summary": "fixed cadence, linear progression",
        "pacing": {
            "sessions_per_week": [4, 5],
            "session_minutes": [30, 60],
            "rest_days_min": 1,
            "progression_rate": 0.10,
            "missed_policy": "same-week",
            "intensity_bias": "medium",
        },
    }


async def _seed_persona(
    container: RoleModelContainer,
    name: str,
    tags: list[str],
    summary: str = "eighty percent easy running",
) -> UUID:
    role_model = await container.role_models.upsert(
        None, "persona", name, tags, _persona_content(summary, ["beginners"])
    )
    return role_model.id


async def _seed_trait(container: RoleModelContainer, name: str) -> UUID:
    role_model = await container.role_models.upsert(
        None, "trait", name, ["cadence:5x-week"], _trait_content()
    )
    return role_model.id


class _RecordingLLM:
    """Base stub: records every call the way FakeLLM does."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, Purpose, dict[str, Any]]] = []


class PickFirstLLM(_RecordingLLM):
    """Recommend the first `count` candidates it is offered."""

    def __init__(self, count: int = 3) -> None:
        super().__init__()
        self._count = count

    async def complete(
        self,
        prompt_name: str,
        context: dict[str, Any],
        output_schema: type[OutputT],
        purpose: Purpose,
    ) -> OutputT:
        self.calls.append((prompt_name, purpose, context))
        picked = list(context["candidates"])[: self._count]
        return output_schema.model_validate(
            {
                "recommendations": [
                    {"role_model_id": c["id"], "name": c["name"], "reason": "fits your cadence"}
                    for c in picked
                ]
            }
        )


class UnknownThenValidLLM(_RecordingLLM):
    """Return an id that is not a candidate first, then a valid pick."""

    async def complete(
        self,
        prompt_name: str,
        context: dict[str, Any],
        output_schema: type[OutputT],
        purpose: Purpose,
    ) -> OutputT:
        self.calls.append((prompt_name, purpose, context))
        first = list(context["candidates"])[0]
        chosen = str(uuid4()) if len(self.calls) == 1 else first["id"]
        return output_schema.model_validate(
            {
                "recommendations": [
                    {"role_model_id": chosen, "name": first["name"], "reason": "fits your cadence"}
                ]
            }
        )


class AlwaysUnknownLLM(_RecordingLLM):
    """Always recommend an id outside the candidate list."""

    async def complete(
        self,
        prompt_name: str,
        context: dict[str, Any],
        output_schema: type[OutputT],
        purpose: Purpose,
    ) -> OutputT:
        self.calls.append((prompt_name, purpose, context))
        return output_schema.model_validate(
            {
                "recommendations": [
                    {"role_model_id": str(uuid4()), "name": "made up", "reason": "invented"}
                ]
            }
        )


async def test_returns_at_most_three() -> None:
    llm = PickFirstLLM(count=3)
    c = build_test_container(llm=llm)
    for index in range(5):
        await _seed_persona(c, f"persona {index}", ["domain:fitness"])

    out = await c.recommend_role_models(RecommendInput(goal="run a 5k", domains=["fitness"]))

    assert len(out) == 3
    assert len(llm.calls[0][2]["candidates"]) == 5


async def test_never_recommends_trait_kind() -> None:
    llm = PickFirstLLM(count=3)
    c = build_test_container(llm=llm)
    trait_ids = {await _seed_trait(c, "steady"), await _seed_trait(c, "hardcore")}
    persona_ids = {
        await _seed_persona(c, "persona a", ["domain:fitness"]),
        await _seed_persona(c, "persona b", ["domain:fitness"]),
        await _seed_persona(c, "persona c", ["domain:fitness"]),
    }

    out = await c.recommend_role_models(RecommendInput(goal="run a 5k"))

    assert {r.role_model_id for r in out} <= persona_ids
    assert not {r.role_model_id for r in out} & trait_ids


async def test_empty_candidates_skips_llm() -> None:
    llm = PickFirstLLM()
    c = build_test_container(llm=llm)
    await _seed_persona(c, "persona a", ["domain:fitness"])

    out = await c.recommend_role_models(
        RecommendInput(goal="x", domains=["nonexistent"]),
    )

    assert out == []
    assert llm.calls == []


async def test_llm_returning_unknown_id_triggers_retry() -> None:
    llm = UnknownThenValidLLM()
    c = build_test_container(llm=llm)
    known = await _seed_persona(c, "persona a", ["domain:fitness"])

    out = await c.recommend_role_models(RecommendInput(goal="run a 5k"))

    assert len(llm.calls) == 2
    assert [r.role_model_id for r in out] == [known]


async def test_falls_back_to_top_scored_when_llm_keeps_failing() -> None:
    llm = AlwaysUnknownLLM()
    c = build_test_container(llm=llm)
    await _seed_persona(c, "top", ["domain:fitness", "goal:endurance"])
    await _seed_persona(c, "middle", ["domain:fitness", "method:80-20"])
    await _seed_persona(c, "bottom", ["domain:fitness"])

    out = await c.recommend_role_models(
        RecommendInput(goal="run a 5k", intake={"goals": ["endurance"], "methods": ["80-20"]}),
    )

    assert len(out) == 3
    assert out[0].reason
    assert out[0].name == "top"


async def test_candidates_passed_to_llm_include_summary_and_applicability() -> None:
    llm = PickFirstLLM(count=1)
    c = build_test_container(llm=llm)
    await _seed_persona(c, "persona a", ["domain:fitness"], summary="eighty percent easy running")

    await c.recommend_role_models(RecommendInput(goal="run a 5k"))

    context = llm.calls[0][2]
    assert "applicability" in str(context)
    assert "eighty percent easy running" in str(context)


async def test_constraint_excluded_candidates_not_offered() -> None:
    llm = PickFirstLLM(count=3)
    c = build_test_container(llm=llm)
    excluded = await _seed_persona(c, "gym only", ["domain:fitness", "constraint:gym-required"])
    await _seed_persona(c, "home friendly", ["domain:fitness"])

    out = await c.recommend_role_models(
        RecommendInput(goal="get stronger", excluded_constraints=["gym-required"]),
    )

    offered = {candidate["id"] for candidate in llm.calls[0][2]["candidates"]}
    assert str(excluded) not in offered
    assert excluded not in {r.role_model_id for r in out}
