"""PgDocumentRepo — PostgreSQL implementation of the documents table."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from packages.repo import models
from packages.repo.entities import Document


def _to_entity(row: models.Document) -> Document:
    return Document(
        id=row.id,
        import_id=row.import_id,
        events=list(row.events),
        text_chunks=list(row.text_chunks),
        created_at=row.created_at,
    )


class PgDocumentRepo:
    """PostgreSQL DocumentRepo, keyed uniquely by import_id."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def create(
        self, import_id: UUID, events: list[dict[str, Any]], text_chunks: list[dict[str, Any]]
    ) -> Document:
        async with self._session_factory() as session:
            row = models.Document(
                import_id=import_id, events=list(events), text_chunks=list(text_chunks)
            )
            session.add(row)
            await session.flush()
            await session.refresh(row)
            entity = _to_entity(row)
            await session.commit()
            return entity

    async def get_by_import(self, import_id: UUID) -> Document | None:
        async with self._session_factory() as session:
            row = await session.scalar(
                select(models.Document).where(models.Document.import_id == import_id)
            )
            return _to_entity(row) if row is not None else None

    async def list_by_imports(self, import_ids: Sequence[UUID]) -> list[Document]:
        if not import_ids:
            return []
        async with self._session_factory() as session:
            rows = await session.scalars(
                select(models.Document).where(models.Document.import_id.in_(list(import_ids)))
            )
            by_import = {row.import_id: _to_entity(row) for row in rows}
        return [by_import[i] for i in import_ids if i in by_import]
