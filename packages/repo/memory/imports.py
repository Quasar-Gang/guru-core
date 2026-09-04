"""InMemoryImportRepo — in-memory implementation for tests."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from uuid import UUID

from packages.repo.entities import Import


class InMemoryImportRepo:
    """ImportRepo implementation that keeps imports in process memory."""

    def __init__(self) -> None:
        self._imports: dict[UUID, Import] = {}

    async def create(
        self, user_id: UUID, source: str, format: str, storage_key: str, filename: str
    ) -> Import:
        record = Import(
            id=uuid.uuid4(),
            user_id=user_id,
            source=source,
            format=format,
            storage_key=storage_key,
            filename=filename,
            status="pending",
            error=None,
            created_at=datetime.now(UTC),
        )
        self._imports[record.id] = record
        return record

    async def get(self, user_id: UUID, import_id: UUID) -> Import | None:
        record = self._imports.get(import_id)
        return record if record is not None and record.user_id == user_id else None

    async def get_unscoped(self, import_id: UUID) -> Import | None:
        return self._imports.get(import_id)

    async def list_for_user(self, user_id: UUID) -> list[Import]:
        return [i for i in self._imports.values() if i.user_id == user_id]

    async def set_status(self, import_id: UUID, status: str, error: str | None = None) -> None:
        record = self._imports.get(import_id)
        if record is not None:
            self._imports[import_id] = record.model_copy(update={"status": status, "error": error})
