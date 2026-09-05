"""PostgreSQL repos for Station 2: plans, the plan tree, check-ins and exports."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import ColumnElement, Select, delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from packages.repo import models
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

__all__ = ["PgCheckinRepo", "PgPlanExportRepo", "PgPlanRepo", "PgPlanTreeRepo"]

TASK_STATUSES = ("pending", "done", "missed", "skipped")


def _plan(row: models.Plan) -> Plan:
    return Plan(
        id=row.id,
        user_id=row.user_id,
        hypothesis_id=row.hypothesis_id,
        title=row.title,
        status=row.status,
        start_date=row.start_date,
        duration_weeks=row.duration_weeks,
        structure=row.structure,
        error=row.error,
        activated_at=row.activated_at,
        archived_at=row.archived_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _milestone(row: models.Milestone) -> Milestone:
    return Milestone(
        id=row.id,
        plan_id=row.plan_id,
        parent_id=row.parent_id,
        key=row.key,
        title=row.title,
        metric=row.metric,
        target_date=row.target_date,
        depth=row.depth,
        position=row.position,
        status=row.status,
    )


def _task(row: models.Task) -> Task:
    return Task(
        id=row.id,
        plan_id=row.plan_id,
        milestone_id=row.milestone_id,
        key=row.key,
        week_index=row.week_index,
        occurrence=row.occurrence,
        area=row.area,
        task_type=row.task_type,
        title=row.title,
        description=row.description,
        duration_minutes=row.duration_minutes,
        status=row.status,
        completed_at=row.completed_at,
        sort_order=row.sort_order,
    )


def _slot(row: models.ScheduleSlot) -> ScheduleSlot:
    return ScheduleSlot(
        id=row.id,
        plan_id=row.plan_id,
        task_id=row.task_id,
        start_at=row.start_at,
        end_at=row.end_at,
        all_day=row.all_day,
        external_ref=row.external_ref,
        synced_at=row.synced_at,
    )


def _checkin(row: models.Checkin) -> Checkin:
    return Checkin(
        id=row.id,
        plan_id=row.plan_id,
        checkin_date=row.checkin_date,
        task_results=row.task_results,
        note=row.note,
        created_at=row.created_at,
    )


def _export(row: models.PlanExport) -> PlanExport:
    return PlanExport(
        id=row.id,
        plan_id=row.plan_id,
        target=row.target,
        external_calendar_id=row.external_calendar_id,
        last_synced_at=row.last_synced_at,
        status=row.status,
        error=row.error,
        created_at=row.created_at,
    )


def _dirty_clause() -> ColumnElement[bool]:
    """Never synced, or completed after the last sync."""
    return or_(
        models.ScheduleSlot.synced_at.is_(None),
        models.Task.completed_at > models.ScheduleSlot.synced_at,
    )


class _Repo:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory


class PgPlanRepo(_Repo):
    async def create(self, user_id: UUID, hypothesis_id: UUID) -> Plan:
        async with self._session_factory() as session:
            row = models.Plan(user_id=user_id, hypothesis_id=hypothesis_id)
            session.add(row)
            await session.flush()
            await session.refresh(row)
            entity = _plan(row)
            await session.commit()
            return entity

    async def get(self, user_id: UUID, plan_id: UUID) -> Plan | None:
        async with self._session_factory() as session:
            row = await session.scalar(
                select(models.Plan).where(models.Plan.id == plan_id, models.Plan.user_id == user_id)
            )
            return _plan(row) if row is not None else None

    async def get_unscoped(self, plan_id: UUID) -> Plan | None:
        async with self._session_factory() as session:
            row = await session.get(models.Plan, plan_id)
            return _plan(row) if row is not None else None

    async def get_by_hypothesis(self, hypothesis_id: UUID) -> Plan | None:
        async with self._session_factory() as session:
            row = await session.scalar(
                select(models.Plan).where(models.Plan.hypothesis_id == hypothesis_id)
            )
            return _plan(row) if row is not None else None

    async def list_for_user(self, user_id: UUID, status: str | None) -> list[Plan]:
        stmt = select(models.Plan).where(models.Plan.user_id == user_id)
        if status is not None:
            stmt = stmt.where(models.Plan.status == status)
        stmt = stmt.order_by(models.Plan.created_at.desc())
        async with self._session_factory() as session:
            rows = await session.scalars(stmt)
            return [_plan(row) for row in rows]

    async def update_fields(self, plan_id: UUID, **fields: Any) -> Plan:
        async with self._session_factory() as session:
            row = await session.get(models.Plan, plan_id)
            if row is None:
                raise KeyError(plan_id)
            for key, value in fields.items():
                setattr(row, key, value)
            await session.flush()
            await session.refresh(row)
            entity = _plan(row)
            await session.commit()
            return entity


class PgPlanTreeRepo(_Repo):
    async def replace_tree(
        self,
        plan_id: UUID,
        milestones: Sequence[NewMilestone],
        tasks: Sequence[NewTask],
    ) -> None:
        """Write the whole tree in one transaction.

        Milestones are inserted shallowest first so a parent always has an id by the time
        its children need one; the schedule slot is written alongside its task.
        """
        async with self._session_factory() as session:
            await session.execute(
                delete(models.Milestone).where(models.Milestone.plan_id == plan_id)
            )
            await session.execute(delete(models.Task).where(models.Task.plan_id == plan_id))
            ids: dict[str, UUID] = {}
            for milestone in sorted(milestones, key=lambda item: (item.depth, item.position)):
                row = models.Milestone(
                    plan_id=plan_id,
                    parent_id=ids.get(milestone.parent_key or ""),
                    key=milestone.key,
                    title=milestone.title,
                    metric=milestone.metric,
                    target_date=milestone.target_date,
                    depth=milestone.depth,
                    position=milestone.position,
                )
                session.add(row)
                await session.flush()
                ids[milestone.key] = row.id
            for task in tasks:
                row_task = models.Task(
                    plan_id=plan_id,
                    milestone_id=ids[task.milestone_key],
                    **task.model_dump(exclude={"milestone_key", "start_at", "end_at", "all_day"}),
                )
                session.add(row_task)
                await session.flush()
                session.add(
                    models.ScheduleSlot(
                        plan_id=plan_id,
                        task_id=row_task.id,
                        start_at=task.start_at,
                        end_at=task.end_at,
                        all_day=task.all_day,
                    )
                )
            await session.commit()

    async def list_milestones(self, plan_id: UUID) -> list[Milestone]:
        async with self._session_factory() as session:
            rows = await session.scalars(
                select(models.Milestone)
                .where(models.Milestone.plan_id == plan_id)
                .order_by(models.Milestone.depth, models.Milestone.position)
            )
            return [_milestone(row) for row in rows]

    async def list_scheduled(
        self, plan_id: UUID, start_from: datetime | None = None, start_to: datetime | None = None
    ) -> list[ScheduledTaskRow]:
        stmt = (
            select(models.Task, models.ScheduleSlot)
            .join(models.ScheduleSlot, models.ScheduleSlot.task_id == models.Task.id)
            .where(models.Task.plan_id == plan_id)
        )
        if start_from is not None:
            stmt = stmt.where(models.ScheduleSlot.start_at >= start_from)
        if start_to is not None:
            stmt = stmt.where(models.ScheduleSlot.start_at < start_to)
        stmt = stmt.order_by(models.ScheduleSlot.start_at, models.Task.sort_order)
        async with self._session_factory() as session:
            rows = await session.execute(stmt)
            return [
                ScheduledTaskRow(task=_task(task), slot=_slot(slot)) for task, slot in rows.all()
            ]

    async def list_dirty(self, plan_id: UUID) -> list[ScheduledTaskRow]:
        async with self._session_factory() as session:
            rows = await session.execute(
                select(models.Task, models.ScheduleSlot)
                .join(models.ScheduleSlot, models.ScheduleSlot.task_id == models.Task.id)
                .where(models.Task.plan_id == plan_id, _dirty_clause())
                .order_by(models.ScheduleSlot.start_at, models.Task.sort_order)
            )
            return [
                ScheduledTaskRow(task=_task(task), slot=_slot(slot)) for task, slot in rows.all()
            ]

    async def get_task(self, plan_id: UUID, task_id: UUID) -> Task | None:
        async with self._session_factory() as session:
            row = await session.scalar(
                select(models.Task).where(models.Task.id == task_id, models.Task.plan_id == plan_id)
            )
            return _task(row) if row is not None else None

    async def find_task(self, task_id: UUID) -> ScheduledTaskRow | None:
        async with self._session_factory() as session:
            row = (
                await session.execute(
                    select(models.Task, models.ScheduleSlot)
                    .join(models.ScheduleSlot, models.ScheduleSlot.task_id == models.Task.id)
                    .where(models.Task.id == task_id)
                )
            ).first()
            if row is None:
                return None
            return ScheduledTaskRow(task=_task(row[0]), slot=_slot(row[1]))

    async def set_task_status(
        self, task_id: UUID, status: str, completed_at: datetime | None
    ) -> Task:
        async with self._session_factory() as session:
            row = await session.get(models.Task, task_id)
            if row is None:
                raise KeyError(task_id)
            row.status = status
            row.completed_at = completed_at
            await session.flush()
            await session.refresh(row)
            entity = _task(row)
            await session.commit()
            return entity

    async def bulk_set_status(self, plan_id: UUID, results: Sequence[TaskStatusUpdate]) -> None:
        if not results:
            return
        async with self._session_factory() as session:
            for result in results:
                await session.execute(
                    update(models.Task)
                    .where(models.Task.id == result.task_id, models.Task.plan_id == plan_id)
                    .values(status=result.status, completed_at=result.completed_at)
                )
            await session.commit()

    async def counts_by_status(self, plan_id: UUID) -> dict[str, int]:
        counts = dict.fromkeys(TASK_STATUSES, 0)
        async with self._session_factory() as session:
            rows = await session.execute(
                select(models.Task.status, func.count())
                .where(models.Task.plan_id == plan_id)
                .group_by(models.Task.status)
            )
            for status, count in rows.all():
                if status in counts:
                    counts[status] = count
        return counts

    async def mark_dirty(self, task_id: UUID) -> None:
        async with self._session_factory() as session:
            await session.execute(
                update(models.ScheduleSlot)
                .where(models.ScheduleSlot.task_id == task_id)
                .values(synced_at=None)
            )
            await session.commit()

    async def mark_synced(
        self, task_id: UUID, external_ref: str | None, synced_at: datetime | None
    ) -> None:
        async with self._session_factory() as session:
            await session.execute(
                update(models.ScheduleSlot)
                .where(models.ScheduleSlot.task_id == task_id)
                .values(external_ref=external_ref, synced_at=synced_at)
            )
            await session.commit()


class PgCheckinRepo(_Repo):
    async def upsert(
        self,
        plan_id: UUID,
        checkin_date: date,
        task_results: list[dict[str, Any]],
        note: str | None,
    ) -> Checkin:
        async with self._session_factory() as session:
            row = await session.scalar(
                select(models.Checkin).where(
                    models.Checkin.plan_id == plan_id,
                    models.Checkin.checkin_date == checkin_date,
                )
            )
            if row is None:
                row = models.Checkin(plan_id=plan_id, checkin_date=checkin_date)
                session.add(row)
            row.task_results = task_results
            row.note = note
            await session.flush()
            await session.refresh(row)
            entity = _checkin(row)
            await session.commit()
            return entity

    async def list_for_plan(self, plan_id: UUID) -> list[Checkin]:
        async with self._session_factory() as session:
            rows = await session.scalars(
                select(models.Checkin)
                .where(models.Checkin.plan_id == plan_id)
                .order_by(models.Checkin.checkin_date)
            )
            return [_checkin(row) for row in rows]


class PgPlanExportRepo(_Repo):
    async def get(self, plan_id: UUID, target: str) -> PlanExport | None:
        async with self._session_factory() as session:
            row = await session.scalar(_export_stmt(plan_id, target))
            return _export(row) if row is not None else None

    async def list_for_plan(self, plan_id: UUID) -> list[PlanExport]:
        async with self._session_factory() as session:
            rows = await session.scalars(
                select(models.PlanExport)
                .where(models.PlanExport.plan_id == plan_id)
                .order_by(models.PlanExport.target)
            )
            return [_export(row) for row in rows]

    async def upsert(
        self,
        plan_id: UUID,
        target: str,
        status: str,
        external_calendar_id: str | None,
        last_synced_at: datetime | None,
        error: str | None,
    ) -> PlanExport:
        async with self._session_factory() as session:
            row = await session.scalar(_export_stmt(plan_id, target))
            if row is None:
                row = models.PlanExport(plan_id=plan_id, target=target)
                session.add(row)
            row.status = status
            row.external_calendar_id = external_calendar_id
            row.last_synced_at = last_synced_at
            row.error = error
            await session.flush()
            await session.refresh(row)
            entity = _export(row)
            await session.commit()
            return entity

    async def delete(self, plan_id: UUID, target: str) -> None:
        async with self._session_factory() as session:
            await session.execute(
                delete(models.PlanExport).where(
                    models.PlanExport.plan_id == plan_id, models.PlanExport.target == target
                )
            )
            await session.commit()


def _export_stmt(plan_id: UUID, target: str) -> Select[tuple[models.PlanExport]]:
    return select(models.PlanExport).where(
        models.PlanExport.plan_id == plan_id, models.PlanExport.target == target
    )
