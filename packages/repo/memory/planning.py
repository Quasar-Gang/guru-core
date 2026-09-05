"""In-memory repos for Station 2: plans, the plan tree, check-ins and exports."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime
from typing import Any
from uuid import UUID, uuid4

from packages.repo.entities import (
    Checkin,
    Milestone,
    NewMilestone,
    NewTask,
    Plan,
    PlanExport,
    ScheduledTaskRow,
    ScheduleSlot,
    Task,
    TaskStatusUpdate,
)
from packages.repo.memory.identity import now

__all__ = [
    "InMemoryCheckinRepo",
    "InMemoryPlanExportRepo",
    "InMemoryPlanRepo",
    "InMemoryPlanTreeRepo",
]

TASK_STATUSES = ("pending", "done", "missed", "skipped")


class InMemoryPlanRepo:
    def __init__(self) -> None:
        self._rows: dict[UUID, Plan] = {}

    async def create(self, user_id: UUID, hypothesis_id: UUID) -> Plan:
        moment = now()
        row = Plan(
            id=uuid4(),
            user_id=user_id,
            hypothesis_id=hypothesis_id,
            title="",
            status="generating",
            start_date=None,
            duration_weeks=0,
            structure={},
            error=None,
            activated_at=None,
            archived_at=None,
            created_at=moment,
            updated_at=moment,
        )
        self._rows[row.id] = row
        return row

    async def get(self, user_id: UUID, plan_id: UUID) -> Plan | None:
        row = self._rows.get(plan_id)
        return row if row is not None and row.user_id == user_id else None

    async def get_unscoped(self, plan_id: UUID) -> Plan | None:
        return self._rows.get(plan_id)

    async def get_by_hypothesis(self, hypothesis_id: UUID) -> Plan | None:
        return next(
            (row for row in self._rows.values() if row.hypothesis_id == hypothesis_id), None
        )

    async def list_for_user(self, user_id: UUID, status: str | None) -> list[Plan]:
        rows = [row for row in self._rows.values() if row.user_id == user_id]
        if status is not None:
            rows = [row for row in rows if row.status == status]
        return sorted(rows, key=lambda row: row.created_at, reverse=True)

    async def update_fields(self, plan_id: UUID, **fields: Any) -> Plan:
        row = self._rows[plan_id]
        updated = row.model_copy(update={**fields, "updated_at": now()})
        self._rows[plan_id] = updated
        return updated


class InMemoryPlanTreeRepo:
    def __init__(self) -> None:
        self._milestones: list[Milestone] = []
        self._tasks: list[Task] = []
        self._slots: dict[UUID, ScheduleSlot] = {}

    async def replace_tree(
        self,
        plan_id: UUID,
        milestones: Sequence[NewMilestone],
        tasks: Sequence[NewTask],
    ) -> None:
        self._milestones = [row for row in self._milestones if row.plan_id != plan_id]
        dropped = {row.id for row in self._tasks if row.plan_id == plan_id}
        self._tasks = [row for row in self._tasks if row.plan_id != plan_id]
        self._slots = {key: slot for key, slot in self._slots.items() if key not in dropped}

        ids: dict[str, UUID] = {}
        for milestone in sorted(milestones, key=lambda item: (item.depth, item.position)):
            row = Milestone(
                id=uuid4(),
                plan_id=plan_id,
                parent_id=ids.get(milestone.parent_key or ""),
                key=milestone.key,
                title=milestone.title,
                metric=milestone.metric,
                target_date=milestone.target_date,
                depth=milestone.depth,
                position=milestone.position,
                status="pending",
            )
            ids[milestone.key] = row.id
            self._milestones.append(row)

        for task in tasks:
            row_task = Task(
                id=uuid4(),
                plan_id=plan_id,
                milestone_id=ids[task.milestone_key],
                status="pending",
                completed_at=None,
                **task.model_dump(exclude={"milestone_key", "start_at", "end_at", "all_day"}),
            )
            self._tasks.append(row_task)
            self._slots[row_task.id] = ScheduleSlot(
                id=uuid4(),
                plan_id=plan_id,
                task_id=row_task.id,
                start_at=task.start_at,
                end_at=task.end_at,
                all_day=task.all_day,
                external_ref=None,
                synced_at=None,
            )

    async def list_milestones(self, plan_id: UUID) -> list[Milestone]:
        rows = [row for row in self._milestones if row.plan_id == plan_id]
        return sorted(rows, key=lambda row: (row.depth, row.position))

    async def list_scheduled(
        self, plan_id: UUID, start_from: datetime | None = None, start_to: datetime | None = None
    ) -> list[ScheduledTaskRow]:
        rows = [
            ScheduledTaskRow(task=task, slot=self._slots[task.id])
            for task in self._tasks
            if task.plan_id == plan_id
        ]
        if start_from is not None:
            rows = [row for row in rows if row.slot.start_at >= start_from]
        if start_to is not None:
            rows = [row for row in rows if row.slot.start_at < start_to]
        return sorted(rows, key=lambda row: (row.slot.start_at, row.task.sort_order))

    async def list_dirty(self, plan_id: UUID) -> list[ScheduledTaskRow]:
        rows = await self.list_scheduled(plan_id)
        return [row for row in rows if _is_dirty(row)]

    async def get_task(self, plan_id: UUID, task_id: UUID) -> Task | None:
        return next(
            (row for row in self._tasks if row.id == task_id and row.plan_id == plan_id), None
        )

    async def find_task(self, task_id: UUID) -> ScheduledTaskRow | None:
        task = next((row for row in self._tasks if row.id == task_id), None)
        if task is None:
            return None
        return ScheduledTaskRow(task=task, slot=self._slots[task.id])

    async def set_task_status(
        self, task_id: UUID, status: str, completed_at: datetime | None
    ) -> Task:
        return self._replace(task_id, {"status": status, "completed_at": completed_at})

    async def bulk_set_status(self, plan_id: UUID, results: Sequence[TaskStatusUpdate]) -> None:
        for result in results:
            task = await self.get_task(plan_id, result.task_id)
            if task is not None:
                self._replace(
                    result.task_id,
                    {"status": result.status, "completed_at": result.completed_at},
                )

    async def counts_by_status(self, plan_id: UUID) -> dict[str, int]:
        counts = dict.fromkeys(TASK_STATUSES, 0)
        for task in self._tasks:
            if task.plan_id == plan_id and task.status in counts:
                counts[task.status] += 1
        return counts

    async def mark_dirty(self, task_id: UUID) -> None:
        slot = self._slots.get(task_id)
        if slot is not None:
            self._slots[task_id] = slot.model_copy(update={"synced_at": None})

    async def mark_synced(
        self, task_id: UUID, external_ref: str | None, synced_at: datetime | None
    ) -> None:
        slot = self._slots.get(task_id)
        if slot is not None:
            self._slots[task_id] = slot.model_copy(
                update={"external_ref": external_ref, "synced_at": synced_at}
            )

    def _replace(self, task_id: UUID, fields: dict[str, Any]) -> Task:
        index = next(i for i, row in enumerate(self._tasks) if row.id == task_id)
        updated = self._tasks[index].model_copy(update=fields)
        self._tasks[index] = updated
        return updated


def _is_dirty(row: ScheduledTaskRow) -> bool:
    if row.slot.synced_at is None:
        return True
    return row.task.completed_at is not None and row.task.completed_at > row.slot.synced_at


class InMemoryCheckinRepo:
    def __init__(self) -> None:
        self._rows: dict[tuple[UUID, date], Checkin] = {}

    async def upsert(
        self,
        plan_id: UUID,
        checkin_date: date,
        task_results: list[dict[str, Any]],
        note: str | None,
    ) -> Checkin:
        existing = self._rows.get((plan_id, checkin_date))
        row = Checkin(
            id=existing.id if existing else uuid4(),
            plan_id=plan_id,
            checkin_date=checkin_date,
            task_results=task_results,
            note=note,
            created_at=existing.created_at if existing else now(),
        )
        self._rows[(plan_id, checkin_date)] = row
        return row

    async def list_for_plan(self, plan_id: UUID) -> list[Checkin]:
        rows = [row for key, row in self._rows.items() if key[0] == plan_id]
        return sorted(rows, key=lambda row: row.checkin_date)


class InMemoryPlanExportRepo:
    def __init__(self) -> None:
        self._rows: dict[tuple[UUID, str], PlanExport] = {}

    async def get(self, plan_id: UUID, target: str) -> PlanExport | None:
        return self._rows.get((plan_id, target))

    async def list_for_plan(self, plan_id: UUID) -> list[PlanExport]:
        rows = [row for key, row in self._rows.items() if key[0] == plan_id]
        return sorted(rows, key=lambda row: row.target)

    async def upsert(
        self,
        plan_id: UUID,
        target: str,
        status: str,
        external_calendar_id: str | None,
        last_synced_at: datetime | None,
        error: str | None,
    ) -> PlanExport:
        existing = self._rows.get((plan_id, target))
        row = PlanExport(
            id=existing.id if existing else uuid4(),
            plan_id=plan_id,
            target=target,
            external_calendar_id=external_calendar_id,
            last_synced_at=last_synced_at,
            status=status,
            error=error,
            created_at=existing.created_at if existing else now(),
        )
        self._rows[(plan_id, target)] = row
        return row

    async def delete(self, plan_id: UUID, target: str) -> None:
        self._rows.pop((plan_id, target), None)
