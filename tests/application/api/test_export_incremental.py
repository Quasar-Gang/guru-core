"""Incremental calendar sync, export status and unexport (plan Task 35, PRD 3.5 / 3.7)."""

from datetime import timedelta
from uuid import UUID

import httpx
import pytest

from packages.queue import ExportJobV1
from services.api.container import ApiContainer
from services.api.domain.errors import DomainError, NotFound
from tests.application.api.test_export_calendar_full import (
    GOOGLE_CALENDAR,
    START,
    fake_calendar,
    full_export,
    new_task,
    seed_plan,
)


async def _push_incremental(container: ApiContainer, plan_id: UUID) -> None:
    await container.push_export(
        ExportJobV1(plan_id=plan_id, target=GOOGLE_CALENDAR, mode="incremental")
    )


async def _exported_task_id(container: ApiContainer, plan_id: UUID) -> UUID:
    tasks = await container.plan_tasks.list(plan_id, None, None)
    return next(t.id for t in tasks if t.external_ref is not None)


def _forget_writes(container: ApiContainer) -> None:
    calendar = fake_calendar(container)
    calendar.created_events.clear()
    calendar.updated_events.clear()
    calendar.deleted_events.clear()


# --- incremental push -------------------------------------------------------


async def test_incremental_only_touches_dirty_tasks(
    container: ApiContainer, auth_user_id: UUID
) -> None:
    plan_id = await full_export(container, auth_user_id)
    _forget_writes(container)
    task_id = await _exported_task_id(container, plan_id)
    await container.update_plan_task(
        auth_user_id,
        plan_id,
        task_id,
        status="done",
        start_at=None,
        end_at=None,
        missed_reason=None,
    )

    await _push_incremental(container, plan_id)

    calendar = fake_calendar(container)
    assert len(calendar.updated_events) == 1
    assert calendar.created_events == []
    assert calendar.deleted_events == []


async def test_done_task_title_gets_check_prefix_on_sync(
    container: ApiContainer, auth_user_id: UUID
) -> None:
    plan_id = await full_export(container, auth_user_id)
    _forget_writes(container)
    task_id = await _exported_task_id(container, plan_id)
    await container.update_plan_task(
        auth_user_id,
        plan_id,
        task_id,
        status="done",
        start_at=None,
        end_at=None,
        missed_reason=None,
    )

    await _push_incremental(container, plan_id)

    _cal, _event_id, event = fake_calendar(container).updated_events[0]
    assert event.summary.startswith("✓")


async def test_incremental_creates_an_event_for_a_new_task(
    container: ApiContainer, auth_user_id: UUID
) -> None:
    plan_id = await full_export(container, auth_user_id)
    _forget_writes(container)
    cutoff = START + timedelta(days=10)
    await container.plan_tasks.replace_from(
        plan_id, cutoff, [new_task(cutoff + timedelta(days=1), title="new run")]
    )

    await _push_incremental(container, plan_id)

    calendar = fake_calendar(container)
    assert [event.summary for _cal, event in calendar.created_events] == ["new run"]
    tasks = await container.plan_tasks.list(plan_id, None, None)
    assert next(t for t in tasks if t.title == "new run").external_ref is not None


async def test_incremental_deletes_the_event_of_a_task_that_left_the_export(
    container: ApiContainer, auth_user_id: UUID
) -> None:
    plan_id = await full_export(container, auth_user_id)
    _forget_writes(container)
    task_id = await _exported_task_id(container, plan_id)
    task = await container.plan_tasks.update_fields(task_id, task_type="rest", synced_at=None)
    external_ref = task.external_ref

    await _push_incremental(container, plan_id)

    calendar = fake_calendar(container)
    assert [event_id for _cal, event_id in calendar.deleted_events] == [external_ref]
    updated = await container.plan_tasks.get(plan_id, task_id)
    assert updated is not None and updated.external_ref is None


async def test_synced_at_updated_after_push(container: ApiContainer, auth_user_id: UUID) -> None:
    plan_id = await full_export(container, auth_user_id)
    task_id = await _exported_task_id(container, plan_id)
    await container.plan_tasks.update_fields(task_id, synced_at=None)

    await _push_incremental(container, plan_id)

    tasks = await container.plan_tasks.list(plan_id, None, None)
    assert all(t.synced_at is not None for t in tasks)


async def test_incremental_without_a_calendar_fails_the_export(
    container: ApiContainer, auth_user_id: UUID
) -> None:
    plan_id = await seed_plan(container, auth_user_id)
    await container.complete_integration(auth_user_id, "google", "code")
    await container.plan_exports.upsert(plan_id, GOOGLE_CALENDAR, "queued", None, None, None)

    await _push_incremental(container, plan_id)

    record = await container.plan_exports.get(plan_id, GOOGLE_CALENDAR)
    assert record is not None and record.status == "failed"


