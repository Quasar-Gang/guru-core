"""Poll one plan session: its status, the open questions, and the generated plans (PRD 3.3)."""

from datetime import date
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from packages.repo import FollowupRoundRepo, PlanRepo, PlanSessionRepo, PlanTaskRepo
from packages.repo.entities import Plan
from services.api.domain.errors import NotFound

__all__ = ["FollowupQuestion", "GetPlanSession", "PlanSessionView", "PlanSummary"]

STATUS_QUESTIONING = "questioning"
STATUS_DONE = "done"

#: Statuses a task can reach that count towards the completion rate (PRD 3.5).
_RESOLVED_STATUSES = ("done", "missed", "skipped")


class FollowupQuestion(BaseModel):
    """One follow-up question as the client sees it.

    Deliberately a second definition of the Plan Engine's
    `services.plan_engine.domain.readiness.FollowupQuestion`: services must not import each
    other, so the two sides are bound by the JSON stored in `followup_rounds.questions`,
    exactly as `Pacing` is duplicated between the Plan Engine and the Role Model service.
    """

    id: str
    metric_id: str
    text: str
    options: list[str] = []
    allow_custom: bool = True
    allow_skip: bool = True


class PlanSummary(BaseModel):
    """One generated plan, condensed to what a chooser screen needs."""

    id: UUID
    title: str
    difficulty: str
    status: str
    duration_weeks: int
    start_date: date
    deadline: date
    goal_statement: str
    sessions_per_week: int
    total_minutes_per_week: int
    completion_rate: float


class PlanSessionView(BaseModel):
    id: UUID
    status: str
    round: int
    goal: str
    questions: list[FollowupQuestion] = Field(default=[])
    plans: list[PlanSummary] = Field(default=[])
    error: str | None = None


class GetPlanSession:
    """Questions are filled in while `questioning`, plans once the session is `done`."""

    def __init__(
        self,
        sessions: PlanSessionRepo,
        followups: FollowupRoundRepo,
        plans: PlanRepo,
        plan_tasks: PlanTaskRepo,
    ) -> None:
        self._sessions = sessions
        self._followups = followups
        self._plans = plans
        self._plan_tasks = plan_tasks

    async def __call__(self, user_id: UUID, session_id: UUID) -> PlanSessionView:
        session = await self._sessions.get(user_id, session_id)
        if session is None:
            raise NotFound(f"plan session not found: {session_id}")

        questions: list[FollowupQuestion] = []
        if session.status == STATUS_QUESTIONING:
            latest = await self._followups.latest(session_id)
            if latest is not None:
                questions = [FollowupQuestion.model_validate(q) for q in latest.questions]

        summaries: list[PlanSummary] = []
        if session.status == STATUS_DONE:
            for plan in await self._plans.list_for_session(session_id):
                counts = await self._plan_tasks.counts_by_status(plan.id)
                summaries.append(_summary(plan, counts))

        return PlanSessionView(
            id=session.id,
            status=session.status,
            round=session.round,
            goal=session.goal,
            questions=questions,
            plans=summaries,
            error=session.error,
        )


def _summary(plan: Plan, counts: dict[str, int]) -> PlanSummary:
    weekly = _weekly_template(plan.template)
    return PlanSummary(
        id=plan.id,
        title=plan.title,
        difficulty=plan.difficulty,
        status=plan.status,
        duration_weeks=plan.duration_weeks,
        start_date=plan.start_date,
        deadline=plan.deadline,
        goal_statement=plan.goal_statement,
        sessions_per_week=sum(_int(item, "times_per_week") for item in weekly),
        total_minutes_per_week=sum(
            _int(item, "times_per_week") * _int(item, "duration_minutes") for item in weekly
        ),
        completion_rate=completion_rate(counts),
    )


def completion_rate(counts: dict[str, int]) -> float:
    """`done / (done + missed + skipped)`; a plan nobody has touched yet scores 0.0."""
    resolved = sum(counts.get(status, 0) for status in _RESOLVED_STATUSES)
    return counts.get("done", 0) / resolved if resolved else 0.0


def _weekly_template(template: dict[str, Any]) -> list[dict[str, Any]]:
    items = template.get("weekly_template", [])
    return [item for item in items if isinstance(item, dict)]


def _int(item: dict[str, Any], key: str) -> int:
    value = item.get(key, 0)
    return value if isinstance(value, int) else 0
