"""Plan task listing and updates (plan Task 31, PRD 3.7 / 4.3.6 / 5)."""

from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4

import httpx
import pytest

from packages.queue import ExportJobV1, InMemoryQueue, JobPayload
from packages.repo.entities import NewPlan, NewPlanTask
from services.api.container import ApiContainer

START = datetime(2026, 9, 7, 16, 0, tzinfo=UTC)


def _enqueued(container: ApiContainer) -> list[JobPayload]:
    """The fake queue's log; the test container always wires an `InMemoryQueue`."""
    queue = container.queue
    assert isinstance(queue, InMemoryQueue)
    return queue.enqueued


def _new_plan(user_id: UUID, session_id: UUID) -> NewPlan:
    return NewPlan(
        user_id=user_id,
        session_id=session_id,
        title="run 5k",
        difficulty="standard",
        goal_statement="run 5k under 30 minutes",
        duration_weeks=8,
        start_date=date(2026, 9, 7),
        deadline=date(2026, 11, 2),
    )


def _new_task(start_at: datetime, **overrides: object) -> NewPlanTask:
    fields: dict[str, object] = {
        "template_key": "easy_run",
        "week_index": 0,
        "task_type": "practice",
        "title": "easy run",
        "start_at": start_at,
        "end_at": start_at + timedelta(hours=1),
    }
    fields.update(overrides)
    return NewPlanTask(**fields)  # type: ignore[arg-type]


async def _plan_with_tasks(
    container: ApiContainer, user_id: UUID, tasks: list[NewPlanTask]
) -> UUID:
    session = await container.plan_sessions.create(
        user_id=user_id,
        goal="run 5k under 30 minutes",
        intake={},
        import_ids=[],
        use_calendar=False,
        trait_role_model_id=None,
        persona_role_model_id=None,
    )
    [plan] = await container.plans.create_many([_new_plan(user_id, session.id)])
    await container.plan_tasks.replace_all(plan.id, tasks)
    return plan.id


async def _single_task_plan(container: ApiContainer, user_id: UUID) -> tuple[UUID, UUID]:
    plan_id = await _plan_with_tasks(container, user_id, [_new_task(START)])
    [task] = await container.plan_tasks.list(plan_id, None, None)
    return plan_id, task.id


# --- listing ----------------------------------------------------------------


async def test_list_returns_every_task_without_a_range(
    client: httpx.AsyncClient,
    container: ApiContainer,
    auth_headers: dict[str, str],
    auth_user_id: UUID,
) -> None:
    plan_id = await _plan_with_tasks(
        container, auth_user_id, [_new_task(START), _new_task(START + timedelta(days=3))]
    )

    r = await client.get(f"/v1/plans/{plan_id}/tasks", headers=auth_headers)

    assert r.status_code == 200
    assert r.json()["total"] == 2


async def test_list_filters_by_local_date_range(
    client: httpx.AsyncClient,
    container: ApiContainer,
    auth_headers: dict[str, str],
    auth_user_id: UUID,
) -> None:
    plan_id = await _plan_with_tasks(
        container, auth_user_id, [_new_task(START), _new_task(START + timedelta(days=3))]
    )

    r = await client.get(
        f"/v1/plans/{plan_id}/tasks",
        params={"from": "2026-09-07", "to": "2026-09-07"},
        headers=auth_headers,
    )

    assert r.status_code == 200
    assert [item["start_at"] for item in r.json()["items"]] == ["2026-09-07T16:00:00Z"]


async def test_range_uses_the_plan_owner_timezone(
    container: ApiContainer, auth_user_id: UUID
) -> None:
    """In Asia/Taipei, 2026-09-08 starts at 2026-09-07T16:00Z."""
    await container.profiles.upsert(auth_user_id, {}, "Asia/Taipei")
    plan_id = await _plan_with_tasks(
        container,
        auth_user_id,
        [_new_task(START), _new_task(START + timedelta(days=1))],
    )

    result = await container.list_plan_tasks(
        auth_user_id, plan_id, date(2026, 9, 8), date(2026, 9, 8)
    )

    assert result.total == 1
    assert result.items[0].start_at == START


