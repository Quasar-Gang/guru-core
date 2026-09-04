"""InMemorySource — SourcePort implementation for tests."""

from packages.importers.ports import RawBlob


class InMemorySource:
    """Return the blob supplied at construction time."""

    def __init__(self, blob: RawBlob) -> None:
        self._blob = blob

    async def fetch(self) -> RawBlob:
        return self._blob
