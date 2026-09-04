from typing import Protocol


class CachePort(Protocol):
    """Key-value cache. Values are always strings; expiry is driven by TTL."""

    async def get(self, key: str) -> str | None: ...

    async def set(self, key: str, value: str, ttl_seconds: int | None = None) -> None: ...

    async def delete(self, key: str) -> None: ...

    async def incr(self, key: str, ttl_seconds: int | None = None) -> int:
        """Increment by one and return the new value, starting at 1 for a missing key.

        `ttl_seconds` is applied only when the key is created.
        """
        ...
