"""InMemoryDocumentRepo — 測試用的記憶體實作。"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from packages.repo.entities import Document


class InMemoryDocumentRepo:
    """把 documents 放在記憶體中，以 import_id 為唯一鍵。"""

    def __init__(self) -> None:
        self._documents: dict[UUID, Document] = {}

    async def create(
        self, import_id: UUID, events: list[dict[str, Any]], text_chunks: list[dict[str, Any]]
    ) -> Document:
        document = Document(
            id=uuid.uuid4(),
            import_id=import_id,
            events=list(events),
            text_chunks=list(text_chunks),
            created_at=datetime.now(UTC),
        )
        self._documents[import_id] = document
        return document

    async def get_by_import(self, import_id: UUID) -> Document | None:
        return self._documents.get(import_id)

    async def list_by_imports(self, import_ids: Sequence[UUID]) -> list[Document]:
        return [self._documents[i] for i in import_ids if i in self._documents]
