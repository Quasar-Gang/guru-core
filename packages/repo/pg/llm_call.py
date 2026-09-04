"""PgLlmCallRepo — llm_calls 表的 PostgreSQL 實作（僅追加）。"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from packages.repo import models
from packages.repo.entities import LlmCallLog


class PgLlmCallRepo:
    """LlmCallRepo 的 PostgreSQL 實作。"""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def record(self, log: LlmCallLog) -> None:
        async with self._session_factory() as session:
            session.add(models.LlmCall(**log.model_dump()))
            await session.commit()
