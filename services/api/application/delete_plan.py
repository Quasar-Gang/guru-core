"""Delete a plan and its tasks (PRD 3.5 / 5: `DELETE /plans/{id}`)."""

from uuid import UUID

from packages.repo import PlanRepo, PlanTaskRepo
from services.api.application.get_plan import GetPlan

__all__ = ["DeletePlan"]


class DeletePlan:
    """The tasks go first, so a plan is never left behind with orphaned rows."""

    def __init__(self, plans: PlanRepo, plan_tasks: PlanTaskRepo, get_plan: GetPlan) -> None:
        self._plans = plans
        self._plan_tasks = plan_tasks
        self._get_plan = get_plan

    async def __call__(self, user_id: UUID, plan_id: UUID) -> None:
        plan = await self._get_plan.load(user_id, plan_id)
        # TODO(Task 35): a plan with export rows must be unexported first — call UnexportPlan
        # for every `plan_exports` target so the external events and the dedicated Google
        # calendar go away before the rows do. Until that use case exists, the MVP drops the
        # database rows only, which can leave orphaned events behind in Google Calendar.
        await self._plan_tasks.replace_all(plan.id, [])
        await self._plans.delete(plan.id)
