"""Import-related port interfaces and shared types."""

from typing import Protocol

from pydantic import BaseModel

from packages.importers.document import Document


class RawBlob(BaseModel):
    """Unparsed raw bytes together with their metadata."""

    data: bytes
    content_type: str
    filename: str


class UnsupportedFormat(ValueError):
    """Raised when the format cannot be detected or no parser supports it."""


class SourcePort(Protocol):
    """Port for fetching raw import data."""

    async def fetch(self) -> RawBlob: ...


class ParserPort(Protocol):
    """Port for parsing a RawBlob into a Document."""

    def supports(self, fmt: str) -> bool: ...

    def parse(self, blob: RawBlob) -> Document: ...
