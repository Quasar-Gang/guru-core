"""PgPlanTaskRepo — PostgreSQL implementation of the plan_tasks table."""

from __future__ import annotations

import builtins
from collections.abc import Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import ColumnElement, delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from packages.repo import models
from packages.repo.entities import NewPlanTask, PlanTask, TaskStatusUpdate

TASK_STATUSES = ("pending", "done", "missed", "skipped")


def _to_entity(row: models.PlanTask) -> PlanTask:
    return PlanTask(
        id=row.id,
        plan_id=row.plan_id,
        template_key=row.template_key,
        week_index=row.week_index,
        phase_index=row.phase_index,
        occurrence=row.occurrence,
        task_type=row.task_type,
        title=row.title,
        description=row.description,
        start_at=row.start_at,
        end_at=row.end_at,
        all_day=row.all_day,
        status=row.status,
        completed_at=row.completed_at,
        missed_reason=row.missed_reason,
        external_ref=row.external_ref,
        synced_at=row.synced_at,
        sort_order=row.sort_order,
    )


def _dirty_clause() -> ColumnElement[bool]:
    """Never synced, or changed since the last sync; completed_at stands in for a change."""
    return or_(
        models.PlanTask.synced_at.is_(None),
        models.PlanTask.completed_at > models.PlanTask.synced_at,
    )


class PgPlanTaskRepo:
    """PostgreSQL PlanTaskRepo."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def replace_all(self, plan_id: UUID, tasks: Sequence[NewPlanTask]) -> None:
        async with self._session_factory() as session:
            await session.execute(delete(models.PlanTask).where(models.PlanTask.plan_id == plan_id))
            self._add(session, plan_id, tasks)
            await session.commit()

    async def replace_from(
        self, plan_id: UUID, cutoff: datetime, tasks: Sequence[NewPlanTask]
    ) -> None:
        async with self._session_factory() as session:
            await session.execute(
                delete(models.PlanTask).where(
                    models.PlanTask.plan_id == plan_id,
                    models.PlanTask.start_at >= cutoff,
                )
            )
            self._add(session, plan_id, tasks)
            await session.commit()

    async def list(
        self, plan_id: UUID, start_from: datetime | None, start_to: datetime | None
    ) -> builtins.list[PlanTask]:
        stmt = select(models.PlanTask).where(models.PlanTask.plan_id == plan_id)
        if start_from is not None:
            stmt = stmt.where(models.PlanTask.start_at >= start_from)
        if start_to is not None:
            stmt = stmt.where(models.PlanTask.start_at < start_to)
        stmt = stmt.order_by(models.PlanTask.start_at, models.PlanTask.sort_order)
        async with self._session_factory() as session:
            rows = await session.scalars(stmt)
            return [_to_entity(row) for row in rows]

    async def get(self, plan_id: UUID, task_id: UUID) -> PlanTask | None:
        async with self._session_factory() as session:
            row = await session.scalar(
                select(models.PlanTask).where(
                    models.PlanTask.id == task_id, models.PlanTask.plan_id == plan_id
                )
            )
            return _to_entity(row) if row is not None else None

    async def update_fields(self, task_id: UUID, **fields: Any) -> PlanTask:
        async with self._session_factory() as session:
            row = await session.get(models.PlanTask, task_id)
            if row is None:
                raise KeyError(task_id)
            for key, value in fields.items():
                setattr(row, key, value)
            await session.flush()
            entity = _to_entity(row)
            await session.commit()
            return entity

    async def bulk_set_status(self, plan_id: UUID, results: Sequence[TaskStatusUpdate]) -> None:
        if not results:
            return
        async with self._session_factory() as session:
            for result in results:
                await session.execute(
                    update(models.PlanTask)
                    .where(
                        models.PlanTask.id == result.task_id,
                        models.PlanTask.plan_id == plan_id,
                    )
                    .values(
                        status=result.status,
                        completed_at=result.completed_at,
                        missed_reason=result.missed_reason,
                    )
                )
            await session.commit()

    async def counts_by_status(self, plan_id: UUID) -> dict[str, int]:
        counts = dict.fromkeys(TASK_STATUSES, 0)
        async with self._session_factory() as session:
            rows = await session.execute(
                select(models.PlanTask.status, func.count())
                .where(models.PlanTask.plan_id == plan_id)
                .group_by(models.PlanTask.status)
            )
            for status, count in rows.all():
                if status in counts:
                    counts[status] = count
        return counts

    async def list_dirty(self, plan_id: UUID) -> builtins.list[PlanTask]:
        async with self._session_factory() as session:
            rows = await session.scalars(
                select(models.PlanTask)
                .where(models.PlanTask.plan_id == plan_id, _dirty_clause())
                .order_by(models.PlanTask.start_at, models.PlanTask.sort_order)
            )
            return [_to_entity(row) for row in rows]

    def _add(self, session: AsyncSession, plan_id: UUID, tasks: Sequence[NewPlanTask]) -> None:
        session.add_all([models.PlanTask(plan_id=plan_id, **task.model_dump()) for task in tasks])
