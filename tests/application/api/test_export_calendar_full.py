"""Google Calendar export, full mode (plan Task 34, PRD 3.5 / 3.6 / 4.3.4).

The helpers here are shared with `test_export_incremental.py`.
"""

from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID

import httpx
import pytest

from packages.queue import ExportJobV1, InMemoryQueue
from packages.repo.entities import NewPlan, NewPlanTask
from services.api.adapters.google.calendar import FakeCalendar
from services.api.adapters.google.oauth import FakeOAuth
from services.api.application.ports import InvalidGrant
from services.api.container import ApiContainer, build_test_container
from services.api.domain.errors import Conflict, ReauthRequired

START = datetime(2026, 9, 8, 11, 30, tzinfo=UTC)
GOOGLE_CALENDAR = "google_calendar"
PLAN_TITLE = "run 5k in 12 weeks"

#: The seeded plan has three tasks, one of which is a `rest` task and is not exported.
EXPORTABLE_TASKS = 2


def new_task(start_at: datetime, **overrides: Any) -> NewPlanTask:
    fields: dict[str, Any] = {
        "template_key": "easy_run",
        "week_index": 0,
        "task_type": "session",
        "title": "easy run",
        "description": "conversational pace",
        "start_at": start_at,
        "end_at": start_at + timedelta(minutes=30),
    }
    fields.update(overrides)
    return NewPlanTask(**fields)


async def seed_plan(
    container: ApiContainer,
    user_id: UUID,
    status: str = "active",
    tasks: list[NewPlanTask] | None = None,
) -> UUID:
    """An active plan with two exportable tasks and one rest task."""
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
                title=PLAN_TITLE,
                difficulty="hard",
                status=status,
                goal_statement="run 5k under 30 minutes",
                duration_weeks=2,
                start_date=date(2026, 9, 7),
                deadline=date(2026, 9, 20),
            )
        ]
    )
    await container.plan_tasks.replace_all(
        plan.id,
        tasks
        if tasks is not None
        else [
            new_task(START),
            new_task(START + timedelta(days=2), title="intervals"),
            new_task(START + timedelta(days=4), task_type="rest", title="rest day"),
        ],
    )
    return plan.id


async def connect_google(container: ApiContainer, user_id: UUID) -> None:
    await container.complete_integration(user_id, "google", "code")


async def push_full(container: ApiContainer, plan_id: UUID) -> None:
    await container.push_export(ExportJobV1(plan_id=plan_id, target=GOOGLE_CALENDAR, mode="full"))


async def full_export(container: ApiContainer, user_id: UUID) -> UUID:
    """Seed, connect, request and push one full export; returns the plan id."""
    plan_id = await seed_plan(container, user_id)
    await connect_google(container, user_id)
    await container.request_export(user_id, plan_id, GOOGLE_CALENDAR, {})
    await push_full(container, plan_id)
    return plan_id


def fake_calendar(container: ApiContainer) -> FakeCalendar:
    calendar = container.calendar
    assert isinstance(calendar, FakeCalendar)
    return calendar


def enqueued(container: ApiContainer) -> list[Any]:
    queue = container.queue
    assert isinstance(queue, InMemoryQueue)
    return queue.enqueued


# --- RequestExport ----------------------------------------------------------


async def test_request_export_queues_a_full_job(
    container: ApiContainer, auth_user_id: UUID
) -> None:
    plan_id = await seed_plan(container, auth_user_id)
    await connect_google(container, auth_user_id)

    result = await container.request_export(auth_user_id, plan_id, GOOGLE_CALENDAR, {})

    assert result.mode == "full"
    assert result.job_id is not None
    assert result.markdown is None
    assert enqueued(container) == [
        ExportJobV1(plan_id=plan_id, target=GOOGLE_CALENDAR, mode="full")
    ]
    record = await container.plan_exports.get(plan_id, GOOGLE_CALENDAR)
    assert record is not None and record.status == "queued"


async def test_request_export_queues_an_incremental_job_once_a_calendar_exists(
    container: ApiContainer, auth_user_id: UUID
) -> None:
    plan_id = await full_export(container, auth_user_id)

    result = await container.request_export(auth_user_id, plan_id, GOOGLE_CALENDAR, {})

    assert result.mode == "incremental"


async def test_request_export_on_a_draft_plan_conflicts(
    container: ApiContainer, auth_user_id: UUID
) -> None:
    plan_id = await seed_plan(container, auth_user_id, status="draft")
    await connect_google(container, auth_user_id)

    with pytest.raises(Conflict):
        await container.request_export(auth_user_id, plan_id, GOOGLE_CALENDAR, {})


