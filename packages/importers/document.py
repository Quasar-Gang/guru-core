"""Document — the only import format the Plan Engine understands."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class DocEvent(BaseModel):
    """An event with an explicit time range."""

    title: str
    start_at: datetime
    end_at: datetime
    all_day: bool = False
    location: str | None = None
    source_ref: str | None = None


class TextChunk(BaseModel):
    """A block of text carrying no time information."""

    text: str
    section: str | None = None
    order: int = 0


class Document(BaseModel):
    """The unified result of parsing one or more import sources."""

    events: list[DocEvent] = Field(default_factory=list)
    text_chunks: list[TextChunk] = Field(default_factory=list)

    def merge(self, other: Document) -> Document:
        """Return a new merged Document, leaving both self and other untouched.

        The text chunks of `other` are renumbered to continue from self's highest order.
        """
        offset = max((c.order for c in self.text_chunks), default=-1) + 1
        return Document(
            events=[*self.events, *other.events],
            text_chunks=[
                *self.text_chunks,
                *(c.model_copy(update={"order": c.order + offset}) for c in other.text_chunks),
            ],
        )
