"""Reading a user's uploads back as one `Document`.

Every use case downstream of intake wants the same thing: everything the user has uploaded,
merged, with the imports it came from. Doing that in one place keeps the merge order — and
therefore the event references the model is given — identical across the pipeline.
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from packages.importers.document import DocEvent, Document, TextChunk
from packages.repo.ports import DocumentRepo, ImportRepo

__all__ = ["Uploads", "event_ref", "load_uploads"]

#: An import only counts once the parser has written its Document.
_PARSED = "parsed"


class Uploads(BaseModel):
    """Everything a user has uploaded, as one Document plus its provenance."""

    model_config = ConfigDict(extra="forbid")

    document: Document
    import_ids: list[UUID]
    sources: list[str]


def event_ref(index: int, event: DocEvent) -> str:
    """The identity an event is given in a prompt, and the one it must come back with.

    Stable across a run because `load_uploads` always merges in the same order.
    """
    return event.source_ref or f"e{index}"


async def load_uploads(imports: ImportRepo, documents: DocumentRepo, user_id: UUID) -> Uploads:
    """Merge every parsed upload of this user, oldest import first."""
    parsed = [
        item for item in reversed(await imports.list_for_user(user_id)) if item.status == _PARSED
    ]
    rows = await documents.list_by_imports([item.id for item in parsed])
    by_import = {row.import_id: row for row in rows}

    merged = Document()
    used: list[UUID] = []
    sources: list[str] = []
    for item in parsed:
        row = by_import.get(item.id)
        if row is None:
            continue
        merged = merged.merge(
            Document(
                events=[DocEvent.model_validate(event) for event in row.events],
                text_chunks=[TextChunk.model_validate(chunk) for chunk in row.text_chunks],
            )
        )
        used.append(item.id)
        sources.append(item.source)
    return Uploads(document=merged, import_ids=used, sources=_unique(sources))


def _unique(values: Sequence[str]) -> list[str]:
    seen: list[str] = []
    for value in values:
        if value not in seen:
            seen.append(value)
    return seen