# --- export status ----------------------------------------------------------


async def test_pending_changes_reported_in_status(
    container: ApiContainer, auth_user_id: UUID
) -> None:
    plan_id = await full_export(container, auth_user_id)
    task_id = await _exported_task_id(container, plan_id)
    await container.update_plan_task(
        auth_user_id,
        plan_id,
        task_id,
        status="done",
        start_at=None,
        end_at=None,
        missed_reason=None,
    )

    [view] = await container.get_export_status(auth_user_id, plan_id)

    assert view.target == GOOGLE_CALENDAR
    assert view.status == "synced"
    assert view.external_calendar_id
    assert view.pending_changes == 1


async def test_status_is_empty_before_any_export(
    container: ApiContainer, auth_user_id: UUID
) -> None:
    plan_id = await seed_plan(container, auth_user_id)

    assert await container.get_export_status(auth_user_id, plan_id) == []


# --- unexport ---------------------------------------------------------------


async def test_unexport_deletes_calendar_and_clears_refs(
    container: ApiContainer, auth_user_id: UUID
) -> None:
    plan_id = await full_export(container, auth_user_id)
    record = await container.plan_exports.get(plan_id, GOOGLE_CALENDAR)
    assert record is not None

    await container.unexport_plan(auth_user_id, plan_id, GOOGLE_CALENDAR)

    assert fake_calendar(container).deleted_calendars == [record.external_calendar_id]
    tasks = await container.plan_tasks.list(plan_id, None, None)
    assert all(t.external_ref is None and t.synced_at is None for t in tasks)
    assert await container.plan_exports.get(plan_id, GOOGLE_CALENDAR) is None


async def test_unexport_tolerates_an_already_deleted_calendar(
    container: ApiContainer, auth_user_id: UUID
) -> None:
    plan_id = await full_export(container, auth_user_id)
    fake_calendar(container).delete_calendar_raises = DomainError(
        "google calendar call failed: 404"
    )

    await container.unexport_plan(auth_user_id, plan_id, GOOGLE_CALENDAR)

    assert await container.plan_exports.get(plan_id, GOOGLE_CALENDAR) is None


async def test_unexport_without_an_export_row_is_not_found(
    container: ApiContainer, auth_user_id: UUID
) -> None:
    plan_id = await seed_plan(container, auth_user_id)

    with pytest.raises(NotFound):
        await container.unexport_plan(auth_user_id, plan_id, GOOGLE_CALENDAR)


async def test_archive_does_not_touch_calendar(container: ApiContainer, auth_user_id: UUID) -> None:
    plan_id = await full_export(container, auth_user_id)
    _forget_writes(container)

    await container.archive_plan(auth_user_id, plan_id)

    calendar = fake_calendar(container)
    assert calendar.deleted_calendars == [] and calendar.deleted_events == []


async def test_delete_plan_unexports_first(container: ApiContainer, auth_user_id: UUID) -> None:
    plan_id = await full_export(container, auth_user_id)
    record = await container.plan_exports.get(plan_id, GOOGLE_CALENDAR)
    assert record is not None

    await container.delete_plan(auth_user_id, plan_id)

    assert fake_calendar(container).deleted_calendars == [record.external_calendar_id]
    assert await container.plan_exports.get(plan_id, GOOGLE_CALENDAR) is None


# --- HTTP -------------------------------------------------------------------


async def test_export_status_endpoint(
    client: httpx.AsyncClient,
    container: ApiContainer,
    auth_headers: dict[str, str],
    auth_user_id: UUID,
) -> None:
    plan_id = await full_export(container, auth_user_id)

    response = await client.get(f"/v1/plans/{plan_id}/export", headers=auth_headers)

    assert response.status_code == 200
    [view] = response.json()
    assert view["target"] == GOOGLE_CALENDAR
    assert view["status"] == "synced"
    assert view["pending_changes"] == 0


async def test_unexport_endpoint(
    client: httpx.AsyncClient,
    container: ApiContainer,
    auth_headers: dict[str, str],
    auth_user_id: UUID,
) -> None:
    plan_id = await full_export(container, auth_user_id)

    response = await client.delete(
        f"/v1/plans/{plan_id}/export/{GOOGLE_CALENDAR}", headers=auth_headers
    )

    assert response.status_code == 204
    assert await container.plan_exports.get(plan_id, GOOGLE_CALENDAR) is None
