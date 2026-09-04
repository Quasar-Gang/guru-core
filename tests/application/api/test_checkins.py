"""Daily check-in endpoints (plan Task 32, PRD 3.7 / 5)."""

from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4

import httpx

from packages.queue import ExportJobV1, InMemoryQueue, JobPayload
from packages.repo.entities import NewPlan, NewPlanTask
from services.api.application.submit_checkin import CheckinResultInput
from services.api.container import ApiContainer

START = datetime(2026, 9, 7, 16, 0, tzinfo=UTC)


def _enqueued(container: ApiContainer) -> list[JobPayload]:
    """The fake queue's log; the test container always wires an `InMemoryQueue`."""
    queue = container.queue
    assert isinstance(queue, InMemoryQueue)
    return queue.enqueued


def _new_task(start_at: datetime, title: str) -> NewPlanTask:
    return NewPlanTask(
        template_key="easy_run",
        week_index=0,
        task_type="practice",
        title=title,
        start_at=start_at,
        end_at=start_at + timedelta(hours=1),
    )


async def _plan_with_tasks(container: ApiContainer, user_id: UUID, count: int) -> UUID:
    session = await container.plan_sessions.create(
        user_id=user_id,
        goal="run 5k under 30 minutes",
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
                difficulty="standard",
                goal_statement="run 5k under 30 minutes",
                duration_weeks=8,
                start_date=date(2026, 9, 7),
                deadline=date(2026, 11, 2),
            )
        ]
    )
    await container.plan_tasks.replace_all(
        plan.id,
        [_new_task(START + timedelta(days=i), f"task {i}") for i in range(count)],
    )
    return plan.id


async def _task_ids(container: ApiContainer, plan_id: UUID) -> list[UUID]:
    return [t.id for t in await container.plan_tasks.list(plan_id, None, None)]


async def test_checkin_syncs_task_status(
    client: httpx.AsyncClient,
    container: ApiContainer,
    auth_headers: dict[str, str],
    auth_user_id: UUID,
) -> None:
    plan_id = await _plan_with_tasks(container, auth_user_id, 2)
    first, second = await _task_ids(container, plan_id)

    r = await client.post(
        f"/v1/plans/{plan_id}/checkins",
        json={
            "checkin_date": "2026-09-08",
            "results": [
                {"task_id": str(first), "status": "done"},
                {"task_id": str(second), "status": "missed", "reason": "rained"},
            ],
            "note": "tough day",
        },
        headers=auth_headers,
    )

    assert r.status_code == 200
    tasks = {t.id: t for t in await container.plan_tasks.list(plan_id, None, None)}
    assert tasks[first].status == "done"
    assert tasks[first].completed_at is not None
    assert tasks[second].status == "missed"
    assert tasks[second].missed_reason == "rained"


async def test_checkin_marks_tasks_dirty(container: ApiContainer, auth_user_id: UUID) -> None:
    plan_id = await _plan_with_tasks(container, auth_user_id, 1)
    [task_id] = await _task_ids(container, plan_id)
    await container.plan_tasks.update_fields(task_id, external_ref="evt-1", synced_at=START)

    await container.submit_checkin(
        auth_user_id,
        plan_id,
        date(2026, 9, 8),
        [CheckinResultInput(task_id=task_id, status="done")],
        None,
    )

    [fresh] = await container.plan_tasks.list(plan_id, None, None)
    assert fresh.synced_at is None


async def test_resubmitting_the_same_day_overwrites(
    container: ApiContainer, auth_user_id: UUID
) -> None:
    plan_id = await _plan_with_tasks(container, auth_user_id, 1)
    [task_id] = await _task_ids(container, plan_id)
    day = date(2026, 9, 8)

    await container.submit_checkin(
        auth_user_id, plan_id, day, [CheckinResultInput(task_id=task_id, status="done")], None
    )
    await container.submit_checkin(
        auth_user_id,
        plan_id,
        day,
        [CheckinResultInput(task_id=task_id, status="skipped", reason="rest")],
        None,
    )

    history = await container.list_checkins(auth_user_id, plan_id)
    assert len(history.items) == 1
    assert history.items[0].results[0].status == "skipped"
    [fresh] = await container.plan_tasks.list(plan_id, None, None)
    assert fresh.status == "skipped"


async def test_task_from_another_plan_is_422(
    client: httpx.AsyncClient,
    container: ApiContainer,
    auth_headers: dict[str, str],
    auth_user_id: UUID,
) -> None:
    plan_id = await _plan_with_tasks(container, auth_user_id, 1)
    other_plan_id = await _plan_with_tasks(container, auth_user_id, 1)
    [foreign] = await _task_ids(container, other_plan_id)

    r = await client.post(
        f"/v1/plans/{plan_id}/checkins",
        json={
            "checkin_date": "2026-09-08",
            "results": [{"task_id": str(foreign), "status": "done"}],
        },
        headers=auth_headers,
    )

    assert r.status_code == 422