async def test_range_end_is_inclusive_of_the_whole_local_day(
    container: ApiContainer, auth_user_id: UUID
) -> None:
    await container.profiles.upsert(auth_user_id, {}, "Asia/Taipei")
    late = datetime(2026, 9, 8, 15, 0, tzinfo=UTC)  # 2026-09-08 23:00 in Taipei
    plan_id = await _plan_with_tasks(container, auth_user_id, [_new_task(late)])

    result = await container.list_plan_tasks(
        auth_user_id, plan_id, date(2026, 9, 8), date(2026, 9, 8)
    )

    assert result.total == 1


async def test_list_reports_synced_only_for_clean_exported_tasks(
    container: ApiContainer, auth_user_id: UUID
) -> None:
    plan_id = await _plan_with_tasks(
        container,
        auth_user_id,
        [
            _new_task(START, external_ref="evt-1", synced_at=START),
            _new_task(START + timedelta(days=1), external_ref="evt-2", synced_at=None),
            _new_task(START + timedelta(days=2)),
        ],
    )

    result = await container.list_plan_tasks(auth_user_id, plan_id, None, None)

    assert [item.synced for item in result.items] == [True, False, False]


async def test_list_of_another_users_plan_is_404(
    client: httpx.AsyncClient, container: ApiContainer, auth_headers: dict[str, str]
) -> None:
    other = await container.users.create("other@example.com", "other-sub")
    plan_id = await _plan_with_tasks(container, other.id, [_new_task(START)])

    r = await client.get(f"/v1/plans/{plan_id}/tasks", headers=auth_headers)

    assert r.status_code == 404


async def test_list_requires_authentication(
    client: httpx.AsyncClient, container: ApiContainer, auth_user_id: UUID
) -> None:
    plan_id = await _plan_with_tasks(container, auth_user_id, [_new_task(START)])

    r = await client.get(f"/v1/plans/{plan_id}/tasks")

    assert r.status_code == 401


# --- updates ----------------------------------------------------------------


async def test_marking_done_records_completed_at(
    client: httpx.AsyncClient,
    container: ApiContainer,
    auth_headers: dict[str, str],
    auth_user_id: UUID,
) -> None:
    plan_id, task_id = await _single_task_plan(container, auth_user_id)

    r = await client.patch(
        f"/v1/plans/{plan_id}/tasks/{task_id}", json={"status": "done"}, headers=auth_headers
    )

    assert r.status_code == 200
    assert r.json()["status"] == "done"
    assert r.json()["completed_at"] is not None


async def test_back_to_pending_clears_completed_at(
    container: ApiContainer, auth_user_id: UUID
) -> None:
    plan_id, task_id = await _single_task_plan(container, auth_user_id)
    await container.update_plan_task(
        auth_user_id,
        plan_id,
        task_id,
        status="done",
        start_at=None,
        end_at=None,
        missed_reason=None,
    )

    view = await container.update_plan_task(
        auth_user_id,
        plan_id,
        task_id,
        status="pending",
        start_at=None,
        end_at=None,
        missed_reason=None,
    )

    assert view.completed_at is None


async def test_missed_keeps_the_reason(
    client: httpx.AsyncClient,
    container: ApiContainer,
    auth_headers: dict[str, str],
    auth_user_id: UUID,
) -> None:
    plan_id, task_id = await _single_task_plan(container, auth_user_id)

    r = await client.patch(
        f"/v1/plans/{plan_id}/tasks/{task_id}",
        json={"status": "missed", "missed_reason": "worked late"},
        headers=auth_headers,
    )

    assert r.json()["missed_reason"] == "worked late"


async def test_unknown_status_is_422(
    client: httpx.AsyncClient,
    container: ApiContainer,
    auth_headers: dict[str, str],
    auth_user_id: UUID,
) -> None:
    plan_id, task_id = await _single_task_plan(container, auth_user_id)

    r = await client.patch(
        f"/v1/plans/{plan_id}/tasks/{task_id}", json={"status": "finished"}, headers=auth_headers
    )

    assert r.status_code == 422


async def test_end_before_start_is_422(
    client: httpx.AsyncClient,
    container: ApiContainer,
    auth_headers: dict[str, str],
    auth_user_id: UUID,
) -> None:
    plan_id, task_id = await _single_task_plan(container, auth_user_id)

    r = await client.patch(
        f"/v1/plans/{plan_id}/tasks/{task_id}",
        json={"start_at": "2026-09-07T16:00:00Z", "end_at": "2026-09-07T16:00:00Z"},
        headers=auth_headers,
    )

    assert r.status_code == 422


