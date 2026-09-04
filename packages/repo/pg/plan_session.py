"""PgPlanSessionRepo — plan_sessions 表的 PostgreSQL 實作。

`import_ids` 在 entity 是 `list[UUID]`，在 ORM 是 JSONB 的 `list[str]`：寫入時序列化成字串、
讀取時轉回 UUID。
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from packages.repo import models
from packages.repo.entities import PlanSession


def _to_entity(row: models.PlanSession) -> PlanSession:
    return PlanSession(
        id=row.id,
        user_id=row.user_id,
        trait_role_model_id=row.trait_role_model_id,
        persona_role_model_id=row.persona_role_model_id,
        goal=row.goal,
        intake=dict(row.intake),
        import_ids=[UUID(i) for i in row.import_ids],
        use_calendar=row.use_calendar,
        status=row.status,
        round=row.round,
        context_snapshot=dict(row.context_snapshot) if row.context_snapshot is not None else None,
        error=row.error,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class PgPlanSessionRepo:
    """PlanSessionRepo 的 PostgreSQL 實作。"""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def create(
        self,
        user_id: UUID,
        goal: str,
        intake: dict[str, Any],
        import_ids: list[UUID],
        use_calendar: bool,
        trait_role_model_id: UUID | None,
        persona_role_model_id: UUID | None,
    ) -> PlanSession:
        async with self._session_factory() as session:
            row = models.PlanSession(
                user_id=user_id,
                trait_role_model_id=trait_role_model_id,
                persona_role_model_id=persona_role_model_id,
                goal=goal,
                intake=dict(intake),
                import_ids=[str(i) for i in import_ids],
                use_calendar=use_calendar,
                status="collecting",
                round=0,
            )
            session.add(row)
            await session.flush()
            await session.refresh(row)
            entity = _to_entity(row)
            await session.commit()
            return entity

    async def get(self, user_id: UUID, session_id: UUID) -> PlanSession | None:
        async with self._session_factory() as session:
            row = await session.scalar(
                select(models.PlanSession).where(
                    models.PlanSession.id == session_id,
                    models.PlanSession.user_id == user_id,
                )
            )
            return _to_entity(row) if row is not None else None

    async def get_unscoped(self, session_id: UUID) -> PlanSession | None:
        async with self._session_factory() as session:
            row = await session.get(models.PlanSession, session_id)
            return _to_entity(row) if row is not None else None

    async def set_status(self, session_id: UUID, status: str, error: str | None = None) -> None:
        await self._update(session_id, {"status": status, "error": error})

    async def bump_round(self, session_id: UUID) -> int:
        async with self._session_factory() as session:
            row = await session.get(models.PlanSession, session_id)
            if row is None:
                raise KeyError(session_id)
            row.round = row.round + 1
            next_round = row.round
            await session.commit()
            return next_round

    async def set_context_snapshot(self, session_id: UUID, snapshot: dict[str, Any]) -> None:
        await self._update(session_id, {"context_snapshot": dict(snapshot)})

    async def _update(self, session_id: UUID, fields: dict[str, Any]) -> None:
        async with self._session_factory() as session:
            row = await session.get(models.PlanSession, session_id)
            if row is None:
                raise KeyError(session_id)
            for key, value in fields.items():
                setattr(row, key, value)
            await session.commit()
