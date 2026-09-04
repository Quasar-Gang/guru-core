"""Revision endpoints and the accept / reject decision (plan Task 37, PRD 3.8)."""

from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID

import httpx
import pytest

from packages.queue import ExportJobV1, InMemoryQueue, JobPayload, PlanReviseJobV1
from packages.repo.entities import NewPlan, NewPlanTask
from services.api.adapters.clock import FakeClock
from services.api.container import ApiContainer, build_test_container

#: Everything is anchored on a Monday so the local and UTC calendar days agree (profiles
#: created by the `auth_user_id` fixture are on UTC).
NOW = datetime(2026, 4, 6, 9, 0, tzinfo=UTC)
CUTOFF = datetime(2026, 4, 6, 0, 0, tzinfo=UTC)
START = date(2026, 3, 2)
OLD_DEADLINE = date(2026, 5, 24)
NEW_DEADLINE = date(2026, 6, 7)
GOAL = "run 5k under 30 minutes"
REDUCED_GOAL = "run 5k under 33 minutes"


@pytest.fixture
def container() -> ApiContainer:
    """The shared fixture, pinned to `NOW` so "today" is inside the seeded plan."""
    return build_test_container(clock=FakeClock(NOW))


def _enqueued(container: ApiContainer) -> list[JobPayload]:
    queue = container.queue
    assert isinstance(queue, InMemoryQueue)
    return queue.enqueued


def _phases(weeks: int) -> list[dict[str, Any]]:
    return [
        {
            "index": 0,
            "name": "base",
            "week_start": 0,
            "week_end": weeks - 1,
            "focus": "focus",
            "milestone": {"title": "milestone", "metric": "metric"},
        }
    ]


def _template(weeks: int, goal: str) -> dict[str, Any]:
    return {
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
                "times_per_week": 1,
            }
        ],
    }


def _task(week_index: int, start_at: datetime) -> NewPlanTask:
    return NewPlanTask(
        template_key="run",
        week_index=week_index,
        task_type="session",
        title="run",
        start_at=start_at,
        end_at=start_at + timedelta(minutes=40),
    )


def _proposal(weeks: int, goal: str) -> list[dict[str, Any]]:
    """The `[plan_patch, task, ...]` shape the Plan Engine writes into `proposed_tasks`."""
    patch = {
        "goal_statement": goal,
        "duration_weeks": weeks,
        "deadline": (START + timedelta(days=weeks * 7 - 1)).isoformat(),
        "template": _template(weeks, goal),
        "structure": {
            "phases": _phases(weeks),
            "success_criteria": ["finish 5k under 30:00"],
            "assumptions": [],
        },
    }
    tasks = [
        _task(week, CUTOFF + timedelta(days=7 * index, hours=19))
        for index, week in enumerate(range(5, weeks))
    ]
    return [patch, *(task.model_dump(mode="json") for task in tasks)]


def _diff(kind: str) -> list[dict[str, Any]]:
    after = {
        "title": "run",
        "start_at": (CUTOFF + timedelta(hours=19)).isoformat(),
        "end_at": (CUTOFF + timedelta(hours=19, minutes=40)).isoformat(),
        "all_day": False,
    }
    return [
        {
            "template_key": "run",
            "week_index": 5,
            "occurrence": 0,
            "kind": kind,
            "title": "run",
            "before": None,
            "after": after,
        }
    ]


async def _plan(container: ApiContainer, user_id: UUID, *, status: str = "active") -> UUID:
    session = await container.plan_sessions.create(
        user_id=user_id,
        goal=GOAL,
        intake={},
        import_ids=[],
        use_calendar=False,
        trait_role_model_id=None,
        persona_role_model_id=None,
    )
    [plan] = await container.plans.create_many(
        [
            NewPlan(
                user_id=user_id,
                session_id=session.id,
                title="run 5k",
                difficulty="hard",
                status=status,
                goal_statement=GOAL,
                duration_weeks=12,
                start_date=START,
                deadline=OLD_DEADLINE,
                template=_template(12, GOAL),
                structure={
                    "phases": _phases(12),
                    "success_criteria": ["finish 5k under 30:00"],
                    "assumptions": [],
                },
            )
        ]
    )
    await container.plan_tasks.replace_all(
        plan.id,
        [
            _task(week, start_at)
            for week, start_at in (
                (0, CUTOFF - timedelta(days=28, hours=-19)),
                (4, CUTOFF - timedelta(days=7, hours=-19)),
                (5, CUTOFF + timedelta(hours=19)),
                (6, CUTOFF + timedelta(days=7, hours=19)),
            )
        ],
    )
    return plan.id


