"""PostgreSQL repos for intake: `imports`, `documents` and `profiles`."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from packages.repo import models
from packages.repo.entities import Document, Import, Profile

__all__ = ["PgDocumentRepo", "PgImportRepo", "PgProfileRepo"]


def _import(row: models.Import) -> Import:
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


def _document(row: models.Document) -> Document:
    return Document(
        id=row.id,
        import_id=row.import_id,
        events=row.events,
        text_chunks=row.text_chunks,
        created_at=row.created_at,
    )


def _profile(row: models.Profile) -> Profile:
    return Profile(
        user_id=row.user_id,
        timezone=row.timezone,
        signals=row.signals,
        coverage=row.coverage,
        source_import_ids=[UUID(value) for value in row.source_import_ids],
        updated_at=row.updated_at,
    )


class _Repo:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory


class PgImportRepo(_Repo):
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
            )
            session.add(row)
            await session.flush()
            await session.refresh(row)
            entity = _import(row)
            await session.commit()
            return entity

    async def get(self, user_id: UUID, import_id: UUID) -> Import | None:
        async with self._session_factory() as session:
            row = await session.scalar(
                select(models.Import).where(
                    models.Import.id == import_id, models.Import.user_id == user_id
                )
            )
            return _import(row) if row is not None else None

    async def get_unscoped(self, import_id: UUID) -> Import | None:
        async with self._session_factory() as session:
            row = await session.get(models.Import, import_id)
            return _import(row) if row is not None else None

    async def list_for_user(self, user_id: UUID) -> list[Import]:
        async with self._session_factory() as session:
            rows = await session.scalars(
                select(models.Import)
                .where(models.Import.user_id == user_id)
                .order_by(models.Import.created_at.desc())
            )
            return [_import(row) for row in rows]

    async def set_status(self, import_id: UUID, status: str, error: str | None = None) -> None:
        async with self._session_factory() as session:
            await session.execute(
                update(models.Import)
                .where(models.Import.id == import_id)
                .values(status=status, error=error)
            )
            await session.commit()


class PgDocumentRepo(_Repo):
    async def create(
        self, import_id: UUID, events: list[dict[str, Any]], text_chunks: list[dict[str, Any]]
    ) -> Document:
        async with self._session_factory() as session:
            row = models.Document(import_id=import_id, events=events, text_chunks=text_chunks)
            session.add(row)
            await session.flush()
            await session.refresh(row)
            entity = _document(row)
            await session.commit()
            return entity

    async def get_by_import(self, import_id: UUID) -> Document | None:
        async with self._session_factory() as session:
            row = await session.scalar(
                select(models.Document).where(models.Document.import_id == import_id)
            )
            return _document(row) if row is not None else None

    async def list_by_imports(self, import_ids: Sequence[UUID]) -> list[Document]:
        if not import_ids:
            return []
        async with self._session_factory() as session:
            rows = await session.scalars(
                select(models.Document)
                .where(models.Document.import_id.in_(list(import_ids)))
                .order_by(models.Document.created_at)
            )
            return [_document(row) for row in rows]


class PgProfileRepo(_Repo):
    async def get(self, user_id: UUID) -> Profile | None:
        async with self._session_factory() as session:
            row = await session.get(models.Profile, user_id)
            return _profile(row) if row is not None else None

    async def upsert(
        self,
        user_id: UUID,
        timezone: str,
        signals: dict[str, Any],
        coverage: dict[str, Any],
        source_import_ids: Sequence[UUID],
    ) -> Profile:
        async with self._session_factory() as session:
            row = await self._row(session, user_id)
            row.timezone = timezone
            row.signals = signals
            row.coverage = coverage
            row.source_import_ids = [str(value) for value in source_import_ids]
            await session.flush()
            await session.refresh(row)
            entity = _profile(row)
            await session.commit()
            return entity

    async def set_timezone(self, user_id: UUID, timezone: str) -> Profile:
        async with self._session_factory() as session:
            row = await self._row(session, user_id)
            row.timezone = timezone
            await session.flush()
            await session.refresh(row)
            entity = _profile(row)
            await session.commit()
            return entity

    async def _row(self, session: AsyncSession, user_id: UUID) -> models.Profile:
        row = await session.get(models.Profile, user_id)
        if row is None:
            row = models.Profile(user_id=user_id)
            session.add(row)
        return row
