"""PgPlanRevisionRepo — PostgreSQL implementation of the plan_revisions table."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from packages.repo import models
from packages.repo.entities import PlanRevision

OPEN_STATUSES = ("pending", "proposed")


def _to_entity(row: models.PlanRevision) -> PlanRevision:
    return PlanRevision(
        id=row.id,
        plan_id=row.plan_id,
        trigger=row.trigger,
        strategy=row.strategy,
        trigger_detail=dict(row.trigger_detail) if row.trigger_detail is not None else None,
        proposed_tasks=list(row.proposed_tasks) if row.proposed_tasks is not None else None,
        diff=list(row.diff) if row.diff is not None else None,
        rationale=row.rationale,
        status=row.status,
        created_at=row.created_at,
        decided_at=row.decided_at,
    )


class PgPlanRevisionRepo:
    """PostgreSQL PlanRevisionRepo."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def create(self, plan_id: UUID, strategy: str, note: str | None) -> PlanRevision:
        async with self._session_factory() as session:
            row = models.PlanRevision(
                plan_id=plan_id,
                trigger="manual",
                strategy=strategy,
                rationale=note,
                status="pending",
            )
            session.add(row)
            await session.flush()
            await session.refresh(row)
            entity = _to_entity(row)
            await session.commit()
            return entity

    async def get(self, plan_id: UUID, revision_id: UUID) -> PlanRevision | None:
        async with self._session_factory() as session:
            row = await session.scalar(
                select(models.PlanRevision).where(
                    models.PlanRevision.id == revision_id,
                    models.PlanRevision.plan_id == plan_id,
                )
            )
            return _to_entity(row) if row is not None else None

    async def get_unscoped(self, revision_id: UUID) -> PlanRevision | None:
        async with self._session_factory() as session:
            row = await session.get(models.PlanRevision, revision_id)
            return _to_entity(row) if row is not None else None

    async def list_for_plan(self, plan_id: UUID) -> list[PlanRevision]:
        async with self._session_factory() as session:
            rows = await session.scalars(
                select(models.PlanRevision)
                .where(models.PlanRevision.plan_id == plan_id)
                .order_by(models.PlanRevision.created_at, models.PlanRevision.id)
            )
            return [_to_entity(row) for row in rows]

    async def has_open(self, plan_id: UUID) -> bool:
        async with self._session_factory() as session:
            found = await session.scalar(
                select(models.PlanRevision.id)
                .where(
                    models.PlanRevision.plan_id == plan_id,
                    models.PlanRevision.status.in_(OPEN_STATUSES),
                )
                .limit(1)
            )
            return found is not None

    async def set_proposal(
        self,
        revision_id: UUID,
        proposed_tasks: list[dict[str, Any]],
        diff: list[dict[str, Any]],
        rationale: str,
    ) -> None:
        await self._update(
            revision_id,
            {
                "proposed_tasks": list(proposed_tasks),
                "diff": list(diff),
                "rationale": rationale,
            },
        )

    async def set_status(self, revision_id: UUID, status: str, decided_at: datetime | None) -> None:
        await self._update(revision_id, {"status": status, "decided_at": decided_at})

    async def _update(self, revision_id: UUID, fields: dict[str, Any]) -> None:
        async with self._session_factory() as session:
            row = await session.get(models.PlanRevision, revision_id)
            if row is None:
                raise KeyError(revision_id)
            for key, value in fields.items():
                setattr(row, key, value)
            await session.commit()
