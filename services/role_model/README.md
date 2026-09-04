# Role Model Service

## 負責什麼

角色卡／特質卡（`role_models`）的權威來源。對外提供 `/role-models*` HTTP（port 8001）：
列表與 tag 查詢、單筆詳情、團隊寫入（`POST` / `PUT`）與停用（`DELETE`，軟刪除）。
寫入時強制驗證 tag 命名空間（PRD 12.3）與 `content` schema（PRD 12.4），
並把新出現的 tag 值學回 `config/tag_vocab.yaml`。

## 對外 port 有哪些

- HTTP（driving）：`GET /role-models`、`GET /role-models/tags`、`GET /role-models/{id}` 不需驗證；
  `POST /role-models`、`PUT /role-models/{id}`、`DELETE /role-models/{id}` 需 `X-API-Key`。
- `packages.repo.RoleModelRepo`（driven）：正式為 `PgRoleModelRepo`，測試為 `InMemoryRoleModelRepo`。
- `config/tag_vocab.yaml`（driven）：tag 詞彙的讀寫，路徑由 `RoleModelSettings.tag_vocab_path` 決定。

## 不負責什麼

不做使用者驗證（JWT 由 API Service 處理，本服務只認 API key）、不碰使用者資料、
不呼叫其他 service、不排程也不產生計畫。角色卡如何被選用與渲染進 prompt 是 Plan Engine 的事。
