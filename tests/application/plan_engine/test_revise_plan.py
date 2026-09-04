"""The `plan.revise` use case (plan Task 36, PRD 3.8)."""

from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID

from packages.queue import PlanReviseJobV1
from packages.repo.entities import NewPlan, NewPlanTask
from services.plan_engine.container import FakeClock, PlanEngineContainer
from services.plan_engine.container import build_test_container as build_engine_container
from services.plan_engine.domain.capacity import Capacity
from services.plan_engine.domain.scheduler import schedule
from services.plan_engine.domain.template import PlanTemplate
from tests.application.plan_engine.helpers import ScriptedLLM, seed_session

#: A Monday five weeks into a plan that started on 2026-03-02.
NOW = datetime(2026, 4, 6, 9, 0, tzinfo=UTC)
CUTOFF = datetime(2026, 4, 6, 0, 0, tzinfo=UTC)
START = date(2026, 3, 2)
GOAL = "run 5k under 30 minutes"


def _phases(weeks: int) -> list[dict[str, Any]]:
    per_phase = weeks // 3
    bounds = [(0, per_phase - 1), (per_phase, 2 * per_phase - 1), (2 * per_phase, weeks - 1)]
    names = ["base", "build", "peak"]
    return [
        {
            "index": index,
            "name": names[index],
            "week_start": start,
            "week_end": end,
            "focus": "focus",
            "milestone": {"title": "milestone", "metric": "metric"},
        }
        for index, (start, end) in enumerate(bounds)
    ]


def _template(*, weeks: int = 12, goal: str = GOAL) -> PlanTemplate:
    return PlanTemplate.model_validate(
        {
            "title": "run 5k",
            "goal_statement": goal,
            "duration_weeks": weeks,
            "assumptions": [],
            "success_criteria": ["finish 5k under 30:00"],
            "phases": _phases(weeks),
            "weekly_template": [
                {
                    "key": "run",
                    "title": "run",
                    "task_type": "session",
                    "day_hint": "any",
                    "slot_hint": "evening",
                    "duration_minutes": 40,
                    "description": "steady run",
                    "times_per_week": 3,
                }
            ],
        }
    )


def _payload(template: PlanTemplate, rationale: str) -> dict[str, Any]:
    return {"template": template.model_dump(mode="json"), "rationale": rationale}


POSTPONED = _payload(_template(weeks=15), "為了補回缺席的週次，把期程延後三週。")
BAD_GOAL = _payload(_template(weeks=15, goal="run 10k"), "延後三週，順便換個目標。")


def _container(payload: dict[str, Any]) -> PlanEngineContainer:
    return build_engine_container(clock=FakeClock(NOW), llm=ScriptedLLM([payload]))


async def _seed_active_plan(container: PlanEngineContainer, strategy: str) -> tuple[UUID, UUID]:
    """An active 12-week plan whose first five weeks are already done, plus a pending revision."""
    session_id = await seed_session(container)
    session = await container.sessions.get_unscoped(session_id)
    assert session is not None

    template = _template()
    result = schedule(
        template,
        start_date=START,
        capacity=Capacity.default("UTC"),
        busy=[],
        pacing=None,
        config=container.scheduler_config,
    )
    [plan] = await container.plans.create_many(
        [
            NewPlan(
                user_id=session.user_id,
                session_id=session_id,
                title=template.title,
                difficulty="hard",
                status="active",
                goal_statement=template.goal_statement,
                duration_weeks=template.duration_weeks,
                start_date=START,
                deadline=START + timedelta(days=template.duration_weeks * 7 - 1),
                template=template.model_dump(mode="json"),
                structure={
                    "phases": [phase.model_dump(mode="json") for phase in template.phases],
                    "success_criteria": list(template.success_criteria),
                    "assumptions": [],
                },
            )
        ]
    )
    await container.plan_tasks.replace_all(
        plan.id, [NewPlanTask(**task.model_dump()) for task in result.tasks]
    )
    for task in await container.plan_tasks.list(plan.id, None, CUTOFF):
        await container.plan_tasks.update_fields(task.id, status="done", completed_at=NOW)

    revision = await container.plan_revisions.create(plan.id, strategy, None)
    return plan.id, revision.id


def _job(plan_id: UUID, revision_id: UUID, strategy: str = "postpone") -> PlanReviseJobV1:
    return PlanReviseJobV1(plan_id=plan_id, revision_id=revision_id, strategy=strategy)  # type: ignore[arg-type]


async def test_revise_produces_proposed_status_with_diff() -> None:
    container = _container(POSTPONED)
    plan_id, revision_id = await _seed_active_plan(container, "postpone")

    await container.revise_plan(_job(plan_id, revision_id))

    revision = await container.plan_revisions.get_unscoped(revision_id)
    assert revision is not None
    assert revision.status == "proposed"
    assert revision.diff
    assert revision.rationale
    assert revision.proposed_tasks


async def test_revise_only_reschedules_future_tasks() -> None:
    container = _container(POSTPONED)
    plan_id, revision_id = await _seed_active_plan(container, "postpone")

    await container.revise_plan(_job(plan_id, revision_id))

    revision = await container.plan_revisions.get_unscoped(revision_id)
    assert revision is not None and revision.diff is not None
    for entry in revision.diff:
        for side in ("before", "after"):
            snapshot = entry[side]
            if snapshot is not None:
                assert datetime.fromisoformat(snapshot["start_at"]) >= CUTOFF


async def test_past_done_tasks_untouched() -> None:
    container = _container(POSTPONED)
    plan_id, revision_id = await _seed_active_plan(container, "postpone")
    before = await container.plan_tasks.list(plan_id, None, CUTOFF)

    await container.revise_plan(_job(plan_id, revision_id))

    assert await container.plan_tasks.list(plan_id, None, CUTOFF) == before


async def test_proposal_extends_the_plan_for_postpone() -> None:
    container = _container(POSTPONED)
    plan_id, revision_id = await _seed_active_plan(container, "postpone")

    await container.revise_plan(_job(plan_id, revision_id))

    revision = await container.plan_revisions.get_unscoped(revision_id)
    assert revision is not None and revision.proposed_tasks is not None
    header, *tasks = revision.proposed_tasks
    assert header["duration_weeks"] == 15
    assert header["deadline"] == (START + timedelta(days=15 * 7 - 1)).isoformat()
    assert tasks
    assert all(datetime.fromisoformat(task["start_at"]) >= CUTOFF for task in tasks)


async def test_revise_marks_failed_when_llm_never_satisfies_strategy() -> None:
    container = _container(BAD_GOAL)
    plan_id, revision_id = await _seed_active_plan(container, "postpone")

    await container.revise_plan(_job(plan_id, revision_id))

    revision = await container.plan_revisions.get_unscoped(revision_id)
    assert revision is not None
    assert revision.status == "failed"
    assert revision.proposed_tasks is None


async def test_revise_is_idempotent_on_already_decided_revision() -> None:
    container = _container(POSTPONED)
    plan_id, revision_id = await _seed_active_plan(container, "postpone")
    await container.plan_revisions.set_status(revision_id, "accepted", NOW)

    await container.revise_plan(_job(plan_id, revision_id))

    llm = container.llm
    assert isinstance(llm, ScriptedLLM)
    assert llm.calls == []
