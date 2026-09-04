"""GeneratePlans: one baseline template, three difficulties (plan Task 23, PRD 4.3/7.5)."""

from uuid import UUID

from packages.llm.fake import FakeLLM
from packages.repo.entities import Plan
from services.plan_engine.container import PlanEngineContainer, build_test_container
from services.plan_engine.domain.template import PlanTemplate
from tests.application.plan_engine.helpers import (
    FIXTURES_DIR,
    PACING_MAX_THREE,
    AlwaysBadLLM,
    ScriptedLLM,
    seed_session,
    seed_trait,
    tpl,
)


async def _ready_container() -> tuple[PlanEngineContainer, UUID]:
    """A container whose LLM answers from the shipped fixture, and a session ready to generate."""
    c = build_test_container(llm=FakeLLM(FIXTURES_DIR))
    sid = await seed_session(c, status="generating")
    return c, sid


async def _hard_plan(c: PlanEngineContainer, session_id: UUID) -> Plan:
    plans = await c.plans.list_for_session(session_id)
    return next(p for p in plans if p.difficulty == "hard")


async def test_generates_exactly_three_plans_one_per_difficulty() -> None:
    c, sid = await _ready_container()

    ids = await c.generate_plans(sid)

    plans = await c.plans.list_for_session(sid)
    assert len(ids) == 3
    assert {p.difficulty for p in plans} == {"easy", "hard", "extremely_hard"}
    assert all(p.status == "draft" for p in plans)


async def test_three_plans_share_goal_statement_and_criteria() -> None:
    c, sid = await _ready_container()
    await c.generate_plans(sid)

    plans = await c.plans.list_for_session(sid)
    assert len({p.goal_statement for p in plans}) == 1
    assert len({tuple(p.structure["success_criteria"]) for p in plans}) == 1


async def test_easy_plan_has_more_weeks_than_hard() -> None:
    c, sid = await _ready_container()
    await c.generate_plans(sid)

    by = {p.difficulty: p for p in await c.plans.list_for_session(sid)}
    assert by["easy"].duration_weeks > by["hard"].duration_weeks
    assert by["extremely_hard"].duration_weeks < by["hard"].duration_weeks


async def test_plan_tasks_are_created_with_absolute_times() -> None:
    c, sid = await _ready_container()
    await c.generate_plans(sid)
    plan = await _hard_plan(c, sid)

    tasks = await c.plan_tasks.list(plan.id, None, None)
    assert tasks
    assert all(t.start_at.tzinfo is not None for t in tasks)
    assert all(t.end_at > t.start_at or t.all_day for t in tasks)


async def test_template_stored_verbatim_for_revision() -> None:
    c, sid = await _ready_container()
    await c.generate_plans(sid)
    plan = await _hard_plan(c, sid)

    assert PlanTemplate.model_validate(plan.template).goal_statement == plan.goal_statement


async def test_pacing_violation_triggers_retry_with_feedback() -> None:
    # the trait pacing allows at most three sessions a week; the first template asks for six
    llm = ScriptedLLM([tpl(times=6), tpl(times=3)])
    c = build_test_container(llm=llm)
    trait_id = await seed_trait(c, PACING_MAX_THREE)
    sid = await seed_session(c, status="generating", trait_role_model_id=trait_id)

    await c.generate_plans(sid)

    assert llm.contexts[1]["_violations"]  # the violations were fed back
    plan = await _hard_plan(c, sid)
    tasks = await c.plan_tasks.list(plan.id, None, None)
    assert len([t for t in tasks if t.week_index == 0 and t.task_type == "session"]) <= 3


async def test_degrades_to_conservative_template_when_retries_exhausted() -> None:
    c = build_test_container(llm=AlwaysBadLLM())
    trait_id = await seed_trait(c, PACING_MAX_THREE)
    sid = await seed_session(c, status="generating", trait_role_model_id=trait_id)

    await c.generate_plans(sid)

    plan = (await c.plans.list_for_session(sid))[0]
    assert plan.duration_weeks in (12, 15, 10)  # the 12-week baseline scaled by difficulty
    assert any("系統假設" in a for a in plan.structure["assumptions"])


async def test_assumption_added_when_calendar_not_connected() -> None:
    c, sid = await _ready_container()
    await c.generate_plans(sid)
    plan = await _hard_plan(c, sid)

    assert any("行事曆" in a for a in plan.structure["assumptions"])


async def test_deadline_matches_duration() -> None:
    c, sid = await _ready_container()
    await c.generate_plans(sid)

    for plan in await c.plans.list_for_session(sid):
        assert (plan.deadline - plan.start_date).days == plan.duration_weeks * 7 - 1


async def test_session_ends_in_done() -> None:
    c, sid = await _ready_container()
    await c.generate_plans(sid)

    session = await c.sessions.get_unscoped(sid)
    assert session is not None
    assert session.status == "done"


async def test_readiness_and_template_degradation_are_reported_separately() -> None:
    """A readiness pass that gave up is not the same as the template being replaced.

    Saying "the plan came from a conservative default" when the model actually produced
    it would mislead the user about what they are looking at.
    """
    c, sid = await _ready_container()

    await c.generate_plans(sid, forced_missing=["baseline"], degraded=True)

    plan = (await c.plans.list_for_session(sid))[0]
    assumptions = plan.structure["assumptions"]
    assert any("追問階段未能問齊所需資訊" in a for a in assumptions)
    assert not any("已改用系統保守預設" in a for a in assumptions)
