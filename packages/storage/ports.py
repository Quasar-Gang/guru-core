"""StoragePort — 物件儲存的對外介面與共用型別。"""

from typing import Protocol

from pydantic import BaseModel


class StoredObject(BaseModel):
    """一個已寫入的物件的中繼資料。"""

    key: str
    size: int
    content_type: str


class ObjectNotFound(KeyError):
    """讀取不存在的 key 時拋出。"""


class StoragePort(Protocol):
    """物件儲存 port。"""

    async def put(self, key: str, data: bytes, content_type: str) -> StoredObject: ...

    async def get(self, key: str) -> bytes: ...

    async def delete(self, key: str) -> None: ...

    async def exists(self, key: str) -> bool: ...

    async def presign_put(self, key: str, content_type: str, expires_in: int) -> str: ...

    async def presign_get(self, key: str, expires_in: int) -> str: ...