async def test_rescheduling_marks_the_task_dirty(
    container: ApiContainer, auth_user_id: UUID
) -> None:
    plan_id = await _plan_with_tasks(
        container, auth_user_id, [_new_task(START, external_ref="evt-1", synced_at=START)]
    )
    [task] = await container.plan_tasks.list(plan_id, None, None)
    moved = START + timedelta(days=1)

    await container.update_plan_task(
        auth_user_id,
        plan_id,
        task.id,
        status=None,
        start_at=moved,
        end_at=moved + timedelta(hours=1),
        missed_reason=None,
    )

    [fresh] = await container.plan_tasks.list(plan_id, None, None)
    assert fresh.start_at == moved
    assert fresh.synced_at is None


async def test_status_change_marks_the_task_dirty(
    container: ApiContainer, auth_user_id: UUID
) -> None:
    plan_id = await _plan_with_tasks(
        container, auth_user_id, [_new_task(START, external_ref="evt-1", synced_at=START)]
    )
    [task] = await container.plan_tasks.list(plan_id, None, None)

    await container.update_plan_task(
        auth_user_id,
        plan_id,
        task.id,
        status="done",
        start_at=None,
        end_at=None,
        missed_reason=None,
    )

    [fresh] = await container.plan_tasks.list(plan_id, None, None)
    assert fresh.synced_at is None


async def test_update_enqueues_incremental_export_when_exported(
    container: ApiContainer, auth_user_id: UUID
) -> None:
    plan_id, task_id = await _single_task_plan(container, auth_user_id)
    await container.plan_exports.upsert(plan_id, "google_calendar", "synced", "cal-1", None, None)

    await container.update_plan_task(
        auth_user_id,
        plan_id,
        task_id,
        status="done",
        start_at=None,
        end_at=None,
        missed_reason=None,
    )

    assert _enqueued(container) == [
        ExportJobV1(plan_id=plan_id, target="google_calendar", mode="incremental")
    ]


async def test_update_does_not_enqueue_without_an_export(
    container: ApiContainer, auth_user_id: UUID
) -> None:
    plan_id, task_id = await _single_task_plan(container, auth_user_id)

    await container.update_plan_task(
        auth_user_id,
        plan_id,
        task_id,
        status="done",
        start_at=None,
        end_at=None,
        missed_reason=None,
    )

    assert _enqueued(container) == []


async def test_update_of_another_users_task_is_404(
    client: httpx.AsyncClient, container: ApiContainer, auth_headers: dict[str, str]
) -> None:
    other = await container.users.create("other@example.com", "other-sub")
    plan_id, task_id = await _single_task_plan(container, other.id)

    r = await client.patch(
        f"/v1/plans/{plan_id}/tasks/{task_id}", json={"status": "done"}, headers=auth_headers
    )

    assert r.status_code == 404


async def test_unknown_task_is_404(
    client: httpx.AsyncClient,
    container: ApiContainer,
    auth_headers: dict[str, str],
    auth_user_id: UUID,
) -> None:
    plan_id, _ = await _single_task_plan(container, auth_user_id)

    r = await client.patch(
        f"/v1/plans/{plan_id}/tasks/{uuid4()}", json={"status": "done"}, headers=auth_headers
    )

    assert r.status_code == 404


async def test_invalid_timezone_falls_back_to_utc(
    container: ApiContainer, auth_user_id: UUID
) -> None:
    await container.profiles.upsert(auth_user_id, {}, "Not/AZone")
    plan_id = await _plan_with_tasks(container, auth_user_id, [_new_task(START)])

    result = await container.list_plan_tasks(
        auth_user_id, plan_id, date(2026, 9, 7), date(2026, 9, 7)
    )

    assert result.total == 1


@pytest.mark.parametrize("field", ["start_at", "end_at"])
async def test_partial_time_update_is_validated_against_the_stored_value(
    container: ApiContainer, auth_user_id: UUID, field: str
) -> None:
    plan_id, task_id = await _single_task_plan(container, auth_user_id)
    kwargs: dict[str, object] = {
        "status": None,
        "start_at": None,
        "end_at": None,
        "missed_reason": None,
    }
    kwargs[field] = START - timedelta(hours=2) if field == "end_at" else START + timedelta(hours=5)

    from services.api.domain.errors import InvalidInput

    with pytest.raises(InvalidInput):
        await container.update_plan_task(auth_user_id, plan_id, task_id, **kwargs)  # type: ignore[arg-type]
