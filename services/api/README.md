# services/api — API Service

## 負責什麼

面向 App 的唯一 HTTP 入口（`/v1`），以及 `import.parse` / `export.push` 兩個 worker 的
consumer。目前已完成的部分：

- `POST /v1/auth/google` — 用 Google 授權碼登入，回本系統簽發的 JWT。
- `GET /v1/me` — 用 Bearer JWT 取得目前使用者。
- `GET /health` — 存活檢查，不需認證。

分層：`domain/`（純 Python 錯誤型別）→ `application/`（use case + port Protocol）
→ `adapters/`（FastAPI、httpx、JWT、時鐘）→ `container.py`（唯一組裝點）。

## 對外 port 有哪些

`application/ports.py` 定義本 service 自己的 port（實作在 `adapters/`）：

| Port | 正式實作 | 測試實作 |
|---|---|---|
| `GoogleOidcPort` | `adapters/google/oidc.py:GoogleOidc` | `FakeGoogleOidc` |
| `TokenIssuerPort` | `adapters/jwt_issuer.py:HmacTokenIssuer` | 同一個（配 `FakeClock`） |
| `ClockPort` | `adapters/clock.py:SystemClock` | `FakeClock`（可 `advance(seconds=...)`） |

其餘 port 來自 `packages/`：`packages.repo` 的 14 個 `XxxRepo`、`packages.storage`
的 `StoragePort`、`packages.queue` 的 `QueuePort`、`packages.cache` 的 `CachePort`。

## 不負責什麼

- 不生成、不修訂計畫（Plan Engine 的事）；不存 role model 內容（Role Model Service 的事）。
- 不直接呼叫 LLM。
- 不自己 new 任何 adapter：一切從 `ApiContainer` 取。

## 怎麼跑

```bash
uv run python -m cmd.api_server        # uvicorn，讀 .env
uv run pytest tests/unit/api tests/application/api
```

## 測試怎麼寫

repo 根目錄的 `conftest.py` 提供三個 fixture：

- `container` — `build_test_container()`，全 Fake（InMemory repo / storage / queue、
  `DictCache`、`FakeClock`、`HmacTokenIssuer`、`FakeGoogleOidc`）。
- `client` — `httpx.AsyncClient` + `httpx.ASGITransport`，打在 `create_app(container)` 上。
- `auth_headers` — 已建好一個使用者並簽好 JWT 的 `{"Authorization": "Bearer ..."}`；
  該使用者的 id 另有 `auth_user_id` fixture。

要換掉某個元件時用 `build_test_container(**overrides)`，被覆蓋的元件會真的傳進
依賴它的 use case。
