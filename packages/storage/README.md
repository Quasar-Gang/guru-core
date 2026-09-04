# packages/storage

## 負責什麼

提供物件儲存的抽象與實作：把 bytes 以 key 寫入／讀出／刪除，回報是否存在，並產生有時效的預簽章 URL（presigned URL），讓前端可以直接上傳或下載而不經過應用程式。

目前提供兩個實作：

- `LocalFileStorage`：MVP 的正式實作。物件寫在本機目錄的 `root` 底下，`content_type` 存成同名的 `.meta` sidecar JSON；presign 產生指向本地 API 的 `{public_base_url}/{key}?exp=…&op=…&sig=…`，簽章為 `HMAC-SHA256(signing_secret, "{op}:{key}:{exp}")` 的十六進位字串，可用 `LocalFileStorage.verify_signature(...)` 驗證。key 一律拒絕絕對路徑與 `..`，父目錄自動建立。
- `InMemoryStorage`：測試與本機開發用，資料放在 process 記憶體，presign 回傳 `memory://{op}/{key}?exp=…`。

## 對外 port 有哪些

`packages.storage.__all__` 明列的介面：

- `StoragePort`（Protocol）：`put` / `get` / `delete` / `exists` / `presign_put` / `presign_get`
- `StoredObject`（Pydantic model）：`key`、`size`、`content_type`
- `ObjectNotFound`（`KeyError` 子類別）：`get` 讀取不存在的 key 時拋出
- `LocalFileStorage`、`InMemoryStorage`：兩個實作

其餘模組（`ports.py`、`local.py`、`memory.py`）視為 private，請一律 `from packages.storage import ...`。

## 不負責什麼

- 不負責檔案內容的解析或轉換（那是 `packages/importers` 的事）。
- 不負責 metadata 的持久化與查詢（檔案紀錄存在資料庫，由 `packages/repo` 負責）；`.meta` sidecar 只是 `LocalFileStorage` 記住 content_type 的實作細節。
- 不負責驗證 presigned URL 的 HTTP 端點；`verify_signature` 只提供判斷函式，路由與權限檢查在 API service。
- 不負責授權與資料隔離，呼叫端須自行把 `user_id` 編進 key。
- 不負責 Cloudflare R2（`R2Storage` 是後續 task）、CDN、生命週期規則或病毒掃描。
