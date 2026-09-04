"""Synchronous Markdown export (plan Task 33, PRD 4.3.5 / 5)."""

from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest

from packages.queue import InMemoryQueue
from packages.repo.entities import NewPlan, NewPlanTask
from services.api.container import ApiContainer
from services.api.domain.errors import Conflict, InvalidInput, NotFound
from services.api.domain.markdown_export import MarkdownOptions

START = datetime(2026, 9, 8, 11, 30, tzinfo=UTC)

STRUCTURE: dict[str, Any] = {
    "success_criteria": ["run 5k under 30 minutes"],
    "assumptions": ["three evenings a week are free"],
    "phases": [
        {
            "index": 0,
            "name": "base",
            "week_start": 0,
            "week_end": 1,
            "focus": "build mileage",
            "milestone": {"title": "5k without stopping", "metric": "distance"},
        }
    ],
}


def _new_task(start_at: datetime, **overrides: Any) -> NewPlanTask:
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


async def _plan(container: ApiContainer, user_id: UUID, status: str = "active") -> UUID:
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
                title="run 5k in 12 weeks",
                difficulty="hard",
                status=status,
                goal_statement="run 5k under 30 minutes",
                duration_weeks=2,
                start_date=date(2026, 9, 7),
                deadline=date(2026, 9, 20),
                structure=STRUCTURE,
            )
        ]
    )
    await container.plan_tasks.replace_all(
        plan.id,
        [
            _new_task(START, status="done"),
            _new_task(START + timedelta(days=2), title="intervals"),
            _new_task(START + timedelta(days=4), task_type="rest", title="rest day"),
        ],
    )
    return plan.id


# --- use case ---------------------------------------------------------------


async def test_export_stores_file_and_returns_url(
    container: ApiContainer, auth_user_id: UUID
) -> None:
    plan_id = await _plan(container, auth_user_id)

    result = await container.export_markdown(auth_user_id, plan_id, MarkdownOptions())

    assert result.content.startswith("# run 5k in 12 weeks")
    assert result.storage_key.startswith(f"exports/{auth_user_id}/{plan_id}/")
    assert result.storage_key.endswith(".md")
    assert await container.storage.exists(result.storage_key)
    assert result.download_url


async def test_stored_bytes_match_the_returned_content(
    container: ApiContainer, auth_user_id: UUID
) -> None:
    plan_id = await _plan(container, auth_user_id)

    result = await container.export_markdown(auth_user_id, plan_id, MarkdownOptions())

    assert await container.storage.get(result.storage_key) == result.content.encode("utf-8")


async def test_export_renders_in_the_profile_timezone(
    container: ApiContainer, auth_user_id: UUID
) -> None:
    await container.profiles.upsert(auth_user_id, {}, "Asia/Taipei")
    plan_id = await _plan(container, auth_user_id)

    result = await container.export_markdown(auth_user_id, plan_id, MarkdownOptions())

    assert "19:30–20:00" in result.content


async def test_export_honours_include_completed(
    container: ApiContainer, auth_user_id: UUID
) -> None:
    plan_id = await _plan(container, auth_user_id)

    result = await container.export_markdown(
        auth_user_id, plan_id, MarkdownOptions(include_completed=False)
    )

    assert "easy run" not in result.content
    assert "intervals" in result.content


async def test_export_of_another_users_plan_is_not_found(
    container: ApiContainer, auth_user_id: UUID
) -> None:
    plan_id = await _plan(container, auth_user_id)
    stranger = await container.users.create("stranger@example.com", "stranger-sub")

    with pytest.raises(NotFound):
        await container.export_markdown(stranger.id, plan_id, MarkdownOptions())


# --- through RequestExport --------------------------------------------------


async def test_request_markdown_returns_inline_content_without_enqueue(
    container: ApiContainer, auth_user_id: UUID
) -> None:
    plan_id = await _plan(container, auth_user_id)
    queue = container.queue
    assert isinstance(queue, InMemoryQueue)

    result = await container.request_export(auth_user_id, plan_id, "markdown", {})

    assert result.target == "markdown"
    assert result.job_id is None and result.mode is None
    assert result.markdown is not None
    assert result.markdown.content.startswith("# ")
    assert queue.enqueued == []


async def test_request_markdown_on_a_draft_plan_conflicts(
    container: ApiContainer, auth_user_id: UUID
) -> None:
    plan_id = await _plan(container, auth_user_id, status="draft")

    with pytest.raises(Conflict):
        await container.request_export(auth_user_id, plan_id, "markdown", {})


async def test_request_export_rejects_an_unknown_target(
    container: ApiContainer, auth_user_id: UUID
) -> None:
    plan_id = await _plan(container, auth_user_id)

    with pytest.raises(InvalidInput):
        await container.request_export(auth_user_id, plan_id, "carrier_pigeon", {})


# --- HTTP -------------------------------------------------------------------


async def test_export_endpoint_returns_markdown_inline(
    client: httpx.AsyncClient,
    container: ApiContainer,
    auth_headers: dict[str, str],
    auth_user_id: UUID,
) -> None:
    plan_id = await _plan(container, auth_user_id)

    response = await client.post(
        f"/v1/plans/{plan_id}/export", json={"target": "markdown"}, headers=auth_headers
    )

    assert response.status_code == 200
    body = response.json()
    assert body["target"] == "markdown"
    assert body["markdown"]["content"].startswith("# ")
    assert body["markdown"]["download_url"]


async def test_export_endpoint_rejects_an_unknown_plan(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    response = await client.post(
        f"/v1/plans/{uuid4()}/export", json={"target": "markdown"}, headers=auth_headers
    )

    assert response.status_code == 404
