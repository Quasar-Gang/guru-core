"""List a user's imports, and the shared view model every import endpoint returns."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from packages.repo import DocumentRepo, ImportRepo
from packages.repo.entities import Document, Import

__all__ = ["ImportView", "ListImports", "to_view"]


class ImportView(BaseModel):
    """One import as seen by the API client."""

    id: UUID
    source: str
    format: str
    filename: str
    status: str
    error: str | None
    created_at: datetime
    event_count: int = 0
    chunk_count: int = 0


def to_view(record: Import, document: Document | None) -> ImportView:
    """Build a view; counts stay at zero until the parse worker has written a document."""
    return ImportView(
        id=record.id,
        source=record.source,
        format=record.format,
        filename=record.filename,
        status=record.status,
        error=record.error,
        created_at=record.created_at,
        event_count=len(document.events) if document is not None else 0,
        chunk_count=len(document.text_chunks) if document is not None else 0,
    )


class ListImports:
    """Every import belonging to one user, newest first."""

    def __init__(self, imports: ImportRepo, documents: DocumentRepo) -> None:
        self._imports = imports
        self._documents = documents

    async def __call__(self, user_id: UUID) -> list[ImportView]:
        records = await self._imports.list_for_user(user_id)
        documents = await self._documents.list_by_imports([r.id for r in records])
        by_import = {d.import_id: d for d in documents}
        return [to_view(r, by_import.get(r.id)) for r in records]
