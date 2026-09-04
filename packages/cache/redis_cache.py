from typing import cast

import redis.asyncio as aioredis


class RedisCache:
    """CachePort implementation backed by Redis."""

    def __init__(self, url: str) -> None:
        self._pool = aioredis.ConnectionPool.from_url(url, decode_responses=True)
        self._redis = aioredis.Redis(connection_pool=self._pool)

    async def get(self, key: str) -> str | None:
        return cast(str | None, await self._redis.get(key))

    async def set(self, key: str, value: str, ttl_seconds: int | None = None) -> None:
        await self._redis.set(key, value, ex=ttl_seconds)

    async def delete(self, key: str) -> None:
        await self._redis.delete(key)

    async def incr(self, key: str, ttl_seconds: int | None = None) -> int:
        value = cast(int, await self._redis.incr(key))
        if ttl_seconds is not None and value == 1:
            await self._redis.expire(key, ttl_seconds)
        return value

    async def close(self) -> None:
        await self._redis.aclose()
        await self._pool.aclose()
