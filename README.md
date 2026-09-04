# guru-core

coach.ai 的後端：使用者輸入目標，系統以 LLM 整併資料、必要時追問，產出三種難度的可執行計畫，能匯出到 Google Calendar 或 Markdown、逐項勾選完成，並在落後時提出修訂。

規格見 [`guru-core-PRD.md`](guru-core-PRD.md)，實作計畫見 [`docs/superpowers/plans/`](docs/superpowers/plans/)，工程紀律見 [`CONTRIBUTING.md`](CONTRIBUTING.md)。

## 架構

三個可獨立部署的 service，共用六個 packages、一個 PostgreSQL 與一個 Redis。Service 之間不互相 HTTP 呼叫，只透過佇列與共用 DB 溝通。

| Service | 型態 | 負責 |
|---|---|---|
| API Service | HTTP + worker | Auth、OAuth、所有 App 端點、匯入解析、匯出推送、發佇列任務 |
| Plan Engine | 純 worker | 整併資料、評估指標、產生 follow-up、生成計畫、產生修訂與 diff |
| Role Model Service | 純 HTTP | Role model 查詢、團隊寫入、LLM 推薦 |

所有外部依賴都是 Protocol port（`LLMPort`、`StoragePort`、`QueuePort`、`CachePort`、各表的 `XxxRepo`、`SourcePort` / `ParserPort`），每個 port 至少一個正式實作與一個 Fake，**單元與 application 測試不起 Docker**。

## 六個執行入口

同一個映像，換 entrypoint 就換角色。

```bash
uv run python -m cmd.api_server          # API Service HTTP（8000）
uv run python -m cmd.api_worker          # import.parse / export.push worker
uv run python -m cmd.plan_engine_worker  # plan.generate / continue / revise worker
uv run python -m cmd.role_model_server   # Role Model Service HTTP（8001）
uv run python -m cmd.seed_role_models    # 寫入 seeds/role_models/*.yaml
uv run python -m cmd.check_llm           # 對設定的 provider 跑一次 smoke test
```

## 本機開發

需要 Python 3.12 與 [uv](https://docs.astral.sh/uv/)。本機已有的 PostgreSQL（5432）與 Redis（6379）可直接使用。

```bash
uv sync
cp .env.example .env                  # 依需要調整
uv run alembic upgrade head           # 建立 schema
uv run python -m cmd.seed_role_models # 寫入 12 筆 role model
make check                            # ruff → mypy --strict → import-linter → pytest
make integration                      # 需要本機 PostgreSQL 的整合測試
```

`docker-compose.yml` 提供整套隔離環境（compose 內的 postgres / redis 對外映射為 5433 / 6380，避免與本機既有服務衝突）。

## 設定

所有設定集中在 `config/` 與環境變數，切換供應商不需要改程式碼。

| 檔案 | 內容 |
|---|---|
| `config/llm.yaml` | LLM provider、每種用途的參數、role model context 預算、重試次數 |
| `config/readiness_metrics.yaml` | 追問指標清單（required / domain_probe / helpful） |
| `config/scheduler.yaml` | 排程的最小間隔、衝突往後挪的上限、slot 順序 |
| `config/difficulty_coefficients.yaml` | 三種難度的推導係數 |
| `config/tag_vocab.yaml` | Role model tag 的命名空間白名單與受控值 |
| `config/calendar_colors.yaml` | Google Calendar colorId 對應 |

### 切換 LLM provider

只改環境變數，程式碼不動：

| 情境 | `LLM_ADAPTER` | `LLM_BASE_URL` | `structured_output` |
|---|---|---|---|
| 測試 / 開發 | `fake` | — | — |
| 本地 vLLM | `openai_compat` | `http://localhost:8000/v1` | `guided_json` |
| 本地 Ollama | `openai_compat` | `http://localhost:11434/v1` | `json_schema` |
| Claude | `anthropic` | — | `tool_use` |

### 切換物件儲存

MVP 用本機檔案儲存（`LocalFileStorage`）。要接回 Cloudflare R2 只需改環境變數：

```
STORAGE_BACKEND=r2
R2_ACCOUNT_ID=...
R2_ACCESS_KEY_ID=...
R2_SECRET_ACCESS_KEY=...
R2_BUCKET=...
```

`container.py` 是唯一的組裝點，任何 use case 都不會因此改動。
