"""Plan lifecycle endpoints: list, detail, rename, activate, archive, delete.

Plan Task 30, PRD 3.5 / 5.
"""

from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest

from packages.repo import NewPlan, NewPlanTask, Plan
from services.api.container import ApiContainer

_START = date(2026, 3, 2)

_STRUCTURE: dict[str, Any] = {
    "phases": [
        {
            "index": 0,
            "name": "base",
            "week_start": 0,
            "week_end": 1,
            "focus": "aerobic base",
            "milestone": {"title": "5k time trial", "metric": "under 33 minutes"},
        },
        {
            "index": 1,
            "name": "sharpen",
            "week_start": 2,
            "week_end": 3,
            "focus": "speed work",
            "milestone": {"title": "final time trial", "metric": "under 30 minutes"},
        },
    ],
    "success_criteria": ["finish 5k under 30 minutes"],
    "assumptions": ["three free evenings a week"],
}

_TEMPLATE: dict[str, Any] = {
    "weekly_template": [
        {"template_key": "run", "times_per_week": 3, "duration_minutes": 40},
    ]
}


async def _session_id(container: ApiContainer, user_id: UUID) -> UUID:
    session = await container.plan_sessions.create(
        user_id=user_id,
        goal="run 5k under 30 minutes",
        intake={},
        import_ids=[],
        use_calendar=False,
        trait_role_model_id=None,
        persona_role_model_id=None,
    )
    await container.plan_sessions.set_status(session.id, "done")
    return session.id


async def _three_plans(container: ApiContainer, user_id: UUID) -> list[Plan]:
    """One session with the three generated difficulties, all still `draft`."""
    session_id = await _session_id(container, user_id)
    return await container.plans.create_many(
        [
            NewPlan(
                user_id=user_id,
                session_id=session_id,
                title=f"5k plan ({difficulty})",
                difficulty=difficulty,
                status="draft",
                goal_statement="run 5k under 30 minutes",
                duration_weeks=4,
                start_date=_START,
                deadline=_START + timedelta(weeks=4),
                template=_TEMPLATE,
                structure=_STRUCTURE,
            )
            for difficulty in ("easy", "hard", "extremely_hard")
        ]
    )


def _task(index: int, *, status: str = "pending", phase_index: int = 0) -> NewPlanTask:
    start_at = datetime(2026, 3, 2, 18, 0, tzinfo=UTC) + timedelta(days=index)
    return NewPlanTask(
        template_key="run",
        week_index=index // 7,
        phase_index=phase_index,
        occurrence=index,
        task_type="session",
        title=f"easy run {index}",
        start_at=start_at,
        end_at=start_at + timedelta(minutes=40),
        status=status,
        sort_order=index,
    )


def _checkpoint(index: int, phase_index: int) -> NewPlanTask:
    start_at = datetime(2026, 3, 8, 0, 0, tzinfo=UTC) + timedelta(weeks=phase_index)
    return NewPlanTask(
        template_key=f"checkpoint_p{phase_index}",
        week_index=index,
        phase_index=phase_index,
        occurrence=0,
        task_type="checkpoint",
        title=_STRUCTURE["phases"][phase_index]["milestone"]["title"],
        description=_STRUCTURE["phases"][phase_index]["milestone"]["metric"],
        start_at=start_at,
        end_at=start_at + timedelta(days=1),
        all_day=True,
    )


async def _plan_with_tasks(
    container: ApiContainer, user_id: UUID, tasks: list[NewPlanTask]
) -> Plan:
    plan = (await _three_plans(container, user_id))[0]
    await container.plan_tasks.replace_all(plan.id, tasks)
    return plan


def _mixed_tasks() -> list[NewPlanTask]:
    """10 tasks: 3 done, 1 missed, 1 skipped, 5 pending."""
    statuses = ["done"] * 3 + ["missed", "skipped"] + ["pending"] * 5
    return [_task(i, status=status) for i, status in enumerate(statuses)]


# --------------------------------------------------------------------- activate / rename


async def test_activate_demotes_siblings_to_draft(
    container: ApiContainer, auth_user_id: UUID
) -> None:
    plans = await _three_plans(container, auth_user_id)

    await container.update_plan(auth_user_id, plans[0].id, title=None, status="active")
    await container.update_plan(auth_user_id, plans[1].id, title=None, status="active")

    fresh = await container.list_plans(auth_user_id, None)
    assert [p.status for p in fresh].count("active") == 1
    assert next(p.status for p in fresh if p.id == plans[1].id) == "active"


async def test_activate_sets_activated_at(container: ApiContainer, auth_user_id: UUID) -> None:
    plan = (await _three_plans(container, auth_user_id))[0]

    await container.update_plan(auth_user_id, plan.id, title=None, status="active")

    stored = await container.plans.get(auth_user_id, plan.id)
    assert stored is not None
    assert stored.activated_at == container.clock.now()


async def test_rename_only_changes_title(
    client: httpx.AsyncClient,
    container: ApiContainer,
    auth_headers: dict[str, str],
    auth_user_id: UUID,
) -> None:
    plan = (await _three_plans(container, auth_user_id))[0]

    r = await client.patch(
        f"/v1/plans/{plan.id}", json={"title": "spring 5k"}, headers=auth_headers
    )

    assert r.status_code == 200
    assert r.json()["title"] == "spring 5k"
    assert r.json()["status"] == "draft"
    stored = await container.plans.get(auth_user_id, plan.id)
    assert stored is not None
    assert stored.activated_at is None


