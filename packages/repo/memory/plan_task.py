"""InMemoryPlanTaskRepo — in-memory implementation for tests."""

from __future__ import annotations

import builtins
import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from packages.repo.entities import NewPlanTask, PlanTask, TaskStatusUpdate

TASK_STATUSES = ("pending", "done", "missed", "skipped")


class InMemoryPlanTaskRepo:
    """PlanTaskRepo implementation that keeps plan_tasks in process memory."""

    def __init__(self) -> None:
        self._tasks: dict[UUID, PlanTask] = {}

    async def replace_all(self, plan_id: UUID, tasks: Sequence[NewPlanTask]) -> None:
        self._drop(plan_id, lambda _: True)
        self._insert(plan_id, tasks)

    async def replace_from(
        self, plan_id: UUID, cutoff: datetime, tasks: Sequence[NewPlanTask]
    ) -> None:
        self._drop(plan_id, lambda t: t.start_at >= cutoff)
        self._insert(plan_id, tasks)

    async def list(
        self, plan_id: UUID, start_from: datetime | None, start_to: datetime | None
    ) -> builtins.list[PlanTask]:
        found = [t for t in self._tasks.values() if t.plan_id == plan_id]
        if start_from is not None:
            found = [t for t in found if t.start_at >= start_from]
        if start_to is not None:
            found = [t for t in found if t.start_at < start_to]
        found.sort(key=lambda t: (t.start_at, t.sort_order))
        return found

    async def get(self, plan_id: UUID, task_id: UUID) -> PlanTask | None:
        task = self._tasks.get(task_id)
        return task if task is not None and task.plan_id == plan_id else None

    async def update_fields(self, task_id: UUID, **fields: Any) -> PlanTask:
        task = self._tasks.get(task_id)
        if task is None:
            raise KeyError(task_id)
        updated = task.model_copy(update=fields)
        self._tasks[task_id] = updated
        return updated

    async def bulk_set_status(self, plan_id: UUID, results: Sequence[TaskStatusUpdate]) -> None:
        for result in results:
            task = self._tasks.get(result.task_id)
            if task is None or task.plan_id != plan_id:
                continue
            self._tasks[task.id] = task.model_copy(
                update={
                    "status": result.status,
                    "completed_at": result.completed_at,
                    "missed_reason": result.missed_reason,
                }
            )

    async def counts_by_status(self, plan_id: UUID) -> dict[str, int]:
        counts = dict.fromkeys(TASK_STATUSES, 0)
        for task in self._tasks.values():
            if task.plan_id == plan_id and task.status in counts:
                counts[task.status] += 1
        return counts

    async def list_dirty(self, plan_id: UUID) -> builtins.list[PlanTask]:
        tasks = await self.list(plan_id, None, None)
        return [t for t in tasks if _is_dirty(t)]

    def _drop(self, plan_id: UUID, predicate: Any) -> None:
        for task in list(self._tasks.values()):
            if task.plan_id == plan_id and predicate(task):
                del self._tasks[task.id]

    def _insert(self, plan_id: UUID, tasks: Sequence[NewPlanTask]) -> None:
        for new_task in tasks:
            task = PlanTask(id=uuid.uuid4(), plan_id=plan_id, **new_task.model_dump())
            self._tasks[task.id] = task


def _is_dirty(task: PlanTask) -> bool:
    """Never synced, or changed since the last sync.

    plan_tasks has no updated_at, so completed_at stands in for the last change.
    """
    if task.synced_at is None:
        return True
    return task.completed_at is not None and task.completed_at > task.synced_at
