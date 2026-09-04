"""M2 acceptance: goal only -> follow-up -> answers -> three plans with checkable tasks.

The API service and the Plan Engine are separate deployables that share one database. Here
that sharing is reproduced by building the Plan Engine test container **on top of the API
container's in-memory repos**, so a row written over HTTP is the same row the engine reads.
The `InMemoryQueue` stands in for ARQ: `drain` runs the engine's worker handlers in-process.
"""

from pathlib import Path
from typing import Any
from uuid import UUID

import httpx

from packages.llm.fake import FakeLLM
from packages.llm.ports import OutputT, Purpose
from packages.queue import InMemoryQueue
from services.api.container import ApiContainer
from services.plan_engine.container import PlanEngineContainer, create_worker_handlers
from services.plan_engine.container import build_test_container as build_engine_container

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "llm"

_FIRST_ROUND: dict[str, Any] = {
    "ready": False,
    "missing": ["capacity"],
    "questions": [
        {
            "id": "q1",
            "metric_id": "capacity",
            "text": "how many sessions a week can you commit to, and for how long?",
            "options": [
                "two evenings, 40 minutes each",
                "three evenings, 30 minutes each",
                "weekends only, 60 minutes each",
            ],
            "allow_custom": True,
            "allow_skip": True,
        }
    ],
}
_READY: dict[str, Any] = {"ready": True, "missing": [], "questions": []}


class AskOnceLLM:
    """Ask one round of follow-ups, then declare the session ready.

    Everything other than `evaluate_readiness` is answered from the shared fixtures.
    """

    def __init__(self) -> None:
        self._fake = FakeLLM(FIXTURES_DIR)
        self._evaluations = 0

    async def complete(
        self,
        prompt_name: str,
        context: dict[str, Any],
        output_schema: type[OutputT],
        purpose: Purpose,
    ) -> OutputT:
        if prompt_name != "evaluate_readiness":
            return await self._fake.complete(prompt_name, context, output_schema, purpose)
        self._evaluations += 1
        payload = _FIRST_ROUND if self._evaluations == 1 else _READY
        return output_schema.model_validate(payload)


def _engine_on(container: ApiContainer) -> PlanEngineContainer:
    """A Plan Engine container sharing the API container's repos and cache."""
    return build_engine_container(
        sessions=container.plan_sessions,
        followups=container.followup_rounds,
        plans=container.plans,
        plan_tasks=container.plan_tasks,
        plan_revisions=container.plan_revisions,
        documents=container.documents,
        role_models=container.role_models,
        profiles=container.profiles,
        llm_calls=container.llm_calls,
        cache=container.cache,
        llm=AskOnceLLM(),
    )


async def test_end_to_end_goal_only_to_three_plans(
    client: httpx.AsyncClient, container: ApiContainer, auth_headers: dict[str, str]
) -> None:
    queue = container.queue
    assert isinstance(queue, InMemoryQueue)
    handlers = create_worker_handlers(_engine_on(container))

    created = await client.post(
        "/v1/plan-sessions",
        json={"goal": "12 週 5K 跑進 30 分"},
        headers=auth_headers,
    )
    assert created.status_code == 202
    session_id = created.json()["session_id"]

    await queue.drain(handlers)  # first round: follow-up questions
    body = (await client.get(f"/v1/plan-sessions/{session_id}", headers=auth_headers)).json()
    assert body["status"] == "questioning"
    assert len(body["questions"]) >= 1

    answered = await client.post(
        f"/v1/plan-sessions/{session_id}/answers",
        headers=auth_headers,
        json={
            "answers": [
                {"question_id": q["id"], "choice": q["options"][0]} for q in body["questions"]
            ]
        },
    )
    assert answered.status_code == 202

    await queue.drain(handlers)  # second round: generation
    body = (await client.get(f"/v1/plan-sessions/{session_id}", headers=auth_headers)).json()
    assert body["status"] == "done"
    assert len(body["plans"]) == 3
    assert {p["difficulty"] for p in body["plans"]} == {"easy", "hard", "extremely_hard"}
    summary = body["plans"][0]
    assert summary["sessions_per_week"] > 0
    assert summary["total_minutes_per_week"] > 0
    assert summary["completion_rate"] == 0.0

    # The checkable tasks are read straight from the repo: `GET /v1/plans/{id}/tasks` is
    # Task 31's endpoint and does not exist yet.
    plan_id = UUID(summary["id"])
    tasks = await container.plan_tasks.list(plan_id, None, None)
    assert len(tasks) > 0
    assert all(task.status == "pending" for task in tasks)
