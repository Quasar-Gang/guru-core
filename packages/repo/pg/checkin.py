"""PgCheckinRepo — checkins 表的 PostgreSQL 實作。"""

from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from packages.repo import models
from packages.repo.entities import Checkin


def _to_entity(row: models.Checkin) -> Checkin:
    return Checkin(
        id=row.id,
        plan_id=row.plan_id,
        checkin_date=row.checkin_date,
        task_results=list(row.task_results),
        note=row.note,
        created_at=row.created_at,
    )


class PgCheckinRepo:
    """CheckinRepo 的 PostgreSQL 實作，以 (plan_id, checkin_date) 為唯一鍵。"""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

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
                row = models.Checkin(
                    plan_id=plan_id,
                    checkin_date=checkin_date,
                    task_results=list(task_results),
                    note=note,
                )
                session.add(row)
            else:
                row.task_results = list(task_results)
                row.note = note
            await session.flush()
            await session.refresh(row)
            entity = _to_entity(row)
            await session.commit()
            return entity

    async def list_for_plan(self, plan_id: UUID) -> list[Checkin]:
        async with self._session_factory() as session:
            rows = await session.scalars(
                select(models.Checkin)
                .where(models.Checkin.plan_id == plan_id)
                .order_by(models.Checkin.checkin_date)
            )
            return [_to_entity(row) for row in rows]
