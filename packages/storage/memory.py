"""InMemoryStorage — in-memory implementation for tests."""

from datetime import UTC, datetime

from packages.storage.ports import ObjectNotFound, StoredObject


class InMemoryStorage:
    """StoragePort implementation that keeps objects in process memory."""

    def __init__(self) -> None:
        self._objects: dict[str, tuple[bytes, str]] = {}

    async def put(self, key: str, data: bytes, content_type: str) -> StoredObject:
        self._objects[key] = (data, content_type)
        return StoredObject(key=key, size=len(data), content_type=content_type)

    async def get(self, key: str) -> bytes:
        try:
            return self._objects[key][0]
        except KeyError as exc:
            raise ObjectNotFound(key) from exc

    async def delete(self, key: str) -> None:
        self._objects.pop(key, None)

    async def exists(self, key: str) -> bool:
        return key in self._objects

    async def presign_put(self, key: str, content_type: str, expires_in: int) -> str:
        return self._presign("put", key, expires_in)

    async def presign_get(self, key: str, expires_in: int) -> str:
        return self._presign("get", key, expires_in)

    @staticmethod
    def _presign(op: str, key: str, expires_in: int) -> str:
        exp = int(datetime.now(UTC).timestamp()) + expires_in
        return f"memory://{op}/{key}?exp={exp}"
