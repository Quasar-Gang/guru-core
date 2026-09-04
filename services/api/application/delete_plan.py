"""Delete a plan and its tasks (PRD 3.5 / 5: `DELETE /plans/{id}`)."""

from uuid import UUID

from packages.repo import PlanExportRepo, PlanRepo, PlanTaskRepo
from services.api.application.get_plan import GetPlan
from services.api.application.unexport_plan import UnexportPlan

__all__ = ["DeletePlan"]


class DeletePlan:
    """The tasks go first, so a plan is never left behind with orphaned rows."""

    def __init__(
        self,
        plans: PlanRepo,
        plan_tasks: PlanTaskRepo,
        exports: PlanExportRepo,
        unexport_plan: UnexportPlan,
        get_plan: GetPlan,
    ) -> None:
        self._plans = plans
        self._plan_tasks = plan_tasks
        self._exports = exports
        self._unexport_plan = unexport_plan
        self._get_plan = get_plan

    async def __call__(self, user_id: UUID, plan_id: UUID) -> None:
        plan = await self._get_plan.load(user_id, plan_id)
        # Deleting a plan deletes its external events too (PRD 3.5), so every export target
        # is undone before the rows that point at it disappear.
        for record in await self._exports.list_for_plan(plan.id):
            await self._unexport_plan(user_id, plan.id, record.target)
        await self._plan_tasks.replace_all(plan.id, [])
        await self._plans.delete(plan.id)
