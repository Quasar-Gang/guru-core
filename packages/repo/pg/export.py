"""PgPlanExportRepo — plan_exports 表的 PostgreSQL 實作。"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from packages.repo import models
from packages.repo.entities import PlanExport


def _to_entity(row: models.PlanExport) -> PlanExport:
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


class PgPlanExportRepo:
    """PlanExportRepo 的 PostgreSQL 實作，以 (plan_id, target) 為唯一鍵。"""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def get(self, plan_id: UUID, target: str) -> PlanExport | None:
        async with self._session_factory() as session:
            row = await self._find(session, plan_id, target)
            return _to_entity(row) if row is not None else None

    async def list_for_plan(self, plan_id: UUID) -> list[PlanExport]:
        async with self._session_factory() as session:
            rows = await session.scalars(
                select(models.PlanExport)
                .where(models.PlanExport.plan_id == plan_id)
                .order_by(models.PlanExport.created_at, models.PlanExport.target)
            )
            return [_to_entity(row) for row in rows]

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
            row = await self._find(session, plan_id, target)
            if row is None:
                row = models.PlanExport(
                    plan_id=plan_id,
                    target=target,
                    status=status,
                    external_calendar_id=external_calendar_id,
                    last_synced_at=last_synced_at,
                    error=error,
                )
                session.add(row)
            else:
                row.status = status
                row.external_calendar_id = external_calendar_id
                row.last_synced_at = last_synced_at
                row.error = error
            await session.flush()
            await session.refresh(row)
            entity = _to_entity(row)
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

    async def _find(
        self, session: AsyncSession, plan_id: UUID, target: str
    ) -> models.PlanExport | None:
        row: models.PlanExport | None = await session.scalar(
            select(models.PlanExport).where(
                models.PlanExport.plan_id == plan_id, models.PlanExport.target == target
            )
        )
        return row
