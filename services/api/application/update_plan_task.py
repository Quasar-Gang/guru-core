"""Tick a task off or move it, and re-sync the external calendar afterwards (PRD 3.7)."""

from datetime import datetime
from typing import Any
from uuid import UUID

from packages.queue import ExportJobV1, QueuePort
from packages.repo import PlanExportRepo, PlanRepo, PlanTaskRepo
from services.api.application.list_plan_tasks import PlanTaskView, task_view
from services.api.application.ports import ClockPort
from services.api.domain.errors import InvalidInput, NotFound

__all__ = ["TASK_STATUSES", "UpdatePlanTask", "enqueue_incremental_export"]

#: The only statuses a task may be set to (PRD 3.7).
TASK_STATUSES = frozenset({"pending", "done", "missed", "skipped"})

GOOGLE_CALENDAR = "google_calendar"


async def enqueue_incremental_export(
    exports: PlanExportRepo, queue: QueuePort, plan_id: UUID
) -> None:
    """Push the change to Google Calendar, but only for a plan that was actually exported."""
    if await exports.get(plan_id, GOOGLE_CALENDAR) is None:
        return
    await queue.enqueue(ExportJobV1(plan_id=plan_id, target=GOOGLE_CALENDAR, mode="incremental"))


class UpdatePlanTask:
    """Any accepted change clears `synced_at`, which is what marks the task dirty."""

    def __init__(
        self,
        plans: PlanRepo,
        plan_tasks: PlanTaskRepo,
        exports: PlanExportRepo,
        queue: QueuePort,
        clock: ClockPort,
    ) -> None:
        self._plans = plans
        self._plan_tasks = plan_tasks
        self._exports = exports
        self._queue = queue
        self._clock = clock

    async def __call__(
        self,
        user_id: UUID,
        plan_id: UUID,
        task_id: UUID,
        *,
        status: str | None,
        start_at: datetime | None,
        end_at: datetime | None,
        missed_reason: str | None,
    ) -> PlanTaskView:
        if await self._plans.get(user_id, plan_id) is None:
            raise NotFound(f"plan not found: {plan_id}")
        task = await self._plan_tasks.get(plan_id, task_id)
        if task is None:
            raise NotFound(f"plan task not found: {task_id}")

        if status is not None and status not in TASK_STATUSES:
            raise InvalidInput(f"unknown task status: {status}")
        if start_at is not None or end_at is not None:
            new_start = start_at if start_at is not None else task.start_at
            new_end = end_at if end_at is not None else task.end_at
            if new_end <= new_start:
                raise InvalidInput("end_at must be after start_at")

        fields: dict[str, Any] = {}
        if start_at is not None:
            fields["start_at"] = start_at
        if end_at is not None:
            fields["end_at"] = end_at
        if status is not None:
            fields["status"] = status
            if status == "done":
                fields["completed_at"] = self._clock.now()
            elif status == "pending":
                fields["completed_at"] = None
        if missed_reason is not None:
            fields["missed_reason"] = missed_reason

        if not fields:
            return task_view(task)

        fields["synced_at"] = None
        updated = await self._plan_tasks.update_fields(task_id, **fields)
        await enqueue_incremental_export(self._exports, self._queue, plan_id)
        return task_view(updated)
