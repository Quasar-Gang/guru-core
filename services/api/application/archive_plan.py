"""Archive a plan: keep the data, hide it from the default list (PRD 3.5)."""

from uuid import UUID

from packages.repo import PlanRepo
from services.api.application.get_plan import GetPlan, PlanDetail
from services.api.application.ports import ClockPort
from services.api.domain.plan_status import PlanStatus, assert_plan_transition, parse_plan_status

__all__ = ["ArchivePlan"]


class ArchivePlan:
    """Archiving never touches an external calendar; only delete and unexport do (PRD 3.5)."""

    def __init__(self, plans: PlanRepo, clock: ClockPort, get_plan: GetPlan) -> None:
        self._plans = plans
        self._clock = clock
        self._get_plan = get_plan

    async def __call__(self, user_id: UUID, plan_id: UUID) -> PlanDetail:
        plan = await self._get_plan.load(user_id, plan_id)
        assert_plan_transition(parse_plan_status(plan.status), PlanStatus.archived)
        archived = await self._plans.update_fields(
            plan_id, status=PlanStatus.archived.value, archived_at=self._clock.now()
        )
        return await self._get_plan.detail(archived)
