"""Shared helpers for the Plan Engine application tests.

Everything here is deliberately synchronous-friendly and dependency-free: the tests must
run without Docker, a database, Redis or a network call.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from packages.llm.ports import LLMError, OutputT, Purpose
from services.plan_engine.container import PlanEngineContainer

FIXTURES_DIR = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "llm"

#: A trait pacing that caps the plan at three sessions a week.
PACING_MAX_THREE: dict[str, Any] = {
    "sessions_per_week": [1, 3],
    "session_minutes": [20, 60],
    "rest_days_min": 1,
    "progression_rate": 0.1,
    "missed_policy": "same-week",
    "intensity_bias": "medium",
}


def tpl(*, times: int = 3, weeks: int = 12, minutes: int = 40) -> dict[str, Any]:
    """A minimal well-formed ``generate_plans`` payload with a tunable weekly frequency."""
    per_phase = weeks // 3
    bounds = [
        (0, per_phase - 1),
        (per_phase, 2 * per_phase - 1),
        (2 * per_phase, weeks - 1),
    ]
    names = ["base", "build", "peak"]
    return {
        "template": {
            "title": "test plan",
            "goal_statement": "run 5k under 30 minutes",
            "duration_weeks": weeks,
            "assumptions": [],
            "success_criteria": ["finish 5k under 30:00"],
            "phases": [
                {
                    "index": index,
                    "name": names[index],
                    "week_start": start,
                    "week_end": end,
                    "focus": "focus",
                    "milestone": {"title": "milestone", "metric": "metric"},
                }
                for index, (start, end) in enumerate(bounds)
            ],
            "weekly_template": [
                {
                    "key": "run",
                    "title": "run",
                    "task_type": "session",
                    "day_hint": "any",
                    "slot_hint": "evening",
                    "duration_minutes": minutes,
                    "description": "steady run",
                    "times_per_week": times,
                }
            ],
        }
    }


class ScriptedLLM:
    """Return the scripted payloads in order, recording every context it was called with."""

    def __init__(self, payloads: list[dict[str, Any]]) -> None:
        self._payloads = list(payloads)
        self.calls: list[tuple[str, Purpose, dict[str, Any]]] = []
        self.contexts: list[dict[str, Any]] = []

    async def complete(
        self,
        prompt_name: str,
        context: dict[str, Any],
        output_schema: type[OutputT],
        purpose: Purpose,
    ) -> OutputT:
        self.calls.append((prompt_name, purpose, context))
        self.contexts.append(context)
        index = min(len(self.contexts) - 1, len(self._payloads) - 1)
        return output_schema.model_validate(self._payloads[index])


class AlwaysBadLLM:
    """Always return a template that breaches the pacing, so every attempt is rejected."""

    def __init__(self, times: int = 7) -> None:
        self._payload = tpl(times=times)
        self.calls: list[tuple[str, Purpose, dict[str, Any]]] = []
        self.contexts: list[dict[str, Any]] = []

    async def complete(
        self,
        prompt_name: str,
        context: dict[str, Any],
        output_schema: type[OutputT],
        purpose: Purpose,
    ) -> OutputT:
        self.calls.append((prompt_name, purpose, context))
        self.contexts.append(context)
        return output_schema.model_validate(self._payload)


class RaisingLLM:
    """Raise the given error on every call."""

    def __init__(self, error: LLMError) -> None:
        self._error = error
        self.calls: list[tuple[str, Purpose, dict[str, Any]]] = []

    async def complete(
        self,
        prompt_name: str,
        context: dict[str, Any],
        output_schema: type[OutputT],
        purpose: Purpose,
    ) -> OutputT:
        self.calls.append((prompt_name, purpose, context))
        raise self._error


async def seed_trait(container: PlanEngineContainer, pacing: dict[str, Any]) -> UUID:
    """Create a trait role model carrying the given pacing block."""
    role_model = await container.role_models.upsert(
        None, "trait", "steady", ["style:steady"], {"pacing": pacing}
    )
    return role_model.id


async def seed_session(
    container: PlanEngineContainer,
    *,
    goal: str = "run 5k under 30 minutes",
    status: str | None = None,
    round: int = 0,
    use_calendar: bool = False,
    trait_role_model_id: UUID | None = None,
    timezone: str = "UTC",
    intake: dict[str, Any] | None = None,
) -> UUID:
    """Create a user, a profile and a plan session, then move it to the wanted state."""
    user_id = uuid.uuid4()
    await container.profiles.upsert(user_id, {"timezone": timezone}, timezone)
    session = await container.sessions.create(
        user_id=user_id,
        goal=goal,
        intake=intake or {},
        import_ids=[],
        use_calendar=use_calendar,
        trait_role_model_id=trait_role_model_id,
        persona_role_model_id=None,
    )
    for _ in range(round):
        await container.sessions.bump_round(session.id)
    if status is not None:
        await container.sessions.set_status(session.id, status)
    return session.id


async def seed_answered_round(
    container: PlanEngineContainer,
    session_id: UUID,
    *,
    metric_id: str = "horizon",
    answer: str = "twelve weeks, no fixed deadline",
) -> None:
    """Record one asked-and-answered follow-up round on the session."""
    created = await container.followups.create(
        session_id,
        0,
        [
            {
                "id": "q1",
                "metric_id": metric_id,
                "text": "how long do you want to spend?",
                "options": ["8 weeks", "12 weeks", "6 months"],
                "allow_custom": True,
                "allow_skip": True,
            }
        ],
    )
    await container.followups.record_answers(
        created.id,
        [{"question_id": "q1", "metric_id": metric_id, "answer": answer}],
        datetime.now(UTC),
    )
