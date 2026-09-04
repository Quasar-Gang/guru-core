"""PgPlanRepo — PostgreSQL implementation of the plans table."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from packages.repo import models
from packages.repo.entities import NewPlan, Plan


def _to_entity(row: models.Plan) -> Plan:
    return Plan(
        id=row.id,
        user_id=row.user_id,
        session_id=row.session_id,
        title=row.title,
        difficulty=row.difficulty,
        status=row.status,
        goal_statement=row.goal_statement,
        duration_weeks=row.duration_weeks,
        start_date=row.start_date,
        deadline=row.deadline,
        template=dict(row.template),
        structure=dict(row.structure),
        activated_at=row.activated_at,
        archived_at=row.archived_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class PgPlanRepo:
    """PostgreSQL PlanRepo."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def create_many(self, plans: Sequence[NewPlan]) -> list[Plan]:
        if not plans:
            return []
        async with self._session_factory() as session:
            rows = [models.Plan(**new_plan.model_dump()) for new_plan in plans]
            session.add_all(rows)
            await session.flush()
            for row in rows:
                await session.refresh(row)
            created = [_to_entity(row) for row in rows]
            await session.commit()
            return created

    async def get(self, user_id: UUID, plan_id: UUID) -> Plan | None:
        async with self._session_factory() as session:
            row = await session.scalar(
                select(models.Plan).where(models.Plan.id == plan_id, models.Plan.user_id == user_id)
            )
            return _to_entity(row) if row is not None else None

    async def get_unscoped(self, plan_id: UUID) -> Plan | None:
        async with self._session_factory() as session:
            row = await session.get(models.Plan, plan_id)
            return _to_entity(row) if row is not None else None

    async def list_for_user(self, user_id: UUID, status: str | None) -> list[Plan]:
        stmt = select(models.Plan).where(models.Plan.user_id == user_id)
        if status is not None:
            stmt = stmt.where(models.Plan.status == status)
        stmt = stmt.order_by(models.Plan.created_at, models.Plan.id)
        async with self._session_factory() as session:
            rows = await session.scalars(stmt)
            return [_to_entity(row) for row in rows]

    async def list_for_session(self, session_id: UUID) -> list[Plan]:
        async with self._session_factory() as session:
            rows = await session.scalars(
                select(models.Plan)
                .where(models.Plan.session_id == session_id)
                .order_by(models.Plan.created_at, models.Plan.id)
            )
            return [_to_entity(row) for row in rows]

    async def update_fields(self, plan_id: UUID, **fields: Any) -> Plan:
        async with self._session_factory() as session:
            row = await session.get(models.Plan, plan_id)
            if row is None:
                raise KeyError(plan_id)
            for key, value in fields.items():
                setattr(row, key, value)
            await session.flush()
            await session.refresh(row)
            entity = _to_entity(row)
            await session.commit()
            return entity

    async def set_status_for_session(
        self, session_id: UUID, status: str, exclude_plan_id: UUID
    ) -> None:
        async with self._session_factory() as session:
            await session.execute(
                update(models.Plan)
                .where(
                    models.Plan.session_id == session_id,
                    models.Plan.id != exclude_plan_id,
                )
                .values(status=status, updated_at=func.now())
            )
            await session.commit()

    async def delete(self, plan_id: UUID) -> None:
        async with self._session_factory() as session:
            await session.execute(delete(models.Plan).where(models.Plan.id == plan_id))
            await session.commit()