async def test_unknown_task_is_422(
    client: httpx.AsyncClient,
    container: ApiContainer,
    auth_headers: dict[str, str],
    auth_user_id: UUID,
) -> None:
    plan_id = await _plan_with_tasks(container, auth_user_id, 1)

    r = await client.post(
        f"/v1/plans/{plan_id}/checkins",
        json={
            "checkin_date": "2026-09-08",
            "results": [{"task_id": str(uuid4()), "status": "done"}],
        },
        headers=auth_headers,
    )

    assert r.status_code == 422


async def test_unknown_status_is_422(
    client: httpx.AsyncClient,
    container: ApiContainer,
    auth_headers: dict[str, str],
    auth_user_id: UUID,
) -> None:
    plan_id = await _plan_with_tasks(container, auth_user_id, 1)
    [task_id] = await _task_ids(container, plan_id)

    r = await client.post(
        f"/v1/plans/{plan_id}/checkins",
        json={
            "checkin_date": "2026-09-08",
            "results": [{"task_id": str(task_id), "status": "nope"}],
        },
        headers=auth_headers,
    )

    assert r.status_code == 422


async def test_daily_rates_one_entry_per_day(
    client: httpx.AsyncClient,
    container: ApiContainer,
    auth_headers: dict[str, str],
    auth_user_id: UUID,
) -> None:
    plan_id = await _plan_with_tasks(container, auth_user_id, 4)
    a, b, c, d = await _task_ids(container, plan_id)
    await container.submit_checkin(
        auth_user_id,
        plan_id,
        date(2026, 9, 8),
        [
            CheckinResultInput(task_id=a, status="done"),
            CheckinResultInput(task_id=b, status="missed"),
        ],
        None,
    )
    await container.submit_checkin(
        auth_user_id,
        plan_id,
        date(2026, 9, 9),
        [
            CheckinResultInput(task_id=c, status="done"),
            CheckinResultInput(task_id=d, status="done"),
        ],
        None,
    )

    r = await client.get(f"/v1/plans/{plan_id}/checkins", headers=auth_headers)

    assert r.status_code == 200
    assert r.json()["daily_rates"] == [
        {"date": "2026-09-08", "done": 1, "total": 2, "rate": 0.5},
        {"date": "2026-09-09", "done": 2, "total": 2, "rate": 1.0},
    ]


async def test_empty_history(
    client: httpx.AsyncClient,
    container: ApiContainer,
    auth_headers: dict[str, str],
    auth_user_id: UUID,
) -> None:
    plan_id = await _plan_with_tasks(container, auth_user_id, 1)

    r = await client.get(f"/v1/plans/{plan_id}/checkins", headers=auth_headers)

    assert r.json() == {"items": [], "daily_rates": []}


async def test_checkin_enqueues_incremental_export_when_exported(
    container: ApiContainer, auth_user_id: UUID
) -> None:
    plan_id = await _plan_with_tasks(container, auth_user_id, 1)
    [task_id] = await _task_ids(container, plan_id)
    await container.plan_exports.upsert(plan_id, "google_calendar", "synced", "cal-1", None, None)

    await container.submit_checkin(
        auth_user_id,
        plan_id,
        date(2026, 9, 8),
        [CheckinResultInput(task_id=task_id, status="done")],
        None,
    )

    assert _enqueued(container) == [
        ExportJobV1(plan_id=plan_id, target="google_calendar", mode="incremental")
    ]


async def test_checkin_does_not_enqueue_without_an_export(
    container: ApiContainer, auth_user_id: UUID
) -> None:
    plan_id = await _plan_with_tasks(container, auth_user_id, 1)
    [task_id] = await _task_ids(container, plan_id)

    await container.submit_checkin(
        auth_user_id,
        plan_id,
        date(2026, 9, 8),
        [CheckinResultInput(task_id=task_id, status="done")],
        None,
    )

    assert _enqueued(container) == []


async def test_checkin_on_another_users_plan_is_404(
    client: httpx.AsyncClient, container: ApiContainer, auth_headers: dict[str, str]
) -> None:
    other = await container.users.create("other@example.com", "other-sub")
    plan_id = await _plan_with_tasks(container, other.id, 1)
    [task_id] = await _task_ids(container, plan_id)

    r = await client.post(
        f"/v1/plans/{plan_id}/checkins",
        json={
            "checkin_date": "2026-09-08",
            "results": [{"task_id": str(task_id), "status": "done"}],
        },
        headers=auth_headers,
    )

    assert r.status_code == 404


async def test_history_of_another_users_plan_is_404(
    client: httpx.AsyncClient, container: ApiContainer, auth_headers: dict[str, str]
) -> None:
    other = await container.users.create("other@example.com", "other-sub")
    plan_id = await _plan_with_tasks(container, other.id, 1)

    r = await client.get(f"/v1/plans/{plan_id}/checkins", headers=auth_headers)

    assert r.status_code == 404
