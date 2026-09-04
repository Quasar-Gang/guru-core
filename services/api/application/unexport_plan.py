"""Undo an export: drop the external calendar and forget every reference (PRD 3.5 / 4.3.4)."""

from uuid import UUID

from packages.repo import PlanExportRepo, PlanTaskRepo
from services.api.application.get_plan import GetPlan
from services.api.application.google_access_token import GoogleAccessTokenProvider
from services.api.application.ports import CalendarPort
from services.api.domain.errors import DomainError, NotFound

__all__ = ["UnexportPlan"]


class UnexportPlan:
    """The whole secondary calendar goes, not the events one by one (PRD 4.3.4)."""

    def __init__(
        self,
        get_plan: GetPlan,
        plan_tasks: PlanTaskRepo,
        exports: PlanExportRepo,
        calendar: CalendarPort,
        tokens: GoogleAccessTokenProvider,
    ) -> None:
        self._get_plan = get_plan
        self._plan_tasks = plan_tasks
        self._exports = exports
        self._calendar = calendar
        self._tokens = tokens

    async def __call__(self, user_id: UUID, plan_id: UUID, target: str) -> None:
        plan = await self._get_plan.load(user_id, plan_id)
        record = await self._exports.get(plan_id, target)
        if record is None:
            raise NotFound(f"plan {plan_id} is not exported to {target}")

        if record.external_calendar_id is not None:
            await self._drop_calendar(plan.user_id, record.external_calendar_id)
        for task in await self._plan_tasks.list(plan_id, None, None):
            if task.external_ref is not None or task.synced_at is not None:
                await self._plan_tasks.update_fields(task.id, external_ref=None, synced_at=None)
        await self._exports.delete(plan_id, target)

    async def _drop_calendar(self, user_id: UUID, calendar_id: str) -> None:
        """Best effort: a calendar the user already deleted, or an expired connection, must
        not leave the plan stuck in an exported state that can never be undone."""
        try:
            access_token = await self._tokens.get(user_id)
            await self._calendar.delete_calendar(access_token, calendar_id)
        except DomainError:
            return
