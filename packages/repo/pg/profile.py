"""PgProfileRepo — PostgreSQL implementation of the profiles table."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from packages.repo import models
from packages.repo.entities import Profile


def _to_entity(row: models.Profile) -> Profile:
    return Profile(
        user_id=row.user_id,
        answers=dict(row.answers),
        timezone=row.timezone,
        updated_at=row.updated_at,
    )


class PgProfileRepo:
    """PostgreSQL ProfileRepo."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def get(self, user_id: UUID) -> Profile | None:
        async with self._session_factory() as session:
            row = await session.get(models.Profile, user_id)
            return _to_entity(row) if row is not None else None

    async def upsert(self, user_id: UUID, answers: dict[str, Any], timezone: str) -> Profile:
        async with self._session_factory() as session:
            row = await session.get(models.Profile, user_id)
            if row is None:
                row = models.Profile(user_id=user_id, answers=dict(answers), timezone=timezone)
                session.add(row)
            else:
                row.answers = dict(answers)
                row.timezone = timezone
            await session.flush()
            await session.refresh(row)
            entity = _to_entity(row)
            await session.commit()
            return entity