async def _proposed_revision(
    container: ApiContainer,
    plan_id: UUID,
    *,
    strategy: str = "postpone",
    weeks: int = 14,
    goal: str = GOAL,
) -> UUID:
    revision = await container.plan_revisions.create(plan_id, strategy, None)
    await container.plan_revisions.set_proposal(
        revision.id, _proposal(weeks, goal), _diff("added"), "延後兩週把落後的量補回來"
    )
    await container.plan_revisions.set_status(revision.id, "proposed", None)
    return revision.id


async def test_create_revision_enqueues_the_job(
    client: httpx.AsyncClient,
    container: ApiContainer,
    auth_headers: dict[str, str],
    auth_user_id: UUID,
) -> None:
    plan_id = await _plan(container, auth_user_id)

    response = await client.post(
        f"/v1/plans/{plan_id}/revisions",
        json={"strategy": "postpone", "note": "出差兩週"},
        headers=auth_headers,
    )

    assert response.status_code == 202
    revision_id = UUID(response.json()["revision_id"])
    assert _enqueued(container)[-1] == PlanReviseJobV1(
        plan_id=plan_id, revision_id=revision_id, strategy="postpone"
    )


async def test_create_revision_on_draft_plan_conflicts(
    client: httpx.AsyncClient,
    container: ApiContainer,
    auth_headers: dict[str, str],
    auth_user_id: UUID,
) -> None:
    plan_id = await _plan(container, auth_user_id, status="draft")

    response = await client.post(
        f"/v1/plans/{plan_id}/revisions", json={"strategy": "postpone"}, headers=auth_headers
    )

    assert response.status_code == 409


async def test_second_open_revision_conflicts(
    client: httpx.AsyncClient,
    container: ApiContainer,
    auth_headers: dict[str, str],
    auth_user_id: UUID,
) -> None:
    plan_id = await _plan(container, auth_user_id)
    await _proposed_revision(container, plan_id)

    response = await client.post(
        f"/v1/plans/{plan_id}/revisions", json={"strategy": "reduce"}, headers=auth_headers
    )

    assert response.status_code == 409


async def test_invalid_strategy_is_422(
    client: httpx.AsyncClient,
    container: ApiContainer,
    auth_headers: dict[str, str],
    auth_user_id: UUID,
) -> None:
    plan_id = await _plan(container, auth_user_id)

    response = await client.post(
        f"/v1/plans/{plan_id}/revisions", json={"strategy": "rewrite"}, headers=auth_headers
    )

    assert response.status_code == 422


async def test_get_revision_returns_diff_and_summary(
    client: httpx.AsyncClient,
    container: ApiContainer,
    auth_headers: dict[str, str],
    auth_user_id: UUID,
) -> None:
    plan_id = await _plan(container, auth_user_id)
    revision_id = await _proposed_revision(container, plan_id)

    body = (
        await client.get(f"/v1/plans/{plan_id}/revisions/{revision_id}", headers=auth_headers)
    ).json()

    summary = body["summary"]
    assert summary["moved"] + summary["added"] + summary["removed"] > 0
    assert len(body["diff"]) == sum(summary.values())
    assert body["status"] == "proposed"
    assert body["rationale"]


async def test_list_revisions_returns_every_revision(
    client: httpx.AsyncClient,
    container: ApiContainer,
    auth_headers: dict[str, str],
    auth_user_id: UUID,
) -> None:
    plan_id = await _plan(container, auth_user_id)
    revision_id = await _proposed_revision(container, plan_id)

    body = (await client.get(f"/v1/plans/{plan_id}/revisions", headers=auth_headers)).json()

    assert [UUID(item["id"]) for item in body] == [revision_id]


