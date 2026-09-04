# packages/cache

## What it owns

A shared key-value cache abstraction used across services: reading and writing string values, TTL
expiry, and an atomic increment counter (`incr`) for rate limiting.
The production implementation is `RedisCache` (`redis.asyncio`); tests and single-machine
development use `DictCache`, an in-process dict with an injectable clock so TTL behaviour is
testable.

## The ports it exposes

- `CachePort`: `get(key)` / `set(key, value, ttl_seconds=None)` / `delete(key)` / `incr(key, ttl_seconds=None)`
- Implementations: `RedisCache(url)` (plus `close()`), `DictCache(clock=time.monotonic)`

## What it does not do

- It is not a source of truth. Job and session state live in PostgreSQL; flushing the cache must
  never lose data.
- It does not serialize: callers convert values to strings (JSON or otherwise) before passing them in.
- It does not decide rate limit policy (window length, thresholds, rejection behaviour); it only
  provides the counting primitive.
- It does not handle pub/sub, queues or distributed locks (queues live in `packages/queue`).
