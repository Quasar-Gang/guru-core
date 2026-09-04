"""List the user's plans, optionally filtered by status (PRD 5: `GET /plans`)."""

from uuid import UUID

from packages.repo import PlanRepo, PlanTaskRepo
from services.api.application.get_plan_session import (
    PlanSummary,
    _summary,  # the one definition of the summary shape and its rates (plan Task 24)
)
from services.api.domain.plan_status import PlanStatus, parse_plan_status

__all__ = ["ListPlans"]


class ListPlans:
    """No status filter means "everything I still work on": archived plans stay hidden."""

    def __init__(self, plans: PlanRepo, plan_tasks: PlanTaskRepo) -> None:
        self._plans = plans
        self._plan_tasks = plan_tasks

    async def __call__(self, user_id: UUID, status: str | None) -> list[PlanSummary]:
        wanted = parse_plan_status(status) if status is not None else None
        found = await self._plans.list_for_user(user_id, wanted.value if wanted else None)
        if wanted is None:
            found = [plan for plan in found if plan.status != PlanStatus.archived]
        return [_summary(plan, await self._plan_tasks.counts_by_status(plan.id)) for plan in found]