async def test_accept_replaces_future_tasks_only(
    client: httpx.AsyncClient,
    container: ApiContainer,
    auth_headers: dict[str, str],
    auth_user_id: UUID,
) -> None:
    plan_id = await _plan(container, auth_user_id)
    revision_id = await _proposed_revision(container, plan_id)
    before_past = await container.plan_tasks.list(plan_id, None, CUTOFF)

    response = await client.post(
        f"/v1/plans/{plan_id}/revisions/{revision_id}/accept", headers=auth_headers
    )

    assert response.status_code == 200
    assert response.json()["status"] == "accepted"
    assert await container.plan_tasks.list(plan_id, None, CUTOFF) == before_past
    future = await container.plan_tasks.list(plan_id, CUTOFF, None)
    assert future != []
    assert {task.week_index for task in future} == set(range(5, 14))


async def test_accept_updates_plan_deadline_for_postpone(
    client: httpx.AsyncClient,
    container: ApiContainer,
    auth_headers: dict[str, str],
    auth_user_id: UUID,
) -> None:
    plan_id = await _plan(container, auth_user_id)
    revision_id = await _proposed_revision(container, plan_id)

    await client.post(f"/v1/plans/{plan_id}/revisions/{revision_id}/accept", headers=auth_headers)

    plan = await container.plans.get(auth_user_id, plan_id)
    assert plan is not None
    assert plan.deadline == NEW_DEADLINE
    assert plan.deadline > OLD_DEADLINE
    assert plan.duration_weeks == 14


async def test_accept_updates_goal_statement_for_reduce(
    client: httpx.AsyncClient,
    container: ApiContainer,
    auth_headers: dict[str, str],
    auth_user_id: UUID,
) -> None:
    plan_id = await _plan(container, auth_user_id)
    revision_id = await _proposed_revision(
        container, plan_id, strategy="reduce", weeks=12, goal=REDUCED_GOAL
    )

    await client.post(f"/v1/plans/{plan_id}/revisions/{revision_id}/accept", headers=auth_headers)

    plan = await container.plans.get(auth_user_id, plan_id)
    assert plan is not None
    assert plan.goal_statement == REDUCED_GOAL
    assert plan.deadline == OLD_DEADLINE
    assert plan.template["goal_statement"] == REDUCED_GOAL


async def test_accept_enqueues_incremental_export_when_exported(
    client: httpx.AsyncClient,
    container: ApiContainer,
    auth_headers: dict[str, str],
    auth_user_id: UUID,
) -> None:
    plan_id = await _plan(container, auth_user_id)
    revision_id = await _proposed_revision(container, plan_id)
    await container.plan_exports.upsert(plan_id, "google_calendar", "synced", "cal-1", NOW, None)

    await client.post(f"/v1/plans/{plan_id}/revisions/{revision_id}/accept", headers=auth_headers)

    assert _enqueued(container)[-1] == ExportJobV1(
        plan_id=plan_id, target="google_calendar", mode="incremental"
    )


async def test_reject_leaves_plan_untouched(
    client: httpx.AsyncClient,
    container: ApiContainer,
    auth_headers: dict[str, str],
    auth_user_id: UUID,
) -> None:
    plan_id = await _plan(container, auth_user_id)
    revision_id = await _proposed_revision(container, plan_id)
    before = await container.plan_tasks.list(plan_id, None, None)

    response = await client.post(
        f"/v1/plans/{plan_id}/revisions/{revision_id}/reject", headers=auth_headers
    )

    assert response.json()["status"] == "rejected"
    assert await container.plan_tasks.list(plan_id, None, None) == before
    plan = await container.plans.get(auth_user_id, plan_id)
    assert plan is not None and plan.deadline == OLD_DEADLINE


async def test_decide_on_pending_revision_conflicts(
    client: httpx.AsyncClient,
    container: ApiContainer,
    auth_headers: dict[str, str],
    auth_user_id: UUID,
) -> None:
    plan_id = await _plan(container, auth_user_id)
    revision = await container.plan_revisions.create(plan_id, "postpone", None)

    response = await client.post(
        f"/v1/plans/{plan_id}/revisions/{revision.id}/accept", headers=auth_headers
    )

    assert response.status_code == 409