async def test_request_export_without_a_connection_raises_reauth(
    container: ApiContainer, auth_user_id: UUID
) -> None:
    plan_id = await seed_plan(container, auth_user_id)

    with pytest.raises(ReauthRequired):
        await container.request_export(auth_user_id, plan_id, GOOGLE_CALENDAR, {})

    assert enqueued(container) == []


# --- PushExport, full mode --------------------------------------------------


async def test_full_export_creates_calendar_and_events(
    container: ApiContainer, auth_user_id: UUID
) -> None:
    await full_export(container, auth_user_id)

    calendar = fake_calendar(container)
    assert calendar.created_calendars == [f"guru · {PLAN_TITLE}"]
    assert len(calendar.created_events) == EXPORTABLE_TASKS
    assert {event.summary for _cal, event in calendar.created_events} == {"easy run", "intervals"}


async def test_full_export_puts_every_event_in_the_new_calendar(
    container: ApiContainer, auth_user_id: UUID
) -> None:
    plan_id = await full_export(container, auth_user_id)

    record = await container.plan_exports.get(plan_id, GOOGLE_CALENDAR)
    assert record is not None
    assert {cal for cal, _event in fake_calendar(container).created_events} == {
        record.external_calendar_id
    }


async def test_full_export_backfills_external_ref_and_synced_at(
    container: ApiContainer, auth_user_id: UUID
) -> None:
    plan_id = await full_export(container, auth_user_id)

    tasks = await container.plan_tasks.list(plan_id, None, None)
    assert all(t.external_ref for t in tasks if t.task_type != "rest")
    assert all(t.synced_at is not None for t in tasks)
    assert all(t.external_ref is None for t in tasks if t.task_type == "rest")


async def test_full_export_leaves_no_pending_changes(
    container: ApiContainer, auth_user_id: UUID
) -> None:
    plan_id = await full_export(container, auth_user_id)

    assert await container.plan_tasks.list_dirty(plan_id) == []


async def test_export_record_marked_synced(container: ApiContainer, auth_user_id: UUID) -> None:
    plan_id = await full_export(container, auth_user_id)

    record = await container.plan_exports.get(plan_id, GOOGLE_CALENDAR)
    assert record is not None
    assert record.status == "synced"
    assert record.error is None
    assert record.external_calendar_id
    assert record.last_synced_at == container.clock.now()


async def test_reauth_required_marks_export_failed() -> None:
    container = build_test_container(google_oauth=FakeOAuth(refresh_raises=InvalidGrant()))
    user = await container.users.create("reauth@example.com", "reauth-sub")
    plan_id = await seed_plan(container, user.id)
    await container.plan_exports.upsert(plan_id, GOOGLE_CALENDAR, "queued", None, None, None)

    await push_full(container, plan_id)

    record = await container.plan_exports.get(plan_id, GOOGLE_CALENDAR)
    assert record is not None
    assert record.status == "failed"
    assert record.error == "reauth_required"


async def test_push_export_records_failure_instead_of_raising(
    container: ApiContainer, auth_user_id: UUID
) -> None:
    plan_id = await seed_plan(container, auth_user_id)
    await connect_google(container, auth_user_id)
    await container.plan_exports.upsert(plan_id, GOOGLE_CALENDAR, "queued", None, None, None)
    await container.plans.delete(plan_id)

    await push_full(container, plan_id)

    record = await container.plan_exports.get(plan_id, GOOGLE_CALENDAR)
    assert record is not None
    assert record.status == "failed"
    assert record.error


# --- HTTP -------------------------------------------------------------------


async def test_export_endpoint_queues_a_calendar_push(
    client: httpx.AsyncClient,
    container: ApiContainer,
    auth_headers: dict[str, str],
    auth_user_id: UUID,
) -> None:
    plan_id = await seed_plan(container, auth_user_id)
    await connect_google(container, auth_user_id)

    response = await client.post(
        f"/v1/plans/{plan_id}/export", json={"target": GOOGLE_CALENDAR}, headers=auth_headers
    )

    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "full"
    assert body["job_id"]


async def test_export_endpoint_reports_a_missing_connection(
    client: httpx.AsyncClient,
    container: ApiContainer,
    auth_headers: dict[str, str],
    auth_user_id: UUID,
) -> None:
    plan_id = await seed_plan(container, auth_user_id)

    response = await client.post(
        f"/v1/plans/{plan_id}/export", json={"target": GOOGLE_CALENDAR}, headers=auth_headers
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "reauth_required"
