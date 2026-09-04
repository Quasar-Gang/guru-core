# CONTRIBUTING — guru-core

## 本機基礎設施

| 項目 | 位置 | 備註 |
|---|---|---|
| PostgreSQL 15 | `127.0.0.1:5432` | `postgres` / `postgres`，DB 名 `guru_core` |
| Redis 7 | `127.0.0.1:6379` | 佇列與快取 |
| 物件儲存 | `./.data/storage` | MVP 用 `LocalFileStorage`；`STORAGE_BACKEND=r2` 可切到 Cloudflare R2 |
| LLM | `LLM_ADAPTER=fake` | 開發與測試預設讀 `tests/fixtures/llm/` |

## 常用指令

```bash
uv sync                       # 安裝依賴
make check                    # ruff → mypy --strict → import-linter → pytest（不起 Docker）
make fmt                      # 自動排版與修正
make integration              # 需要本機 PostgreSQL 的整合測試
uv run alembic upgrade head   # 套用 migration
uv run alembic check          # 確認 model 與 migration 同步
uv run python -m cmd.api_server            # API Service HTTP (8000)
uv run python -m cmd.api_worker            # import.parse / export.push worker
uv run python -m cmd.plan_engine_worker    # plan.generate / continue / revise worker
uv run python -m cmd.role_model_server     # Role Model Service HTTP (8001)
uv run python -m cmd.seed_role_models      # 寫入 seeds/role_models/*.yaml
uv run python -m cmd.check_llm             # 對設定的 provider 跑一次 smoke test
```

## 工程紀律

以下逐條照抄自 PRD 第 9 節，CI 會強制其中可自動檢查的部分。

### 9.1 邊界（用工具強制，不靠自覺）

1. 依賴方向只能 `adapters → application → domain`；反向 import 直接 CI 失敗（`import-linter` layers contract）。
2. Service 之間不能互相 import。只能透過 `packages/` 或佇列溝通；`services/plan_engine` 出現 `from services.api import ...` 即違規。
2b. `cmd/` 只能 import 各 service 的 `container.py` 與 `packages/` 的 runtime helper，不能 import use case 或 domain；`cmd/` 出現業務判斷即違規。
3. 每個共用套件只 export `__init__.py` 中的公開介面，其餘視為 private。
4. 一張表只有一個 service 能寫，其他只讀；owner 寫在表格 docstring（見 4.2）。

### 9.2 抽象（所有存儲與外部都是 port，皆可替換）

5. 以下一律定義 `Protocol`，實作放 adapters：`LLMPort`、`StoragePort`、`QueuePort`、`CachePort`、每張表的 `XxxRepo`、`SourcePort` / `ParserPort`、`CalendarPort` / `NotionPort`。Scheduler、`RoleModelRenderer`、難度推導係數屬於 domain 的純函式，不是 port——它們沒有外部依賴，必須可單獨測試。
6. 每個 port 至少兩個實作：正式版 + `InMemory` / `Fake` 版。Fake 版的目的是現在的測試不用起 Docker——這是抽象有沒有做對的驗證。
7. Port 介面只用 domain 型別，不用供應商型別。`StoragePort.put(key, bytes)` 可以，`put(boto3_object)` 不行；`LLMPort.complete()` 回 Pydantic model，不回 SDK response。
8. 供應商切換只改組裝點：每個 service 一個 `container.py`，環境變數決定實作。其他地方看不到 `boto3`、`anthropic`、`openai`、`redis` 這些字。

### 9.3 易讀性

9. 一個 use case 一個檔案，檔名是動詞：`evaluate_session.py`、`generate_followups.py`。
10. Domain 狀態機用 enum + 明確轉移表，不散落 `if status == "questioning"`。
11. 固定命名：port 叫 `XxxPort`，實作叫 `技術名 + Xxx`（`PgSessionRepo`、`R2Storage`、`OpenAICompatLLM`），use case 叫動詞。
12. `mypy --strict` 過；Pydantic 管所有進出邊界的資料（HTTP、佇列 payload、LLM 輸出）。
13. 每個 service 與套件根目錄一份 `README.md`，只回答三個問題：負責什麼、對外 port 有哪些、不負責什麼。

### 9.4 變更紀律

14. 加新的外部整合 = 加一個 adapter + 改 container，不改 use case；若需改 use case，代表 port 設計錯了，先修 port。
15. DB schema 只透過 Alembic migration 改，migration 與功能同一 PR。
16. 佇列 payload 是版本化 Pydantic model；加欄位可以，改語意要開新版本。
17. 任務狀態的權威來源在 PostgreSQL，Redis 只當快取；Redis 清空不能導致任何 session 或 job 消失。

### 9.5 CI 必過清單

`ruff` → `mypy --strict` → `import-linter`（含 `cmd/` 那條）→ `pytest`（unit + application，皆不起 Docker）→ `alembic check`
