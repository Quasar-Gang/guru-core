"""The daily check-in: one row per plan and day, written straight through to the tasks (PRD 3.7)."""

from collections.abc import Sequence
from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

from packages.queue import QueuePort
from packages.repo import CheckinRepo, PlanExportRepo, PlanRepo, PlanTaskRepo
from packages.repo.entities import Checkin, TaskStatusUpdate
from services.api.application.ports import ClockPort
from services.api.application.update_plan_task import enqueue_incremental_export
from services.api.domain.errors import InvalidInput, NotFound

__all__ = ["CheckinResultInput", "CheckinView", "SubmitCheckin", "checkin_view"]


class CheckinResultInput(BaseModel):
    """What the user ticked for one task."""

    task_id: UUID
    status: Literal["done", "missed", "skipped"]
    reason: str | None = None


class CheckinView(BaseModel):
    id: UUID
    checkin_date: date
    results: list[CheckinResultInput]
    note: str | None
    created_at: datetime


def checkin_view(checkin: Checkin) -> CheckinView:
    return CheckinView(
        id=checkin.id,
        checkin_date=checkin.checkin_date,
        results=[CheckinResultInput.model_validate(r) for r in checkin.task_results],
        note=checkin.note,
        created_at=checkin.created_at,
    )


class SubmitCheckin:
    """Completion lives in `plan_tasks`; the calendar is only a projection of it."""

    def __init__(
        self,
        plans: PlanRepo,
        plan_tasks: PlanTaskRepo,
        checkins: CheckinRepo,
        exports: PlanExportRepo,
        queue: QueuePort,
        clock: ClockPort,
    ) -> None:
        self._plans = plans
        self._plan_tasks = plan_tasks
        self._checkins = checkins
        self._exports = exports
        self._queue = queue
        self._clock = clock

    async def __call__(
        self,
        user_id: UUID,
        plan_id: UUID,
        checkin_date: date,
        results: Sequence[CheckinResultInput],
        note: str | None,
    ) -> CheckinView:
        if await self._plans.get(user_id, plan_id) is None:
            raise NotFound(f"plan not found: {plan_id}")

        for result in results:
            if await self._plan_tasks.get(plan_id, result.task_id) is None:
                raise InvalidInput(f"task {result.task_id} does not belong to plan {plan_id}")

        checkin = await self._checkins.upsert(
            plan_id,
            checkin_date,
            [result.model_dump(mode="json") for result in results],
            note,
        )

        now = self._clock.now()
        await self._plan_tasks.bulk_set_status(
            plan_id,
            [
                TaskStatusUpdate(
                    task_id=result.task_id,
                    status=result.status,
                    completed_at=now if result.status == "done" else None,
                    missed_reason=result.reason,
                )
                for result in results
            ],
        )
        # bulk_set_status does not touch the export bookkeeping, so mark the tasks dirty here.
        for result in results:
            await self._plan_tasks.update_fields(result.task_id, synced_at=None)

        if results:
            await enqueue_incremental_export(self._exports, self._queue, plan_id)
        return checkin_view(checkin)
