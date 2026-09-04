"""PgImportRepo — imports 表的 PostgreSQL 實作。"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from packages.repo import models
from packages.repo.entities import Import


def _to_entity(row: models.Import) -> Import:
    return Import(
        id=row.id,
        user_id=row.user_id,
        source=row.source,
        format=row.format,
        storage_key=row.storage_key,
        filename=row.filename,
        status=row.status,
        error=row.error,
        created_at=row.created_at,
    )


class PgImportRepo:
    """ImportRepo 的 PostgreSQL 實作。"""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def create(
        self, user_id: UUID, source: str, format: str, storage_key: str, filename: str
    ) -> Import:
        async with self._session_factory() as session:
            row = models.Import(
                user_id=user_id,
                source=source,
                format=format,
                storage_key=storage_key,
                filename=filename,
                status="pending",
            )
            session.add(row)
            await session.flush()
            await session.refresh(row)
            entity = _to_entity(row)
            await session.commit()
            return entity

    async def get(self, user_id: UUID, import_id: UUID) -> Import | None:
        async with self._session_factory() as session:
            row = await session.scalar(
                select(models.Import).where(
                    models.Import.id == import_id, models.Import.user_id == user_id
                )
            )
            return _to_entity(row) if row is not None else None

    async def get_unscoped(self, import_id: UUID) -> Import | None:
        async with self._session_factory() as session:
            row = await session.get(models.Import, import_id)
            return _to_entity(row) if row is not None else None

    async def list_for_user(self, user_id: UUID) -> list[Import]:
        async with self._session_factory() as session:
            rows = await session.scalars(
                select(models.Import)
                .where(models.Import.user_id == user_id)
                .order_by(models.Import.created_at, models.Import.id)
            )
            return [_to_entity(row) for row in rows]

    async def set_status(self, import_id: UUID, status: str, error: str | None = None) -> None:
        async with self._session_factory() as session:
            await session.execute(
                update(models.Import)
                .where(models.Import.id == import_id)
                .values(status=status, error=error)
            )
            await session.commit()
