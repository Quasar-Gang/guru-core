# packages/cache

## 負責什麼

提供跨 service 共用的鍵值快取抽象：字串值的讀寫、TTL 過期，以及 rate limit 用的原子遞增計數器（`incr`）。
正式實作為 `RedisCache`（`redis.asyncio`），測試與單機開發用 `DictCache`（行程內 dict，clock 可注入以測 TTL）。

## 對外 port 有哪些

- `CachePort`：`get(key)` / `set(key, value, ttl_seconds=None)` / `delete(key)` / `incr(key, ttl_seconds=None)`
- 實作：`RedisCache(url)`（另有 `close()`）、`DictCache(clock=time.monotonic)`

## 不負責什麼

- 不是資料的權威來源。任務與 session 狀態的權威來源是 PostgreSQL，快取清空不得造成資料遺失。
- 不做序列化：值一律由呼叫端轉成字串（JSON 等）後傳入。
- 不做 rate limit 策略判斷（視窗長度、門檻、拒絕行為），只提供計數原語。
- 不管理 pub/sub、佇列或分散式鎖（佇列見 `packages/queue`）。
