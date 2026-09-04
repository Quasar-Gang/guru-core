"""Report where each export target stands, and how much has changed since (PRD 3.5 / 5)."""

from uuid import UUID

from packages.repo import PlanExportRepo, PlanTaskRepo
from services.api.application.get_plan import ExportStatusView, GetPlan

__all__ = ["GetExportStatus"]


class GetExportStatus:
    """`pending_changes` is the dirty task count: what the next incremental push will send."""

    def __init__(
        self, get_plan: GetPlan, exports: PlanExportRepo, plan_tasks: PlanTaskRepo
    ) -> None:
        self._get_plan = get_plan
        self._exports = exports
        self._plan_tasks = plan_tasks

    async def __call__(self, user_id: UUID, plan_id: UUID) -> list[ExportStatusView]:
        await self._get_plan.load(user_id, plan_id)
        rows = await self._exports.list_for_plan(plan_id)
        if not rows:
            return []
        pending = len(await self._plan_tasks.list_dirty(plan_id))
        return [
            ExportStatusView(
                target=row.target,
                status=row.status,
                external_calendar_id=row.external_calendar_id,
                last_synced_at=row.last_synced_at,
                error=row.error,
                pending_changes=pending,
            )
            for row in rows
        ]
