"""InMemorySource — 測試用的 SourcePort 實作。"""

from packages.importers.ports import RawBlob


class InMemorySource:
    """直接回傳建構時給定的 blob。"""

    def __init__(self, blob: RawBlob) -> None:
        self._blob = blob

    async def fetch(self) -> RawBlob:
        return self._blob