async def test_illegal_transition_is_409(
    client: httpx.AsyncClient,
    container: ApiContainer,
    auth_headers: dict[str, str],
    auth_user_id: UUID,
) -> None:
    plan = (await _three_plans(container, auth_user_id))[0]
    await container.archive_plan(auth_user_id, plan.id)

    r = await client.patch(f"/v1/plans/{plan.id}", json={"status": "draft"}, headers=auth_headers)

    assert r.status_code == 409


# ------------------------------------------------------------------------------ listing


async def test_list_filters_by_status(
    client: httpx.AsyncClient,
    container: ApiContainer,
    auth_headers: dict[str, str],
    auth_user_id: UUID,
) -> None:
    plans = await _three_plans(container, auth_user_id)
    await container.update_plan(auth_user_id, plans[0].id, title=None, status="active")

    body = (await client.get("/v1/plans?status=active", headers=auth_headers)).json()

    assert [UUID(p["id"]) for p in body] == [plans[0].id]


async def test_archived_plans_hidden_from_default_list(
    client: httpx.AsyncClient,
    container: ApiContainer,
    auth_headers: dict[str, str],
    auth_user_id: UUID,
) -> None:
    plans = await _three_plans(container, auth_user_id)
    await container.archive_plan(auth_user_id, plans[2].id)

    listed = (await client.get("/v1/plans", headers=auth_headers)).json()
    archived = (await client.get("/v1/plans?status=archived", headers=auth_headers)).json()

    assert {UUID(p["id"]) for p in listed} == {plans[0].id, plans[1].id}
    assert [UUID(p["id"]) for p in archived] == [plans[2].id]


async def test_get_plan_of_other_user_is_404(
    client: httpx.AsyncClient, container: ApiContainer, auth_headers: dict[str, str]
) -> None:
    other = await container.users.create("other@example.com", "other-sub")
    plan = (await _three_plans(container, other.id))[0]

    r = await client.get(f"/v1/plans/{plan.id}", headers=auth_headers)

    assert r.status_code == 404


# ----------------------------------------------------------------------------- progress


async def test_progress_counts_and_rate(
    client: httpx.AsyncClient,
    container: ApiContainer,
    auth_headers: dict[str, str],
    auth_user_id: UUID,
) -> None:
    plan = await _plan_with_tasks(container, auth_user_id, _mixed_tasks())

    progress = (await client.get(f"/v1/plans/{plan.id}", headers=auth_headers)).json()["progress"]

    assert progress["total"] == 10
    assert progress["done"] == 3
    assert progress["missed"] == 1
    assert progress["skipped"] == 1
    assert progress["pending"] == 5
    assert progress["completion_rate"] == pytest.approx(0.6)


async def test_completion_rate_zero_when_nothing_resolved(
    container: ApiContainer, auth_user_id: UUID
) -> None:
    plan = await _plan_with_tasks(container, auth_user_id, [_task(i) for i in range(4)])

    detail = await container.get_plan(auth_user_id, plan.id)

    assert detail.progress.completion_rate == 0.0


async def test_phase_rates_cover_every_phase(container: ApiContainer, auth_user_id: UUID) -> None:
    tasks = [
        _task(0, status="done", phase_index=0),
        _task(1, status="pending", phase_index=0),
        _task(2, status="done", phase_index=1),
    ]
    plan = await _plan_with_tasks(container, auth_user_id, tasks)

    rates = (await container.get_plan(auth_user_id, plan.id)).progress.phase_rates

    assert [r.phase_index for r in rates] == [0, 1]
    assert [r.name for r in rates] == ["base", "sharpen"]
    assert (rates[0].done, rates[0].total) == (1, 2)
    assert rates[0].rate == pytest.approx(0.5)
    assert (rates[1].done, rates[1].total) == (1, 1)
    assert rates[1].rate == pytest.approx(1.0)


async def test_checkpoints_listed_with_due_date(
    client: httpx.AsyncClient,
    container: ApiContainer,
    auth_headers: dict[str, str],
    auth_user_id: UUID,
) -> None:
    tasks = [_task(0), _checkpoint(1, 0), _checkpoint(3, 1)]
    plan = await _plan_with_tasks(container, auth_user_id, tasks)

    body = (await client.get(f"/v1/plans/{plan.id}", headers=auth_headers)).json()

    checkpoints = body["progress"]["checkpoints"]
    assert [c["phase_index"] for c in checkpoints] == [0, 1]
    assert checkpoints[0]["title"] == "5k time trial"
    assert checkpoints[0]["metric"] == "under 33 minutes"
    assert checkpoints[0]["due_at"].startswith("2026-03-08")
    assert checkpoints[0]["status"] == "pending"
    assert [p["name"] for p in body["phases"]] == ["base", "sharpen"]
    assert body["success_criteria"] == ["finish 5k under 30 minutes"]
    assert body["assumptions"] == ["three free evenings a week"]


# ------------------------------------------------------------------------------- delete


async def test_delete_removes_plan_and_tasks(
    client: httpx.AsyncClient,
    container: ApiContainer,
    auth_headers: dict[str, str],
    auth_user_id: UUID,
) -> None:
    plan = await _plan_with_tasks(container, auth_user_id, _mixed_tasks())

    r = await client.delete(f"/v1/plans/{plan.id}", headers=auth_headers)

    assert r.status_code == 204
    assert await container.plans.get(auth_user_id, plan.id) is None
    assert await container.plan_tasks.list(plan.id, None, None) == []


async def test_delete_of_unknown_plan_is_404(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    r = await client.delete(f"/v1/plans/{uuid4()}", headers=auth_headers)
    assert r.status_code == 404
