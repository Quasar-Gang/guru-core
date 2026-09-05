"""In-memory repos for intake: imports, documents and the single Profile per user."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from uuid import UUID, uuid4

from packages.repo.entities import Document, Import, Profile
from packages.repo.memory.identity import now

__all__ = ["InMemoryDocumentRepo", "InMemoryImportRepo", "InMemoryProfileRepo"]


class InMemoryImportRepo:
    def __init__(self) -> None:
        self._rows: dict[UUID, Import] = {}

    async def create(
        self, user_id: UUID, source: str, format: str, storage_key: str, filename: str
    ) -> Import:
        row = Import(
            id=uuid4(),
            user_id=user_id,
            source=source,
            format=format,
            storage_key=storage_key,
            filename=filename,
            status="pending",
            error=None,
            created_at=now(),
        )
        self._rows[row.id] = row
        return row

    async def get(self, user_id: UUID, import_id: UUID) -> Import | None:
        row = self._rows.get(import_id)
        return row if row is not None and row.user_id == user_id else None

    async def get_unscoped(self, import_id: UUID) -> Import | None:
        return self._rows.get(import_id)

    async def list_for_user(self, user_id: UUID) -> list[Import]:
        rows = [row for row in self._rows.values() if row.user_id == user_id]
        return sorted(rows, key=lambda row: row.created_at, reverse=True)

    async def set_status(self, import_id: UUID, status: str, error: str | None = None) -> None:
        row = self._rows.get(import_id)
        if row is not None:
            self._rows[import_id] = row.model_copy(update={"status": status, "error": error})


class InMemoryDocumentRepo:
    def __init__(self) -> None:
        self._rows: dict[UUID, Document] = {}

    async def create(
        self, import_id: UUID, events: list[dict[str, Any]], text_chunks: list[dict[str, Any]]
    ) -> Document:
        row = Document(
            id=uuid4(),
            import_id=import_id,
            events=events,
            text_chunks=text_chunks,
            created_at=now(),
        )
        self._rows[row.id] = row
        return row

    async def get_by_import(self, import_id: UUID) -> Document | None:
        return next((row for row in self._rows.values() if row.import_id == import_id), None)

    async def list_by_imports(self, import_ids: Sequence[UUID]) -> list[Document]:
        wanted = set(import_ids)
        rows = [row for row in self._rows.values() if row.import_id in wanted]
        return sorted(rows, key=lambda row: row.created_at)


class InMemoryProfileRepo:
    def __init__(self) -> None:
        self._rows: dict[UUID, Profile] = {}

    async def get(self, user_id: UUID) -> Profile | None:
        return self._rows.get(user_id)

    async def upsert(
        self,
        user_id: UUID,
        timezone: str,
        signals: dict[str, Any],
        coverage: dict[str, Any],
        source_import_ids: Sequence[UUID],
    ) -> Profile:
        row = Profile(
            user_id=user_id,
            timezone=timezone,
            signals=signals,
            coverage=coverage,
            source_import_ids=list(source_import_ids),
            updated_at=now(),
        )
        self._rows[user_id] = row
        return row

    async def set_timezone(self, user_id: UUID, timezone: str) -> Profile:
        existing = self._rows.get(user_id)
        row = (
            existing.model_copy(update={"timezone": timezone, "updated_at": now()})
            if existing is not None
            else Profile(
                user_id=user_id,
                timezone=timezone,
                signals={},
                coverage={},
                source_import_ids=[],
                updated_at=now(),
            )
        )
        self._rows[user_id] = row
        return row
