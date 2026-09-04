"""PgLlmCallRepo — PostgreSQL implementation of the append-only llm_calls table."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from packages.repo import models
from packages.repo.entities import LlmCallLog


class PgLlmCallRepo:
    """PostgreSQL LlmCallRepo."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def record(self, log: LlmCallLog) -> None:
        async with self._session_factory() as session:
            session.add(models.LlmCall(**log.model_dump()))
            await session.commit()
