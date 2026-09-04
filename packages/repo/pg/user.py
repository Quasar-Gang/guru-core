"""PgUserRepo — PostgreSQL implementation of the users table."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from packages.repo import models
from packages.repo.entities import User


def _to_entity(row: models.User) -> User:
    return User(
        id=row.id,
        email=row.email,
        google_sub=row.google_sub,
        created_at=row.created_at,
    )


class PgUserRepo:
    """PostgreSQL UserRepo."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def get_by_google_sub(self, google_sub: str) -> User | None:
        async with self._session_factory() as session:
            row = await session.scalar(
                select(models.User).where(models.User.google_sub == google_sub)
            )
            return _to_entity(row) if row is not None else None

    async def get(self, user_id: UUID) -> User | None:
        async with self._session_factory() as session:
            row = await session.get(models.User, user_id)
            return _to_entity(row) if row is not None else None

    async def create(self, email: str, google_sub: str) -> User:
        async with self._session_factory() as session:
            row = models.User(email=email, google_sub=google_sub)
            session.add(row)
            await session.flush()
            await session.refresh(row)
            entity = _to_entity(row)
            await session.commit()
            return entity
