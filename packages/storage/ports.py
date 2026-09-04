"""StoragePort — the object storage interface and its shared types."""

from typing import Protocol

from pydantic import BaseModel


class StoredObject(BaseModel):
    """Metadata describing a stored object."""

    key: str
    size: int
    content_type: str


class ObjectNotFound(KeyError):
    """Raised when reading a key that does not exist."""


class StoragePort(Protocol):
    """Object storage port."""

    async def put(self, key: str, data: bytes, content_type: str) -> StoredObject: ...

    async def get(self, key: str) -> bytes: ...

    async def delete(self, key: str) -> None: ...

    async def exists(self, key: str) -> bool: ...

    async def presign_put(self, key: str, content_type: str, expires_in: int) -> str: ...

    async def presign_get(self, key: str, expires_in: int) -> str: ...
