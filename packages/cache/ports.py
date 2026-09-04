from typing import Protocol


class CachePort(Protocol):
    """鍵值快取。值一律是字串，過期由 TTL 控制。"""

    async def get(self, key: str) -> str | None: ...

    async def set(self, key: str, value: str, ttl_seconds: int | None = None) -> None: ...

    async def delete(self, key: str) -> None: ...

    async def incr(self, key: str, ttl_seconds: int | None = None) -> int:
        """加一並回傳新值；key 不存在時從 1 開始。ttl 只在建立 key 時套用。"""
        ...
