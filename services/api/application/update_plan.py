"""Rename a plan, or move it along the lifecycle (PRD 3.5 / 5: `PATCH /plans/{id}`)."""

from typing import Any
from uuid import UUID

from packages.repo import PlanRepo
from services.api.application.get_plan import GetPlan, PlanDetail
from services.api.application.ports import ClockPort
from services.api.domain.errors import InvalidInput
from services.api.domain.plan_status import PlanStatus, assert_plan_transition, parse_plan_status

__all__ = ["UpdatePlan"]


class UpdatePlan:
    """Activating a plan is what picks one of a session's three difficulties (PRD 3.5)."""

    def __init__(self, plans: PlanRepo, clock: ClockPort, get_plan: GetPlan) -> None:
        self._plans = plans
        self._clock = clock
        self._get_plan = get_plan

    async def __call__(
        self, user_id: UUID, plan_id: UUID, *, title: str | None, status: str | None
    ) -> PlanDetail:
        plan = await self._get_plan.load(user_id, plan_id)

        changes: dict[str, Any] = {}
        if title is not None:
            if not title.strip():
                raise InvalidInput("title must not be blank")
            changes["title"] = title.strip()

        target: PlanStatus | None = None
        if status is not None:
            target = parse_plan_status(status)
            assert_plan_transition(parse_plan_status(plan.status), target)
            changes["status"] = target.value
            if target is PlanStatus.active:
                changes["activated_at"] = self._clock.now()
            elif target is PlanStatus.archived:
                changes["archived_at"] = self._clock.now()

        if changes:
            plan = await self._plans.update_fields(plan_id, **changes)
        if target is PlanStatus.active:
            # A session holds at most one active plan; the rest fall back to draft (PRD 3.5).
            await self._plans.set_status_for_session(
                plan.session_id, PlanStatus.draft.value, plan_id
            )
        return await self._get_plan.detail(plan)
