"""PostgreSQL repo for Station 3: `reconciliations`."""

from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from packages.repo import models
from packages.repo.entities import Reconciliation

__all__ = ["PgReconciliationRepo"]


def _reconciliation(row: models.Reconciliation) -> Reconciliation:
    return Reconciliation(
        id=row.id,
        user_id=row.user_id,
        hypothesis_id=row.hypothesis_id,
        status=row.status,
        period_start=row.period_start,
        period_end=row.period_end,
        comparison=row.comparison,
        narrative=row.narrative,
        outcome=row.outcome,
        revision_kind=row.revision_kind,
        error=row.error,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class PgReconciliationRepo:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def create(
        self, user_id: UUID, hypothesis_id: UUID, period_start: date, period_end: date
    ) -> Reconciliation:
        async with self._session_factory() as session:
            row = models.Reconciliation(
                user_id=user_id,
                hypothesis_id=hypothesis_id,
                period_start=period_start,
                period_end=period_end,
            )
            session.add(row)
            await session.flush()
            entity = _reconciliation(row)
            await session.commit()
            return entity

    async def get(self, user_id: UUID, reconciliation_id: UUID) -> Reconciliation | None:
        async with self._session_factory() as session:
            row = await session.scalar(
                select(models.Reconciliation).where(
                    models.Reconciliation.id == reconciliation_id,
                    models.Reconciliation.user_id == user_id,
                )
            )
            return _reconciliation(row) if row is not None else None

    async def get_unscoped(self, reconciliation_id: UUID) -> Reconciliation | None:
        async with self._session_factory() as session:
            row = await session.get(models.Reconciliation, reconciliation_id)
            return _reconciliation(row) if row is not None else None

    async def list_for_hypothesis(self, hypothesis_id: UUID) -> list[Reconciliation]:
        async with self._session_factory() as session:
            rows = await session.scalars(
                select(models.Reconciliation)
                .where(models.Reconciliation.hypothesis_id == hypothesis_id)
                .order_by(models.Reconciliation.created_at)
            )
            return [_reconciliation(row) for row in rows]

    async def complete(
        self,
        reconciliation_id: UUID,
        comparison: dict[str, Any],
        narrative: str,
        revision_kind: str | None,
    ) -> None:
        async with self._session_factory() as session:
            await session.execute(
                update(models.Reconciliation)
                .where(models.Reconciliation.id == reconciliation_id)
                .values(
                    status="done",
                    comparison=comparison,
                    narrative=narrative,
                    revision_kind=revision_kind,
                    error=None,
                )
            )
            await session.commit()

    async def decide(self, reconciliation_id: UUID, outcome: str) -> None:
        async with self._session_factory() as session:
            await session.execute(
                update(models.Reconciliation)
                .where(models.Reconciliation.id == reconciliation_id)
                .values(outcome=outcome)
            )
            await session.commit()

    async def fail(self, reconciliation_id: UUID, error: str) -> None:
        async with self._session_factory() as session:
            await session.execute(
                update(models.Reconciliation)
                .where(models.Reconciliation.id == reconciliation_id)
                .values(status="failed", error=error)
            )
            await session.commit()
