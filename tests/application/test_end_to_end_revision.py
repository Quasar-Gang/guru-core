"""M4.5 acceptance: a missed week becomes a revision the user accepts (PRD 3.8).

Same arrangement as `test_end_to_end_generate.py`: the Plan Engine test container is built
on the API container's in-memory repos, so both services see one database, and the
`InMemoryQueue` stands in for ARQ — draining it runs both services' worker handlers in
process.
"""

from pathlib import Path
from typing import Any
from uuid import UUID

import httpx

from packages.llm.fake import FakeLLM
from packages.llm.ports import OutputT, Purpose
from packages.queue import ExportJobV1, InMemoryQueue
from services.api.adapters.google.calendar import FakeCalendar
from services.api.container import ApiContainer
from services.api.container import create_worker_handlers as create_api_handlers
from services.plan_engine.container import PlanEngineContainer
from services.plan_engine.container import build_test_container as build_engine_container
from services.plan_engine.container import create_worker_handlers as create_engine_handlers
from services.plan_engine.domain.template import PlanTemplate

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "llm"
GOOGLE_CALENDAR = "google_calendar"
EXTRA_WEEKS = 2
_READY: dict[str, Any] = {"ready": True, "missing": [], "questions": []}


class ScriptedRevisionLLM:
    """Fixtures for everything except `revise_plan`, whose answer the test sets itself.

    The revision has to agree with the plan that was actually generated (the postpone rules
    compare it against that plan's own template), so the payload can only be built once the
    plan exists.
    """

    def __init__(self) -> None:
        self._fake = FakeLLM(FIXTURES_DIR)
        self.revision: dict[str, Any] | None = None

    async def complete(
        self,
        prompt_name: str,
        context: dict[str, Any],
        output_schema: type[OutputT],
        purpose: Purpose,
    ) -> OutputT:
        if prompt_name == "evaluate_readiness":
            return output_schema.model_validate(_READY)
        if prompt_name == "revise_plan":
            assert self.revision is not None, "the test must script the revision first"
            return output_schema.model_validate(self.revision)
        return await self._fake.complete(prompt_name, context, output_schema, purpose)


def _engine_on(container: ApiContainer, llm: ScriptedRevisionLLM) -> PlanEngineContainer:
    return build_engine_container(
        sessions=container.plan_sessions,
        followups=container.followup_rounds,
        plans=container.plans,
        plan_tasks=container.plan_tasks,
        plan_revisions=container.plan_revisions,
        checkins=container.checkins,
        documents=container.documents,
        role_models=container.role_models,
        profiles=container.profiles,
        llm_calls=container.llm_calls,
        cache=container.cache,
        llm=llm,
    )


def _postponed(template: PlanTemplate) -> dict[str, Any]:
    """The same plan, `EXTRA_WEEKS` longer: what the `postpone` strategy allows."""
    last = template.phases[-1]
    revised = template.model_copy(
        update={
            "duration_weeks": template.duration_weeks + EXTRA_WEEKS,
            "phases": [
                *template.phases[:-1],
                last.model_copy(update={"week_end": last.week_end + EXTRA_WEEKS}),
            ],
        }
    )
    return {
        "template": revised.model_dump(mode="json"),
        "rationale": f"本週的任務都沒完成，把期程延後 {EXTRA_WEEKS} 週，強度與目標維持不變。",
    }


async def test_end_to_end_missed_then_revise_then_accept(
    client: httpx.AsyncClient, container: ApiContainer, auth_headers: dict[str, str]
) -> None:
    queue = container.queue
    assert isinstance(queue, InMemoryQueue)
    llm = ScriptedRevisionLLM()
    handlers = create_api_handlers(container) | create_engine_handlers(_engine_on(container, llm))

    # 1. one session, three plans, one of them activated and exported to Google Calendar.
    created = await client.post(
        "/v1/plan-sessions", json={"goal": "12 週 5K 跑進 30 分"}, headers=auth_headers
    )
    assert created.status_code == 202
    session_id = created.json()["session_id"]
    await queue.drain(handlers)

    session = (await client.get(f"/v1/plan-sessions/{session_id}", headers=auth_headers)).json()
    assert session["status"] == "done"
    plan_id = UUID(next(p["id"] for p in session["plans"] if p["difficulty"] == "hard"))

    activated = await client.patch(
        f"/v1/plans/{plan_id}", json={"status": "active"}, headers=auth_headers
    )
    assert activated.status_code == 200
    old_deadline = activated.json()["deadline"]

    user_id = (await container.plans.get_unscoped(plan_id)).user_id  # type: ignore[union-attr]
    await container.complete_integration(user_id, "google", "code")
    await client.post(
        f"/v1/plans/{plan_id}/export", json={"target": GOOGLE_CALENDAR}, headers=auth_headers
    )
    await queue.drain(handlers)  # export.push, full mode
    calendar = container.calendar
    assert isinstance(calendar, FakeCalendar)
    assert calendar.created_events

    # 2. the first week goes badly: every task of it is checked in as missed.
    tasks = (await client.get(f"/v1/plans/{plan_id}/tasks", headers=auth_headers)).json()["items"]
    first_week = [task for task in tasks if task["week_index"] == 0]
    assert first_week
    checkin = await client.post(
        f"/v1/plans/{plan_id}/checkins",
        json={
            "checkin_date": first_week[-1]["start_at"][:10],
            "results": [
                {"task_id": task["id"], "status": "missed", "reason": "出差"} for task in first_week
            ],
        },
        headers=auth_headers,
    )
    assert checkin.status_code == 200
    await queue.drain(handlers)  # the incremental export the check-in triggered

    # 3. the user asks for a postponement.
    plan = await container.plans.get_unscoped(plan_id)
    assert plan is not None
    llm.revision = _postponed(PlanTemplate.model_validate(plan.template))
    requested = await client.post(
        f"/v1/plans/{plan_id}/revisions", json={"strategy": "postpone"}, headers=auth_headers
    )
    assert requested.status_code == 202
    revision_id = requested.json()["revision_id"]

    # 4. the engine proposes one.
    await queue.drain(handlers)
    proposal = (
        await client.get(f"/v1/plans/{plan_id}/revisions/{revision_id}", headers=auth_headers)
    ).json()
    assert proposal["status"] == "proposed"
    assert proposal["diff"]
    assert proposal["summary"]["added"] > 0
    assert proposal["rationale"]

    # 5. accepting it replaces the future tasks and pushes the deadline out.
    before_tasks = await container.plan_tasks.list(plan_id, None, None)
    accepted = await client.post(
        f"/v1/plans/{plan_id}/revisions/{revision_id}/accept", headers=auth_headers
    )
    assert accepted.status_code == 200
    assert accepted.json()["status"] == "accepted"

    detail = (await client.get(f"/v1/plans/{plan_id}", headers=auth_headers)).json()
    assert detail["deadline"] > old_deadline
    after_tasks = await container.plan_tasks.list(plan_id, None, None)
    assert {task.id for task in after_tasks} != {task.id for task in before_tasks}
    assert max(task.week_index for task in after_tasks) > max(
        task.week_index for task in before_tasks
    )

    # 6. and the calendar is brought back in line.
    assert queue.enqueued[-1] == ExportJobV1(
        plan_id=plan_id, target=GOOGLE_CALENDAR, mode="incremental"
    )
    writes_before = len(calendar.created_events) + len(calendar.updated_events)
    await queue.drain(handlers)
    assert len(calendar.created_events) + len(calendar.updated_events) > writes_before
