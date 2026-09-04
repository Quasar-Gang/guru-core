# guru-core MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建置 guru-core 後端 MVP：使用者輸入目標 → LLM 評估/追問 → 產出三種難度可執行計畫 → 內建 todo/check-in → 匯出 Google Calendar / Markdown → 手動修訂。

**Architecture:** Python monorepo，Hexagonal（Ports & Adapters）。三個可獨立部署 service（`api`、`plan_engine`、`role_model`）共用六個 packages（`llm`、`importers`、`repo`、`storage`、`queue`、`cache`）與一個 PostgreSQL / Redis。Service 之間不互相 HTTP 呼叫，只靠佇列（ARQ on Redis）與共用 DB（經 `repo`）。所有外部依賴皆為 Protocol port，每個 port 至少一個正式實作 + 一個 Fake，測試不起 Docker。

**Tech Stack:** Python 3.12、FastAPI、Pydantic v2、SQLAlchemy 2.0 async + asyncpg、Alembic、ARQ、Redis 7、PostgreSQL 15、uv、pytest + pytest-asyncio、ruff、mypy --strict、import-linter。

**Spec:** `guru-core-PRD.md`（repo root，v0.2 Draft）

---

## Global Constraints

這些規則適用於**每一個** task，不再於個別 task 重複：

1. **Python 3.12**，套件管理一律用 `uv`（`uv add`、`uv run`）。不使用 pip / poetry / venv 手動操作。
2. **依賴方向**只能 `cmd → container → adapters → application → domain`；反向 import 一律禁止。`cmd/` 只能 import 各 service 的 `container.py` 與 `packages/` 的 runtime helper，不能 import use case 或 domain，且不得含業務判斷。以 `.importlinter` 強制。
3. **Service 之間不能互相 import**：`services/plan_engine` 出現 `from services.api import ...` 即違規。
4. **每個 package 只 export `__init__.py` 中的公開介面**，其餘視為 private（`__all__` 明列）。
5. **Port 介面只用 domain / stdlib / Pydantic 型別**，不出現供應商型別。`boto3`、`anthropic`、`openai`、`redis`、`arq`、`google` 這些字只能出現在 `packages/*/`（adapter 實作檔）與 `services/*/container.py`；application 與 domain 層一律看不到。
6. **每個 port 至少兩個實作**：正式版 + `InMemory`/`Fake`/`Local` 版。unit + application 測試**不得**啟動 Docker、DB、Redis 或呼叫外網。
7. **命名**：port 叫 `XxxPort`；實作叫「技術名 + Xxx」（`PgSessionRepo`、`LocalFileStorage`、`OpenAICompatLLM`、`ArqQueue`）；use case 檔名是動詞（`evaluate_session.py`），一個 use case 一個檔案，類別名為 `動詞Xxx` 的 PascalCase（`EvaluateSession`）。
8. **`mypy --strict` 必須全綠**，`ruff check` 與 `ruff format --check` 必須全綠。
9. **所有跨邊界資料（HTTP body、佇列 payload、LLM 輸出、config 檔）一律 Pydantic v2 model**。佇列 payload model 名稱帶版本後綴（`PlanGenerateJobV1`）。
10. **DB schema 只透過 Alembic migration 改**，migration 與功能同一 commit。
11. **資料隔離**：所有涉及使用者資料的 repo 方法簽名必須帶 `user_id: UUID`，不提供無 `user_id` 的查詢（`role_models` 與 job 狀態除外）。
12. **任務狀態權威來源是 PostgreSQL**，Redis 只當快取；Redis 清空不得導致任何 session 或 job 遺失。
13. **時間**：DB 一律 `TIMESTAMP WITH TIME ZONE`，程式內一律 timezone-aware `datetime`，UTC 儲存；使用者本地時間換算依 `profiles.timezone`（IANA 字串）。禁用 `datetime.utcnow()`，一律 `datetime.now(UTC)`。
14. **TDD 強制**：每個 task 先寫失敗測試 → 跑到看見它失敗 → 寫最小實作 → 跑到綠 → commit。禁止先寫實作。
15. **Commit 格式**：Conventional Commits（`feat:`、`fix:`、`test:`、`chore:`、`refactor:`）。每個 task 至少一個 commit。
16. **本機基礎設施（已就緒，不需自行啟動）**：
    - PostgreSQL 15 @ `127.0.0.1:5432`，帳密 `postgres` / `postgres`，MVP 專用 DB 名 `guru_core`（首次由 M0 建立）。
    - Redis 7 @ `127.0.0.1:6379`（**注意：不是 6397**）。
    - 物件儲存：**MVP 不接 Cloudflare R2**。`StoragePort` 的正式實作是 `LocalFileStorage`（寫本機目錄，presign 回本地 API 的簽章 URL）。`R2Storage` 於 M5 補上，屆時只改 `container.py` 與環境變數，不動任何 use case。
17. **LLM**：開發與測試一律用 `FakeLLM`（讀 `tests/fixtures/llm/`）。`OpenAICompatLLM` / `AnthropicLLM` 需實作並有以 mock transport 為基礎的測試，但不在 CI 打外網。
18. **每個 service 與 package 根目錄一份 `README.md`**，只回答三個問題：負責什麼、對外 port 有哪些、不負責什麼。

---

## File Structure

```
guru-core/
├── cmd/                              # 執行入口，每檔 ≤30 行，零業務邏輯
│   ├── api_server.py                 # FastAPI(uvicorn) — API Service HTTP
│   ├── api_worker.py                 # ARQ worker — import.parse, export.push
│   ├── plan_engine_worker.py         # ARQ worker — plan.generate/continue/revise
│   ├── role_model_server.py          # FastAPI — Role Model Service HTTP
│   ├── seed_role_models.py           # seeds/*.yaml → 驗證 → upsert
│   └── check_llm.py                  # 對設定 provider 跑一次 smoke test
├── packages/
│   ├── config/                       # 共用設定載入（YAML + env 展開）
│   │   ├── __init__.py               # load_yaml_config(path, model) -> BaseModel
│   │   └── env.py                    # ${VAR} / ${VAR:-default} 展開
│   ├── llm/
│   │   ├── __init__.py               # LLMPort, Purpose, LLMConfig, build_llm, LLMError
│   │   ├── ports.py                  # LLMPort Protocol, Purpose enum, LLMResult
│   │   ├── config.py                 # LLMConfig / ProviderConfig / ParamsConfig
│   │   ├── prompts.py                # PromptRegistry（jinja2 模板 + 版本）
│   │   ├── prompts/                  # *.md 模板（含 YAML frontmatter: version）
│   │   ├── openai_compat.py          # OpenAICompatLLM
│   │   ├── anthropic_llm.py          # AnthropicLLM
│   │   ├── fake.py                   # FakeLLM
│   │   ├── validation.py             # 驗證→回灌→降級鏈（7.5）
│   │   └── observability.py          # LLMCallLog + emit
│   ├── repo/
│   │   ├── __init__.py               # 所有 Port + build_repos
│   │   ├── models.py                 # SQLAlchemy ORM，所有表
│   │   ├── ports.py                  # 每張表一個 XxxRepo Protocol
│   │   ├── pg/                       # PgXxxRepo（每個 repo 一檔）
│   │   └── memory/                   # InMemoryXxxRepo（每個 repo 一檔）
│   ├── storage/
│   │   └── __init__.py + ports.py, local.py, r2.py, memory.py
│   ├── queue/
│   │   └── __init__.py + ports.py, jobs.py, arq_queue.py, memory.py, worker.py
│   ├── cache/
│   │   └── __init__.py + ports.py, redis_cache.py, dict_cache.py
│   └── importers/
│       ├── __init__.py + ports.py, document.py
│       ├── sources/ (upload.py, google_calendar.py, memory.py)
│       └── parsers/ (csv.py, xlsx.py, markdown.py, html.py, pdf.py, docx.py, ics.py, registry.py)
├── services/
│   ├── api/{domain,application,adapters,container.py}
│   ├── plan_engine/{domain,application,adapters,container.py}
│   └── role_model/{domain,application,adapters,container.py}
├── config/                           # llm.yaml, readiness_metrics.yaml, scheduler.yaml,
│                                     # tag_vocab.yaml, difficulty_coefficients.yaml, calendar_colors.yaml
├── seeds/role_models/*.yaml
├── migrations/                       # Alembic
├── tests/{unit,application,fixtures}
├── .importlinter
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml
└── CONTRIBUTING.md
```

---

## Milestone Map

| Phase | Tasks | 交付 |
|---|---|---|
| **M0 骨架** | 1–10 | monorepo、CI 三閘門、六個 port + Fake、DB schema、llm 套件（provider 路由 + 驗證鏈 + 觀測） |
| **M1 輸入** | 11–16 | Auth（Google OIDC + JWT）、Profile、Upload 匯入、解析器、Google Calendar 匯入 |
| **M2 引擎** | 17–24 | Readiness 評估、follow-up loop、PlanTemplate 生成、難度推導、Scheduler、狀態機、端到端 |
| **M3 Role model** | 25–29 | tag 驗證、CRUD API、seed、LLM 推薦、RoleModelRenderer 接入 Plan Engine |
| **M4 管理與輸出** | 30–35 | 計畫列表/啟用/封存/刪除、tasks CRUD、check-in、Google OAuth 連線、Calendar 匯出（full/incremental）、Markdown 匯出 |
| **M4.5 修訂** | 36–37 | 修訂觸發、postpone/reduce、diff、accept/reject |
| **M5 硬化** | 38–41 | 限流、結構化 log、R2Storage、docker-compose 端到端冒煙 |

---

# Phase M0 — 骨架

## Task 1: 專案骨架與 CI 三閘門

**Files:**
- Create: `pyproject.toml`, `.importlinter`, `.gitignore`, `.env.example`, `CONTRIBUTING.md`, `Makefile`
- Create: `packages/__init__.py`, `services/__init__.py`, `cmd/__init__.py`（皆空檔）
- Create: `tests/__init__.py`, `tests/unit/__init__.py`, `tests/application/__init__.py`
- Create: `tests/unit/test_import_boundaries.py`

**Interfaces:**
- Consumes: 無
- Produces: `uv run pytest` / `uv run ruff check .` / `uv run mypy .` / `uv run lint-imports` 四個指令可跑；套件命名空間 `packages.*`、`services.*`、`cmd.*` 可 import。

- [ ] **Step 1: 建立 pyproject.toml**

```toml
[project]
name = "guru-core"
version = "0.1.0"
requires-python = ">=3.12,<3.13"
dependencies = [
  "pydantic>=2.9",
  "pydantic-settings>=2.5",
  "pyyaml>=6.0",
  "jinja2>=3.1",
]

[dependency-groups]
dev = [
  "pytest>=8.3",
  "pytest-asyncio>=0.24",
  "ruff>=0.7",
  "mypy>=1.13",
  "import-linter>=2.1",
  "types-pyyaml",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["packages", "services", "cmd"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
addopts = "-q"

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "SIM", "TID"]

[tool.mypy]
python_version = "3.12"
strict = true
plugins = ["pydantic.mypy"]
warn_unused_ignores = true
disallow_any_generics = true

[[tool.mypy.overrides]]
module = ["tests.*"]
disallow_untyped_defs = false
```

- [ ] **Step 2: 建立 `.importlinter`**

```ini
[importlinter]
root_packages =
    packages
    services
    cmd

[importlinter:contract:layers]
name = Hexagonal layers per service
type = layers
containers =
    services.api
    services.plan_engine
    services.role_model
layers =
    adapters
    application
    domain

[importlinter:contract:services-independent]
name = Services must not import each other
type = independence
modules =
    services.api
    services.plan_engine
    services.role_model

[importlinter:contract:cmd-thin]
name = cmd may only touch containers and packages
type = forbidden
source_modules =
    cmd
forbidden_modules =
    services.api.application
    services.api.domain
    services.api.adapters
    services.plan_engine.application
    services.plan_engine.domain
    services.plan_engine.adapters
    services.role_model.application
    services.role_model.domain
    services.role_model.adapters

[importlinter:contract:domain-pure]
name = Domain must not import frameworks or vendor SDKs
type = forbidden
source_modules =
    services.api.domain
    services.plan_engine.domain
    services.role_model.domain
forbidden_modules =
    fastapi
    sqlalchemy
    arq
    redis
    boto3
    openai
    anthropic
    httpx

[importlinter:contract:application-no-vendor]
name = Application must not import vendor SDKs
type = forbidden
source_modules =
    services.api.application
    services.plan_engine.application
    services.role_model.application
forbidden_modules =
    fastapi
    sqlalchemy
    arq
    redis
    boto3
    openai
    anthropic
```

- [ ] **Step 3: 建立目錄骨架與空 `__init__.py`**

所有 `packages/`、`services/{api,plan_engine,role_model}/{domain,application,adapters}`、`cmd/`、`tests/` 下都要有 `__init__.py`（`packages/llm/prompts/` 與 `config/`、`seeds/`、`migrations/` 除外）。

- [ ] **Step 4: 寫失敗測試 `tests/unit/test_import_boundaries.py`**

```python
import subprocess


def test_import_linter_contracts_pass():
    result = subprocess.run(
        ["uv", "run", "lint-imports"], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stdout + result.stderr
```

- [ ] **Step 5: 跑測試確認會失敗**

Run: `uv run pytest tests/unit/test_import_boundaries.py -v`
Expected: FAIL（`.importlinter` 或目錄尚未齊全）

- [ ] **Step 6: 補齊目錄與設定直到測試通過**

Run: `uv sync && uv run pytest tests/unit/test_import_boundaries.py -v`
Expected: PASS

- [ ] **Step 7: 建立 Makefile**

```makefile
.PHONY: check test lint type imports fmt
check: lint type imports test
lint: ; uv run ruff check . && uv run ruff format --check .
fmt: ; uv run ruff format . && uv run ruff check --fix .
type: ; uv run mypy .
imports: ; uv run lint-imports
test: ; uv run pytest
```

- [ ] **Step 8: 建立 `.env.example`**

```
DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/guru_core
REDIS_URL=redis://127.0.0.1:6379/0
STORAGE_BACKEND=local
STORAGE_LOCAL_ROOT=./.data/storage
STORAGE_PUBLIC_BASE_URL=http://127.0.0.1:8000/v1/files
STORAGE_SIGNING_SECRET=dev-storage-secret-change-me
JWT_SECRET=dev-jwt-secret-change-me
JWT_TTL_SECONDS=2592000
OAUTH_TOKEN_ENC_KEY=
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
GOOGLE_REDIRECT_URI=http://127.0.0.1:8000/v1/integrations/google/callback
ROLE_MODEL_API_KEY=dev-role-model-key
ROLE_MODEL_BASE_URL=http://127.0.0.1:8001
LLM_ADAPTER=fake
LLM_BASE_URL=http://127.0.0.1:8000/v1
LLM_API_KEY=dummy
LLM_MODEL=local-model
LLM_MAX_CONTEXT=16000
```

- [ ] **Step 9: 寫 `CONTRIBUTING.md`**

內容為 PRD 第 9 節的 17 條紀律逐條列出（原文照抄，不要改寫），加上「本機基礎設施」與「常用指令」兩節。

- [ ] **Step 10: `make check` 全綠後 commit**

```bash
git add -A && git commit -m "chore: bootstrap monorepo skeleton with CI gates"
```

---

## Task 2: `packages/config` — YAML + env 展開

**Files:**
- Create: `packages/config/__init__.py`, `packages/config/env.py`
- Test: `tests/unit/packages/config/test_env.py`, `tests/unit/packages/config/test_load.py`

**Interfaces:**
- Produces:
  ```python
  # packages/config/env.py
  def expand_env(raw: str, environ: Mapping[str, str] | None = None) -> str: ...
      # 展開 ${VAR} 與 ${VAR:-default}；VAR 不存在且無 default -> raise MissingEnvVar

  class MissingEnvVar(RuntimeError): ...

  # packages/config/__init__.py
  ConfigT = TypeVar("ConfigT", bound=BaseModel)
  def load_yaml_config(path: Path, model: type[ConfigT],
                       environ: Mapping[str, str] | None = None) -> ConfigT: ...
  CONFIG_DIR: Path   # repo root / "config"
  ```

- [ ] **Step 1: 寫失敗測試**

```python
import pytest
from packages.config.env import MissingEnvVar, expand_env


def test_expands_plain_var():
    assert expand_env("url: ${HOST}", {"HOST": "abc"}) == "url: abc"


def test_expands_default_when_missing():
    assert expand_env("k: ${NOPE:-fallback}", {}) == "k: fallback"


def test_env_wins_over_default():
    assert expand_env("k: ${A:-fallback}", {"A": "real"}) == "k: real"


def test_missing_without_default_raises():
    with pytest.raises(MissingEnvVar, match="HOST"):
        expand_env("url: ${HOST}", {})


def test_empty_default_allowed():
    assert expand_env("k: ${NOPE:-}", {}) == "k: "
```

```python
from pathlib import Path
from pydantic import BaseModel
from packages.config import load_yaml_config


class Sample(BaseModel):
    name: str
    port: int


def test_load_yaml_with_env(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("SAMPLE_PORT", "9999")
    p = tmp_path / "s.yaml"
    p.write_text("name: hi\nport: ${SAMPLE_PORT}\n")
    cfg = load_yaml_config(p, Sample)
    assert cfg.name == "hi" and cfg.port == 9999
```

- [ ] **Step 2: 跑測試確認失敗** — `uv run pytest tests/unit/packages/config -v`，Expected: FAIL（模組不存在）
- [ ] **Step 3: 實作 `expand_env`（regex `\$\{(\w+)(?::-([^}]*))?\}`）與 `load_yaml_config`（讀檔 → expand → `yaml.safe_load` → `model.model_validate`）**
- [ ] **Step 4: 跑測試至 PASS**
- [ ] **Step 5: `make check` 後 commit** — `feat(config): yaml loader with env expansion`

---

## Task 3: `packages/storage` — StoragePort + Local/InMemory 實作

**Files:**
- Create: `packages/storage/__init__.py`, `ports.py`, `local.py`, `memory.py`, `README.md`
- Test: `tests/unit/packages/storage/test_contract.py`

**Interfaces:**
- Produces:
  ```python
  # ports.py
  class StoredObject(BaseModel):
      key: str
      size: int
      content_type: str

  class StoragePort(Protocol):
      async def put(self, key: str, data: bytes, content_type: str) -> StoredObject: ...
      async def get(self, key: str) -> bytes: ...        # 不存在 -> raise ObjectNotFound
      async def delete(self, key: str) -> None: ...      # 不存在為 no-op
      async def exists(self, key: str) -> bool: ...
      async def presign_put(self, key: str, content_type: str,
                            expires_in: int) -> str: ...
      async def presign_get(self, key: str, expires_in: int) -> str: ...

  class ObjectNotFound(KeyError): ...

  # local.py
  class LocalFileStorage:
      def __init__(self, root: Path, public_base_url: str, signing_secret: str) -> None: ...
      # presign_* 產生 f"{public_base_url}/{key}?exp={ts}&op={put|get}&sig={hmac}"
      # HMAC-SHA256(signing_secret, f"{op}:{key}:{exp}") 十六進位
      @staticmethod
      def verify_signature(secret: str, op: str, key: str, exp: int, sig: str,
                           now: datetime) -> bool: ...

  # memory.py
  class InMemoryStorage:  # presign 回 f"memory://{op}/{key}?exp={ts}"
      def __init__(self) -> None: ...
  ```
  `R2Storage` 於 Task 44 補上，此 task **不實作**。

- [ ] **Step 1: 寫失敗測試 — 對兩個實作跑同一份契約測試**

```python
import pytest
from datetime import UTC, datetime
from pathlib import Path
from packages.storage import InMemoryStorage, LocalFileStorage, ObjectNotFound


@pytest.fixture(params=["memory", "local"])
def storage(request, tmp_path: Path):
    if request.param == "memory":
        return InMemoryStorage()
    return LocalFileStorage(tmp_path, "http://x/v1/files", "secret")


async def test_put_then_get_roundtrip(storage):
    await storage.put("a/b.txt", b"hello", "text/plain")
    assert await storage.get("a/b.txt") == b"hello"


async def test_get_missing_raises(storage):
    with pytest.raises(ObjectNotFound):
        await storage.get("nope")


async def test_delete_is_idempotent(storage):
    await storage.put("k", b"x", "text/plain")
    await storage.delete("k")
    await storage.delete("k")
    assert await storage.exists("k") is False


async def test_presign_put_contains_key(storage):
    url = await storage.presign_put("up/1.pdf", "application/pdf", 900)
    assert "up/1.pdf" in url


def test_local_signature_roundtrip(tmp_path: Path):
    exp = int(datetime.now(UTC).timestamp()) + 900
    s = LocalFileStorage(tmp_path, "http://x", "secret")
    import hmac, hashlib
    sig = hmac.new(b"secret", b"get:k:%d" % exp, hashlib.sha256).hexdigest()
    assert LocalFileStorage.verify_signature(
        "secret", "get", "k", exp, sig, datetime.now(UTC)) is True
    assert LocalFileStorage.verify_signature(
        "secret", "get", "k", exp, "bad", datetime.now(UTC)) is False


def test_local_rejects_path_traversal(tmp_path: Path):
    s = LocalFileStorage(tmp_path, "http://x", "secret")
    with pytest.raises(ValueError):
        s._resolve("../escape")
```

- [ ] **Step 2: 跑測試確認失敗**
- [ ] **Step 3: 實作**（`LocalFileStorage._resolve` 必須拒絕 `..` 與絕對路徑；父目錄自動建立；content_type 存成同名 `.meta` sidecar JSON）
- [ ] **Step 4: 跑測試至 PASS**
- [ ] **Step 5: 寫 `packages/storage/README.md`（負責什麼 / port / 不負責什麼）**
- [ ] **Step 6: `make check` 後 commit** — `feat(storage): StoragePort with local and in-memory adapters`

---

## Task 4: `packages/cache` — CachePort + Redis/Dict 實作

**Files:**
- Create: `packages/cache/__init__.py`, `ports.py`, `redis_cache.py`, `dict_cache.py`, `README.md`
- Test: `tests/unit/packages/cache/test_dict_cache.py`

**Interfaces:**
- Produces:
  ```python
  class CachePort(Protocol):
      async def get(self, key: str) -> str | None: ...
      async def set(self, key: str, value: str, ttl_seconds: int | None = None) -> None: ...
      async def delete(self, key: str) -> None: ...
      async def incr(self, key: str, ttl_seconds: int | None = None) -> int: ...  # rate limit 用

  class DictCache:
      def __init__(self, clock: Callable[[], float] = time.monotonic) -> None: ...

  class RedisCache:
      def __init__(self, url: str) -> None: ...
      async def close(self) -> None: ...
  ```
  `redis` 只在 `redis_cache.py` import。

- [ ] **Step 1: 寫失敗測試**（`DictCache`：set/get、TTL 過期回 None（用可注入的假 clock）、delete、incr 從 1 開始遞增）
- [ ] **Step 2: 跑測試確認失敗**
- [ ] **Step 3: 實作 `DictCache` 與 `RedisCache`（`uv add redis`）**
- [ ] **Step 4: 跑測試至 PASS**
- [ ] **Step 5: 寫 README 並 commit** — `feat(cache): CachePort with redis and dict adapters`

---

## Task 5: `packages/queue` — QueuePort + Job payloads + worker runner

**Files:**
- Create: `packages/queue/__init__.py`, `ports.py`, `jobs.py`, `arq_queue.py`, `memory.py`, `worker.py`, `README.md`
- Test: `tests/unit/packages/queue/test_memory_queue.py`, `tests/unit/packages/queue/test_jobs.py`

**Interfaces:**
- Produces:
  ```python
  # jobs.py — 所有佇列 payload，版本化
  class JobPayload(BaseModel):
      model_config = ConfigDict(frozen=True, extra="forbid")
      @classmethod
      def queue_name(cls) -> str: ...   # 子類覆寫

  class ImportParseJobV1(JobPayload):   # queue_name -> "import.parse"
      import_id: UUID
  class PlanGenerateJobV1(JobPayload):  # "plan.generate"
      session_id: UUID
  class PlanContinueJobV1(JobPayload):  # "plan.continue"
      session_id: UUID
  class PlanReviseJobV1(JobPayload):    # "plan.revise"
      plan_id: UUID
      revision_id: UUID
      strategy: Literal["postpone", "reduce"]
  class ExportJobV1(JobPayload):        # "export.push"
      plan_id: UUID
      target: Literal["google_calendar", "google_sheets", "notion"]
      mode: Literal["full", "incremental"]

  JOB_REGISTRY: dict[str, type[JobPayload]]   # queue_name -> class

  # ports.py
  class JobStatus(StrEnum):
      queued = "queued"; running = "running"; done = "done"; failed = "failed"

  class JobHandle(BaseModel):
      job_id: str
      queue: str

  class QueuePort(Protocol):
      async def enqueue(self, payload: JobPayload) -> JobHandle: ...
      async def status(self, job_id: str) -> JobStatus | None: ...

  # memory.py
  class InMemoryQueue:
      def __init__(self) -> None: ...
      enqueued: list[JobPayload]                     # 測試斷言用
      async def drain(self, handlers: Mapping[str, Callable[[JobPayload],
                      Awaitable[None]]]) -> None: ...   # 依序執行並清空

  # arq_queue.py
  class ArqQueue:
      def __init__(self, redis_url: str) -> None: ...
      async def close(self) -> None: ...

  # worker.py
  async def run_worker(redis_url: str,
                       handlers: Mapping[str, Callable[[JobPayload], Awaitable[None]]]) -> None: ...
  ```
  `arq` / `redis` 只在 `arq_queue.py`、`worker.py` import。

- [ ] **Step 1: 寫失敗測試**

```python
from uuid import uuid4
from packages.queue import (
    ExportJobV1, InMemoryQueue, JOB_REGISTRY, PlanGenerateJobV1,
)


def test_queue_name_mapping():
    assert PlanGenerateJobV1.queue_name() == "plan.generate"
    assert JOB_REGISTRY["export.push"] is ExportJobV1


def test_payload_is_frozen_and_strict():
    import pytest
    from pydantic import ValidationError
    p = PlanGenerateJobV1(session_id=uuid4())
    with pytest.raises(ValidationError):
        PlanGenerateJobV1(session_id=uuid4(), extra_field=1)


async def test_memory_queue_records_and_drains():
    q = InMemoryQueue()
    sid = uuid4()
    handle = await q.enqueue(PlanGenerateJobV1(session_id=sid))
    assert handle.queue == "plan.generate"
    assert q.enqueued == [PlanGenerateJobV1(session_id=sid)]
    seen: list[str] = []
    await q.drain({"plan.generate": lambda p: _record(seen, p)})
    assert seen == [str(sid)]
    assert q.enqueued == []
```

- [ ] **Step 2: 跑測試確認失敗**
- [ ] **Step 3: 實作**（`uv add arq`；`ArqQueue.enqueue` 以 `queue_name()` 當 arq function name，payload 以 `model_dump(mode="json")` 傳遞；`run_worker` 反查 `JOB_REGISTRY` 還原成 Pydantic model 再交給 handler）
- [ ] **Step 4: 跑測試至 PASS**
- [ ] **Step 5: 寫 README 並 commit** — `feat(queue): QueuePort, versioned job payloads, arq worker runner`

---

## Task 6: DB schema — SQLAlchemy models + 初始 Alembic migration

**Files:**
- Create: `packages/repo/models.py`, `packages/repo/engine.py`
- Create: `migrations/env.py`, `migrations/script.py.mako`, `migrations/versions/0001_initial.py`, `alembic.ini`
- Test: `tests/unit/packages/repo/test_models_metadata.py`

**Interfaces:**
- Produces（PRD 4.1 ERD 的 12 張表，全部 `mapped_column` 型別註記完整）：
  ```python
  class Base(DeclarativeBase): ...

  # 每個 model 的 docstring 第一行必須寫 "Owner: <service>"（PRD 4.2）
  users(id UUID pk, email str unique, google_sub str unique, created_at tstz)
  profiles(user_id UUID pk fk->users, answers JSONB default {}, timezone str default 'UTC', updated_at tstz)
  oauth_connections(id, user_id fk, provider str, encrypted_refresh_token LargeBinary,
                    scopes str, expires_at tstz|null, revoked_at tstz|null, created_at,
                    UNIQUE(user_id, provider))
  imports(id, user_id fk, source str, format str, storage_key str, filename str,
          status str, error str|null, created_at)
  documents(id, import_id fk unique, events JSONB, text_chunks JSONB, created_at)
  role_models(id, kind str, name str, tags ARRAY(str) + GIN index, content JSONB,
              active bool default true, version int default 1, created_at, updated_at)
  plan_sessions(id, user_id fk, trait_role_model_id fk|null, persona_role_model_id fk|null,
                goal Text, intake JSONB default {}, import_ids JSONB default [],
                use_calendar bool default false, status str default 'collecting',
                round int default 0, context_snapshot JSONB|null, error str|null, created_at, updated_at)
  followup_rounds(id, session_id fk, round_no int, questions JSONB, answers JSONB|null,
                  answered_at tstz|null, created_at, UNIQUE(session_id, round_no))
  plans(id, user_id fk, session_id fk, title str, difficulty str, status str default 'draft',
        goal_statement Text, duration_weeks int, start_date Date, deadline Date,
        template JSONB, structure JSONB, activated_at|null, archived_at|null, created_at, updated_at)
  plan_tasks(id, plan_id fk, template_key str, week_index int, phase_index int,
             occurrence int, task_type str, title str, description Text,
             start_at tstz, end_at tstz, all_day bool, status str default 'pending',
             completed_at|null, missed_reason str|null, external_ref str|null,
             synced_at tstz|null, sort_order int,
             UNIQUE(plan_id, template_key, week_index, occurrence),
             INDEX(plan_id, start_at))
  checkins(id, plan_id fk, checkin_date Date, task_results JSONB, note Text|null,
           created_at, UNIQUE(plan_id, checkin_date))
  plan_revisions(id, plan_id fk, trigger str default 'manual', strategy str,
                 trigger_detail JSONB|null, proposed_tasks JSONB|null, diff JSONB|null,
                 rationale Text|null, status str default 'pending', created_at, decided_at|null)
  plan_exports(id, plan_id fk, target str, external_calendar_id str|null,
               last_synced_at tstz|null, status str, error str|null,
               UNIQUE(plan_id, target))
  llm_calls(id, prompt_name str, prompt_version str, provider str, model str, purpose str,
            input_tokens int, output_tokens int, latency_ms int, attempts int,
            degraded bool, job_id str|null, created_at)     # PRD 7.8 觀測

  # engine.py
  def build_engine(database_url: str) -> AsyncEngine: ...
  def build_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]: ...
  ```
  `plan_exports` 與 `llm_calls` 不在 PRD ERD 但由 PRD 5（`GET /plans/{id}/export`）與 7.8 要求，明確納入。

- [ ] **Step 1: 寫失敗測試**

```python
from packages.repo.models import Base

EXPECTED = {
    "users", "profiles", "oauth_connections", "imports", "documents",
    "role_models", "plan_sessions", "followup_rounds", "plans", "plan_tasks",
    "checkins", "plan_revisions", "plan_exports", "llm_calls",
}


def test_all_tables_declared():
    assert set(Base.metadata.tables) == EXPECTED


def test_every_model_declares_owner():
    for mapper in Base.registry.mappers:
        doc = mapper.class_.__doc__ or ""
        assert doc.strip().startswith("Owner:"), mapper.class_.__name__


def test_plan_tasks_unique_constraint():
    cols = {
        tuple(sorted(c.name for c in con.columns))
        for con in Base.metadata.tables["plan_tasks"].constraints
        if con.__class__.__name__ == "UniqueConstraint"
    }
    assert ("occurrence", "plan_id", "template_key", "week_index") in cols
```

- [ ] **Step 2: 跑測試確認失敗**
- [ ] **Step 3: `uv add sqlalchemy asyncpg alembic` 並實作 models.py + engine.py**
- [ ] **Step 4: 跑測試至 PASS**
- [ ] **Step 5: 初始化 Alembic 並產生 migration**

```bash
createdb -h 127.0.0.1 -U postgres guru_core   # 或 docker exec local-postgres createdb -U postgres guru_core
uv run alembic revision --autogenerate -m "initial schema"
uv run alembic upgrade head
uv run alembic check     # 必須回 "No new upgrade operations detected."
```

`migrations/env.py` 要從 `DATABASE_URL` 讀連線字串（同步驅動 `postgresql+psycopg` 或 async 皆可，擇一並在 README 註明）。

- [ ] **Step 6: 手動驗證 schema**

Run: `docker exec local-postgres psql -U postgres -d guru_core -c '\dt'`
Expected: 列出 14 張表 + `alembic_version`

- [ ] **Step 7: commit** — `feat(repo): sqlalchemy models and initial alembic migration`

---

## Task 7: `packages/repo` — Repo Protocols + InMemory + Pg 實作

**Files:**
- Create: `packages/repo/ports.py`, `packages/repo/__init__.py`, `packages/repo/README.md`
- Create: `packages/repo/pg/{__init__,user,profile,oauth,imports,role_model,plan_session,followup,plan,plan_task,checkin,revision,export,llm_call}.py`
- Create: `packages/repo/memory/{同上檔名}.py`
- Test: `tests/unit/packages/repo/test_memory_repos.py`

**Interfaces:**
- Produces（每張表一個 Protocol；**所有使用者資料方法帶 `user_id`**）：
  ```python
  class UserRepo(Protocol):
      async def get_by_google_sub(self, google_sub: str) -> User | None: ...
      async def get(self, user_id: UUID) -> User | None: ...
      async def create(self, email: str, google_sub: str) -> User: ...

  class ProfileRepo(Protocol):
      async def get(self, user_id: UUID) -> Profile | None: ...
      async def upsert(self, user_id: UUID, answers: dict[str, Any], timezone: str) -> Profile: ...

  class OAuthConnectionRepo(Protocol):
      async def get(self, user_id: UUID, provider: str) -> OAuthConnection | None: ...
      async def list_for_user(self, user_id: UUID) -> list[OAuthConnection]: ...
      async def upsert(self, user_id: UUID, provider: str, encrypted_refresh_token: bytes,
                       scopes: str, expires_at: datetime | None) -> OAuthConnection: ...
      async def mark_revoked(self, user_id: UUID, provider: str, at: datetime) -> None: ...

  class ImportRepo(Protocol):
      async def create(self, user_id: UUID, source: str, format: str,
                       storage_key: str, filename: str) -> Import: ...
      async def get(self, user_id: UUID, import_id: UUID) -> Import | None: ...
      async def get_unscoped(self, import_id: UUID) -> Import | None: ...   # worker 專用
      async def list_for_user(self, user_id: UUID) -> list[Import]: ...
      async def set_status(self, import_id: UUID, status: str, error: str | None = None) -> None: ...

  class DocumentRepo(Protocol):
      async def create(self, import_id: UUID, events: list[dict[str, Any]],
                       text_chunks: list[dict[str, Any]]) -> Document: ...
      async def get_by_import(self, import_id: UUID) -> Document | None: ...
      async def list_by_imports(self, import_ids: Sequence[UUID]) -> list[Document]: ...

  class RoleModelRepo(Protocol):
      async def get(self, role_model_id: UUID) -> RoleModel | None: ...
      async def list(self, kind: str | None, tags_any: Sequence[str] | None,
                     tags_all: Sequence[str] | None, active_only: bool = True,
                     limit: int = 50) -> list[RoleModel]: ...
      async def list_tags(self) -> list[str]: ...
      async def upsert(self, role_model_id: UUID | None, kind: str, name: str,
                       tags: list[str], content: dict[str, Any]) -> RoleModel: ...
      async def deactivate(self, role_model_id: UUID) -> None: ...

  class PlanSessionRepo(Protocol):
      async def create(self, user_id: UUID, goal: str, intake: dict[str, Any],
                       import_ids: list[UUID], use_calendar: bool,
                       trait_role_model_id: UUID | None,
                       persona_role_model_id: UUID | None) -> PlanSession: ...
      async def get(self, user_id: UUID, session_id: UUID) -> PlanSession | None: ...
      async def get_unscoped(self, session_id: UUID) -> PlanSession | None: ...
      async def set_status(self, session_id: UUID, status: str, error: str | None = None) -> None: ...
      async def bump_round(self, session_id: UUID) -> int: ...
      async def set_context_snapshot(self, session_id: UUID, snapshot: dict[str, Any]) -> None: ...

  class FollowupRoundRepo(Protocol):
      async def create(self, session_id: UUID, round_no: int,
                       questions: list[dict[str, Any]]) -> FollowupRound: ...
      async def latest(self, session_id: UUID) -> FollowupRound | None: ...
      async def list_for_session(self, session_id: UUID) -> list[FollowupRound]: ...
      async def record_answers(self, round_id: UUID, answers: list[dict[str, Any]],
                               answered_at: datetime) -> None: ...

  class PlanRepo(Protocol):
      async def create_many(self, plans: Sequence[NewPlan]) -> list[Plan]: ...
      async def get(self, user_id: UUID, plan_id: UUID) -> Plan | None: ...
      async def get_unscoped(self, plan_id: UUID) -> Plan | None: ...
      async def list_for_user(self, user_id: UUID, status: str | None) -> list[Plan]: ...
      async def list_for_session(self, session_id: UUID) -> list[Plan]: ...
      async def update_fields(self, plan_id: UUID, **fields: Any) -> Plan: ...
      async def set_status_for_session(self, session_id: UUID, status: str,
                                       exclude_plan_id: UUID) -> None: ...
      async def delete(self, plan_id: UUID) -> None: ...

  class PlanTaskRepo(Protocol):
      async def replace_all(self, plan_id: UUID, tasks: Sequence[NewPlanTask]) -> None: ...
      async def replace_from(self, plan_id: UUID, cutoff: datetime,
                             tasks: Sequence[NewPlanTask]) -> None: ...
      async def list(self, plan_id: UUID, start_from: datetime | None,
                     start_to: datetime | None) -> list[PlanTask]: ...
      async def get(self, plan_id: UUID, task_id: UUID) -> PlanTask | None: ...
      async def update_fields(self, task_id: UUID, **fields: Any) -> PlanTask: ...
      async def bulk_set_status(self, plan_id: UUID,
                                results: Sequence[TaskStatusUpdate]) -> None: ...
      async def counts_by_status(self, plan_id: UUID) -> dict[str, int]: ...
      async def list_dirty(self, plan_id: UUID) -> list[PlanTask]: ...   # synced_at is null 或 < updated

  class CheckinRepo(Protocol):
      async def upsert(self, plan_id: UUID, checkin_date: date,
                       task_results: list[dict[str, Any]], note: str | None) -> Checkin: ...
      async def list_for_plan(self, plan_id: UUID) -> list[Checkin]: ...

  class PlanRevisionRepo(Protocol):
      async def create(self, plan_id: UUID, strategy: str, note: str | None) -> PlanRevision: ...
      async def get(self, plan_id: UUID, revision_id: UUID) -> PlanRevision | None: ...
      async def get_unscoped(self, revision_id: UUID) -> PlanRevision | None: ...
      async def list_for_plan(self, plan_id: UUID) -> list[PlanRevision]: ...
      async def has_open(self, plan_id: UUID) -> bool: ...   # status in (pending, proposed)
      async def set_proposal(self, revision_id: UUID, proposed_tasks: list[dict[str, Any]],
                             diff: list[dict[str, Any]], rationale: str) -> None: ...
      async def set_status(self, revision_id: UUID, status: str,
                           decided_at: datetime | None) -> None: ...

  class PlanExportRepo(Protocol):
      async def get(self, plan_id: UUID, target: str) -> PlanExport | None: ...
      async def list_for_plan(self, plan_id: UUID) -> list[PlanExport]: ...
      async def upsert(self, plan_id: UUID, target: str, status: str,
                       external_calendar_id: str | None, last_synced_at: datetime | None,
                       error: str | None) -> PlanExport: ...
      async def delete(self, plan_id: UUID, target: str) -> None: ...

  class LlmCallRepo(Protocol):
      async def record(self, log: LlmCallLog) -> None: ...
  ```
  回傳型別是 `packages/repo/entities.py` 內的 **frozen Pydantic model**（`User`、`Plan`、`PlanTask`…），不是 ORM 物件——ORM 物件不得跨出 repo 邊界。`NewPlan` / `NewPlanTask` / `TaskStatusUpdate` 是寫入用的 Pydantic input model。

- [ ] **Step 1: 寫失敗測試 `tests/unit/packages/repo/test_memory_repos.py`**

覆蓋每個 InMemory repo 至少一個 round-trip 與一個隔離案例，重點包含：
```python
async def test_plan_repo_scopes_by_user():
    repo = InMemoryPlanRepo()
    [p] = await repo.create_many([_new_plan(user_id=U1)])
    assert await repo.get(U1, p.id) is not None
    assert await repo.get(U2, p.id) is None          # 跨使用者必須讀不到


async def test_plan_task_replace_from_keeps_history():
    # 舊任務 3 筆（過去 1 筆、未來 2 筆），replace_from(cutoff=now) 後
    # 過去那筆仍在，未來兩筆被新的取代
    ...


async def test_revision_has_open_detects_pending_and_proposed():
    ...


async def test_counts_by_status_returns_all_four_keys():
    assert set((await repo.counts_by_status(plan_id)).keys()) == {
        "pending", "done", "missed", "skipped"}
```

- [ ] **Step 2: 跑測試確認失敗**
- [ ] **Step 3: 實作 entities + ports + 全部 InMemory repo，測試轉綠**
- [ ] **Step 4: 實作全部 Pg repo**（同一份 Protocol；`list` 用 SQLAlchemy `select`；`tags_any` 用 `role_models.tags.overlap(...)`，`tags_all` 用 `.contains(...)`）
- [ ] **Step 5: 寫整合測試 `tests/integration/test_pg_repos.py`（標記 `@pytest.mark.integration`，預設 `-m "not integration"` 排除）**，內容為對真實 `guru_core` DB 跑與 InMemory 相同的關鍵案例。在 `pyproject.toml` 加 `addopts = "-q -m 'not integration'"`、`markers = ["integration: needs postgres"]`。
- [ ] **Step 6: 跑 `uv run pytest -m integration tests/integration -v` 至 PASS**
- [ ] **Step 7: 寫 README 並 commit** — `feat(repo): repo protocols with in-memory and postgres adapters`

---

## Task 8: `packages/llm` — Port、設定、prompt registry、FakeLLM

**Files:**
- Create: `packages/llm/{__init__,ports,config,prompts,fake}.py`, `packages/llm/prompts/*.md`, `packages/llm/README.md`
- Create: `config/llm.yaml`
- Create: `tests/fixtures/llm/*.json`
- Test: `tests/unit/packages/llm/{test_config.py,test_prompts.py,test_fake.py}`

**Interfaces:**
- Produces:
  ```python
  # ports.py
  class Purpose(StrEnum):
      evaluate = "evaluate"; generate = "generate"
      revise = "revise"; recommend = "recommend"

  OutputT = TypeVar("OutputT", bound=BaseModel)

  class LLMPort(Protocol):
      async def complete(self, prompt_name: str, context: dict[str, Any],
                         output_schema: type[OutputT], purpose: Purpose) -> OutputT: ...

  class LLMError(RuntimeError): ...
  class LLMSchemaError(LLMError): ...      # 回應無法通過 Pydantic 驗證
  class LLMTransportError(LLMError): ...   # 網路 / HTTP 層

  # config.py
  class ProviderConfig(BaseModel):
      adapter: Literal["openai_compat", "anthropic", "fake"]
      base_url: str | None = None
      api_key: str = "dummy"
      model: str = ""
      structured_output: Literal["guided_json", "json_schema", "tool_use", "prompt"]
      max_context_tokens: int = 16000
      timeout_seconds: int = 180

  class PurposeParams(BaseModel):
      temperature: float
      max_output_tokens: int

  class RetryConfig(BaseModel):
      max_attempts: int = 3

  class LLMConfig(BaseModel):
      provider: ProviderConfig
      params: dict[Purpose, PurposeParams]
      budgets: dict[Purpose, int]
      retry: RetryConfig
      def params_for(self, purpose: Purpose) -> PurposeParams: ...
      def budget_for(self, purpose: Purpose) -> int: ...

  def load_llm_config(path: Path | None = None) -> LLMConfig: ...

  # prompts.py
  class RenderedPrompt(BaseModel):
      name: str
      version: str
      system: str
      user: str

  class PromptRegistry:
      def __init__(self, directory: Path) -> None: ...
      def render(self, name: str, context: dict[str, Any]) -> RenderedPrompt: ...
      def version(self, name: str) -> str: ...
  # 模板格式：YAML frontmatter (--- version: "1" ---) 後接
  # "# SYSTEM\n...\n# USER\n..." 兩段，jinja2 渲染 context

  # fake.py
  class FakeLLM:
      def __init__(self, fixtures_dir: Path,
                   overrides: Mapping[str, Any] | None = None) -> None: ...
      calls: list[tuple[str, Purpose, dict[str, Any]]]   # 測試斷言用
      # 依序找 fixtures_dir/{prompt_name}.json；overrides[prompt_name] 優先
      # 找不到 -> raise LLMError("no fixture for ...")
  ```

- [ ] **Step 1: 建立 `config/llm.yaml`（原文照 PRD 7.4，`adapter` 改為 `${LLM_ADAPTER:-fake}`）**
- [ ] **Step 2: 寫失敗測試**

```python
def test_load_llm_config_defaults(monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "m1")
    cfg = load_llm_config()
    assert cfg.provider.adapter == "fake"
    assert cfg.params_for(Purpose.generate).max_output_tokens == 4000
    assert cfg.budget_for(Purpose.recommend) == 600
    assert cfg.retry.max_attempts == 3


def test_prompt_registry_renders_and_versions(tmp_path):
    (tmp_path / "hello.md").write_text(
        '---\nversion: "3"\n---\n# SYSTEM\nYou are {{ role }}.\n# USER\nGoal: {{ goal }}\n')
    reg = PromptRegistry(tmp_path)
    r = reg.render("hello", {"role": "coach", "goal": "run 5k"})
    assert r.version == "3"
    assert r.system == "You are coach."
    assert r.user == "Goal: run 5k"


async def test_fake_llm_returns_fixture(tmp_path):
    (tmp_path / "evaluate_readiness.json").write_text(
        '{"ready": true, "missing": [], "questions": []}')
    llm = FakeLLM(tmp_path)
    out = await llm.complete("evaluate_readiness", {"goal": "x"},
                             ReadinessOutput, Purpose.evaluate)
    assert out.ready is True
    assert llm.calls[0][0] == "evaluate_readiness"


async def test_fake_llm_missing_fixture_raises(tmp_path):
    with pytest.raises(LLMError, match="no fixture"):
        await FakeLLM(tmp_path).complete("nope", {}, ReadinessOutput, Purpose.evaluate)
```

- [ ] **Step 3: 跑測試確認失敗** → **Step 4: 實作** → **Step 5: 跑至 PASS**
- [ ] **Step 6: 寫 README 並 commit** — `feat(llm): LLMPort, config, prompt registry, FakeLLM`

---

## Task 9: `packages/llm` — 驗證→回灌→降級鏈與觀測（PRD 7.5 / 7.8）

**Files:**
- Create: `packages/llm/validation.py`, `packages/llm/observability.py`
- Modify: `packages/llm/__init__.py`
- Test: `tests/unit/packages/llm/test_validation.py`

**Interfaces:**
- Produces:
  ```python
  # validation.py
  BusinessRule = Callable[[BaseModel], list[str]]   # 回傳違規訊息列，空 list = 通過

  class ValidationOutcome(BaseModel, Generic[OutputT]):
      value: OutputT
      attempts: int
      degraded: bool
      violations: list[str]          # 最後一次仍存在的違規（degraded 時才非空）

  async def complete_validated(
      llm: LLMPort, prompt_name: str, context: dict[str, Any],
      output_schema: type[OutputT], purpose: Purpose, *,
      max_attempts: int,
      rules: Sequence[BusinessRule] = (),
      fallback: Callable[[list[str]], OutputT] | None = None,
  ) -> ValidationOutcome[OutputT]: ...
  # 流程：呼叫 llm.complete → Pydantic 已由 adapter 驗證 → 跑 rules
  #   通過 -> 回傳 (attempts=n, degraded=False)
  #   失敗且 attempts < max_attempts -> 把違規訊息塞進 context["_violations"]
  #                                      與 context["_previous_output"] 再呼叫一次
  #   重試耗盡 -> fallback 存在則回 fallback(violations) 且 degraded=True；
  #               否則 raise LLMValidationExhausted(violations)

  class LLMValidationExhausted(LLMError):
      violations: list[str]

  # observability.py
  class LlmCallLog(BaseModel):
      prompt_name: str; prompt_version: str; provider: str; model: str
      purpose: Purpose; input_tokens: int; output_tokens: int
      latency_ms: int; attempts: int; degraded: bool; job_id: str | None = None

  class LlmObserver(Protocol):
      async def record(self, log: LlmCallLog) -> None: ...

  class NullObserver:  # 只寫 structured log，不落 DB
      async def record(self, log: LlmCallLog) -> None: ...
  ```

- [ ] **Step 1: 寫失敗測試**

```python
class Out(BaseModel):
    n: int


async def test_passes_first_try_when_rules_ok():
    llm = _ScriptedLLM([Out(n=5)])
    r = await complete_validated(llm, "p", {}, Out, Purpose.generate,
                                 max_attempts=3, rules=[lambda o: []])
    assert r.attempts == 1 and r.degraded is False


async def test_retries_with_violations_injected():
    llm = _ScriptedLLM([Out(n=99), Out(n=1)])
    rule = lambda o: [] if o.n < 10 else ["n must be < 10"]
    r = await complete_validated(llm, "p", {}, Out, Purpose.generate,
                                 max_attempts=3, rules=[rule])
    assert r.attempts == 2 and r.value.n == 1
    assert llm.contexts[1]["_violations"] == ["n must be < 10"]
    assert llm.contexts[1]["_previous_output"]["n"] == 99


async def test_degrades_to_fallback_when_exhausted():
    llm = _ScriptedLLM([Out(n=99)] * 3)
    rule = lambda o: ["always bad"]
    r = await complete_validated(llm, "p", {}, Out, Purpose.generate,
                                 max_attempts=3, rules=[rule],
                                 fallback=lambda v: Out(n=0))
    assert r.attempts == 3 and r.degraded is True and r.value.n == 0
    assert r.violations == ["always bad"]


async def test_raises_when_no_fallback():
    with pytest.raises(LLMValidationExhausted):
        await complete_validated(_ScriptedLLM([Out(n=99)] * 2), "p", {}, Out,
                                 Purpose.generate, max_attempts=2,
                                 rules=[lambda o: ["bad"]])
```

- [ ] **Step 2–4: 確認失敗 → 實作 → 轉綠**
- [ ] **Step 5: commit** — `feat(llm): validation-retry-degrade chain and call observability`

---

## Task 10: `packages/llm` — OpenAICompatLLM 與 AnthropicLLM

**Files:**
- Create: `packages/llm/openai_compat.py`, `packages/llm/anthropic_llm.py`
- Modify: `packages/llm/__init__.py`（加 `build_llm(config, prompts, observer) -> LLMPort`）
- Create: `cmd/check_llm.py`
- Test: `tests/unit/packages/llm/test_openai_compat.py`, `test_anthropic.py`, `test_build_llm.py`

**Interfaces:**
- Produces:
  ```python
  class OpenAICompatLLM:
      def __init__(self, config: LLMConfig, prompts: PromptRegistry,
                   observer: LlmObserver,
                   transport: httpx.AsyncBaseTransport | None = None) -> None: ...
  # structured_output 對應：
  #   guided_json  -> body["extra_body"]["guided_json"] = schema  (vLLM/SGLang)
  #   json_schema  -> body["response_format"] = {"type": "json_schema",
  #                     "json_schema": {"name": ..., "schema": ..., "strict": True}}
  #   prompt       -> 把 schema 附在 user 訊息結尾，並要求「只輸出 JSON」
  # 回應：取 choices[0].message.content -> json.loads -> output_schema.model_validate
  #       解析失敗 raise LLMSchemaError；HTTP 非 2xx raise LLMTransportError

  class AnthropicLLM:
      def __init__(self, config: LLMConfig, prompts: PromptRegistry,
                   observer: LlmObserver,
                   transport: httpx.AsyncBaseTransport | None = None) -> None: ...
  # 以 tool use 強制 schema：tools=[{"name": "emit", "input_schema": schema}],
  # tool_choice={"type": "tool", "name": "emit"}；取回應中 tool_use block 的 input

  def build_llm(config: LLMConfig, prompts: PromptRegistry, observer: LlmObserver,
                fixtures_dir: Path | None = None) -> LLMPort: ...
  # adapter=="fake" -> FakeLLM(fixtures_dir); "openai_compat" -> OpenAICompatLLM; ...
  ```
  兩個 adapter 都直接用 `httpx`（`uv add httpx`），不裝 `openai` / `anthropic` SDK——這樣 port 邊界更乾淨，也少兩個相依。**允許在這兩個檔案 import `httpx`。**

- [ ] **Step 1: 寫失敗測試（用 `httpx.MockTransport`，不打外網）**

```python
async def test_openai_compat_uses_guided_json_and_parses():
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(200, json={
            "choices": [{"message": {"content": '{"n": 7}'}}],
            "usage": {"prompt_tokens": 11, "completion_tokens": 3},
        })

    llm = OpenAICompatLLM(_cfg(structured_output="guided_json"), _prompts(),
                          _observer(), transport=httpx.MockTransport(handler))
    out = await llm.complete("p", {"goal": "g"}, Out, Purpose.generate)
    assert out.n == 7
    assert "guided_json" in captured["extra_body"]
    assert captured["temperature"] == 0.4          # 來自 params.generate


async def test_openai_compat_records_observability():
    # observer 收到 input_tokens=11, output_tokens=3, prompt_version 來自模板
    ...


async def test_openai_compat_bad_json_raises_schema_error():
    with pytest.raises(LLMSchemaError):
        ...


async def test_openai_compat_http_500_raises_transport_error():
    with pytest.raises(LLMTransportError):
        ...


async def test_anthropic_uses_tool_use():
    # 送出的 body 有 tools[0].input_schema 與 tool_choice.name == "emit"
    # 回應 {"content":[{"type":"tool_use","name":"emit","input":{"n":7}}],
    #       "usage":{"input_tokens":5,"output_tokens":2}}
    ...


def test_build_llm_selects_adapter_by_config():
    assert isinstance(build_llm(_cfg(adapter="fake"), ..., fixtures_dir=P), FakeLLM)
    assert isinstance(build_llm(_cfg(adapter="openai_compat"), ...), OpenAICompatLLM)
```

- [ ] **Step 2–4: 確認失敗 → 實作 → 轉綠**
- [ ] **Step 5: 寫 `cmd/check_llm.py`**（≤30 行：讀 config → `build_llm` → 對 `smoke` prompt 呼叫一次 → 印出 provider/model/耗時/token）
- [ ] **Step 6: `make check` 全綠後 commit** — `feat(llm): openai-compatible and anthropic adapters`

### M0 驗收

- [ ] `make check` 全綠（ruff + mypy --strict + import-linter + pytest）
- [ ] `uv run alembic check` 回 "No new upgrade operations detected."
- [ ] 六個 port（llm / importers 除外，importers 於 M1）各有正式 + Fake 實作，且測試不起 Docker
- [ ] commit: `chore: M0 skeleton complete`

---

# Phase M1 — 輸入

## Task 11: `packages/importers` — Document 型別、ports、parser registry

**Files:**
- Create: `packages/importers/{__init__,ports,document,registry}.py`, `packages/importers/README.md`
- Create: `packages/importers/sources/{__init__,memory}.py`
- Test: `tests/unit/packages/importers/test_document.py`, `test_registry.py`

**Interfaces:**
- Produces:
  ```python
  # document.py — Plan Engine 唯一認識的匯入格式
  class DocEvent(BaseModel):
      title: str
      start_at: datetime          # timezone-aware
      end_at: datetime
      all_day: bool = False
      location: str | None = None
      source_ref: str | None = None      # 外部事件 id

  class TextChunk(BaseModel):
      text: str
      section: str | None = None         # 例：檔名/工作表名/頁碼
      order: int = 0

  class Document(BaseModel):
      events: list[DocEvent] = []
      text_chunks: list[TextChunk] = []
      def merge(self, other: Document) -> Document: ...   # 供多檔合併

  # ports.py
  class RawBlob(BaseModel):
      data: bytes
      content_type: str
      filename: str

  class SourcePort(Protocol):
      async def fetch(self) -> RawBlob: ...

  class ParserPort(Protocol):
      def supports(self, fmt: str) -> bool: ...
      def parse(self, blob: RawBlob) -> Document: ...

  class UnsupportedFormat(ValueError): ...

  # registry.py
  def detect_format(filename: str, content_type: str) -> str: ...
      # 回 "csv" | "xlsx" | "md" | "html" | "pdf" | "docx" | "ics"
      # 判不出來 -> raise UnsupportedFormat
  class ParserRegistry:
      def __init__(self, parsers: Sequence[ParserPort]) -> None: ...
      def parse(self, blob: RawBlob) -> Document: ...    # 依 detect_format 挑 parser
  def default_registry() -> ParserRegistry: ...

  # sources/memory.py
  class InMemorySource:
      def __init__(self, blob: RawBlob) -> None: ...
  ```

- [ ] **Step 1: 寫失敗測試** — `Document.merge` 合併兩份的 events/text_chunks 且不改動原物件；`detect_format` 對 `("a.csv","text/csv")`、`("a.CSV","application/octet-stream")`、`("a.xlsx", …)`、`("a.md", …)`、`("a.pdf", …)`、`("a.docx", …)`、`("a.ics","text/calendar")` 都正確，對 `("a.exe","application/x-msdownload")` raise `UnsupportedFormat`；`ParserRegistry` 選到對的 parser、選不到時 raise。
- [ ] **Step 2–4: 確認失敗 → 實作 → 轉綠**
- [ ] **Step 5: 寫 README 並 commit** — `feat(importers): document model, ports, parser registry`

---

## Task 12: `packages/importers` — 七個 parser

**Files:**
- Create: `packages/importers/parsers/{__init__,csv_parser,xlsx_parser,markdown_parser,html_parser,pdf_parser,docx_parser,ics_parser}.py`
- Test: `tests/unit/packages/importers/parsers/test_*.py`
- Test fixtures: `tests/fixtures/importers/{sample.csv,sample.xlsx,sample.md,sample.html,sample.pdf,sample.docx,sample.ics}`

**Interfaces:**
- Consumes: `RawBlob`、`Document`、`DocEvent`、`TextChunk`、`ParserPort`（Task 11）
- Produces: `CsvParser`、`XlsxParser`、`MarkdownParser`、`HtmlParser`、`PdfParser`、`DocxParser`、`IcsParser`，皆實作 `ParserPort`。

規則：
- **有時間欄位的列 → `events`，其餘 → `text_chunks`。** CSV/XLSX 若表頭含 `start`/`開始`/`date`/`日期` 且能解析出日期，該列進 `events`（`title` 取第一個非時間欄位），否則整列以 `key: value` 串成一個 `TextChunk`。
- `MarkdownParser` / `HtmlParser`：依標題切段，每段一個 `TextChunk`（`section` 為標題文字）。HTML 去標籤只留文字。
- `PdfParser`：每頁一個 `TextChunk`（`section = f"page {n}"`）。
- `DocxParser`：每個非空段落累積，遇 heading 樣式切段。
- `IcsParser`：每個 `VEVENT` 一個 `DocEvent`，`DTSTART`/`DTEND` 轉 UTC aware datetime，`DTSTART;VALUE=DATE` → `all_day=True`，`UID` → `source_ref`。
- 所有 parser 對空檔案回空 `Document`，不 raise。

依賴：`uv add openpyxl pypdf python-docx beautifulsoup4 icalendar markdown-it-py`

- [ ] **Step 1: 建立七個 fixture 檔**（用小腳本產生 xlsx/pdf/docx，其餘直接寫文字；腳本放 `tests/fixtures/importers/_make_fixtures.py` 並在 README 註明）
- [ ] **Step 2: 為每個 parser 寫失敗測試**，每個至少三個案例：正常解析、空檔案、格式判斷。例：

```python
def test_csv_row_with_date_becomes_event():
    blob = RawBlob(data=b"title,start,end\nGym,2026-09-08T19:00:00Z,2026-09-08T20:00:00Z\n",
                   content_type="text/csv", filename="a.csv")
    doc = CsvParser().parse(blob)
    assert len(doc.events) == 1
    assert doc.events[0].title == "Gym"
    assert doc.events[0].start_at == datetime(2026, 9, 8, 19, tzinfo=UTC)
    assert doc.text_chunks == []


def test_csv_row_without_date_becomes_text_chunk():
    blob = RawBlob(data=b"name,note\nrun,easy pace\n", content_type="text/csv",
                   filename="a.csv")
    doc = CsvParser().parse(blob)
    assert doc.events == []
    assert "easy pace" in doc.text_chunks[0].text


def test_ics_all_day_event():
    doc = IcsParser().parse(_blob("sample.ics"))
    e = next(e for e in doc.events if e.all_day)
    assert e.end_at > e.start_at
```

- [ ] **Step 3–5: 確認失敗 → 逐一實作 → 全部轉綠**
- [ ] **Step 6: 把七個 parser 註冊進 `default_registry()`，補一個 registry 整合測試（每種 fixture 都能經 registry 解析出非空 Document）**
- [ ] **Step 7: commit** — `feat(importers): csv/xlsx/md/html/pdf/docx/ics parsers`

---

## Task 13: API Service 骨架 + Google 登入 + JWT

**Files:**
- Create: `services/api/domain/{__init__,errors.py}`
- Create: `services/api/application/{__init__,ports.py}`
- Create: `services/api/application/login_with_google.py`
- Create: `services/api/adapters/http/{__init__,app.py,deps.py,auth_router.py,schemas.py}`
- Create: `services/api/adapters/google/{__init__,oidc.py}`
- Create: `services/api/container.py`, `services/api/settings.py`, `services/api/README.md`
- Create: `cmd/api_server.py`
- Test: `tests/application/api/test_login_with_google.py`, `tests/unit/api/test_jwt.py`, `tests/application/api/test_auth_endpoint.py`

**Interfaces:**
- Produces:
  ```python
  # services/api/domain/errors.py — 領域錯誤，adapters 對應成 HTTP status
  class DomainError(Exception): ...
  class NotFound(DomainError): ...              # -> 404
  class Forbidden(DomainError): ...             # -> 403
  class Conflict(DomainError): ...              # -> 409
  class InvalidInput(DomainError): ...          # -> 422
  class Unauthorized(DomainError): ...          # -> 401
  class ReauthRequired(DomainError): ...        # -> 409, code="reauth_required"

  # services/api/application/ports.py
  class GoogleIdentity(BaseModel):
      google_sub: str
      email: str

  class GoogleOidcPort(Protocol):
      async def exchange_code(self, code: str, redirect_uri: str) -> GoogleIdentity: ...

  class TokenIssuerPort(Protocol):
      def issue(self, user_id: UUID) -> str: ...
      def verify(self, token: str) -> UUID: ...    # 失效 -> raise Unauthorized

  class ClockPort(Protocol):
      def now(self) -> datetime: ...

  # services/api/application/login_with_google.py
  class LoginWithGoogle:
      def __init__(self, users: UserRepo, profiles: ProfileRepo,
                   oidc: GoogleOidcPort, tokens: TokenIssuerPort) -> None: ...
      async def __call__(self, code: str, redirect_uri: str) -> LoginResult: ...

  class LoginResult(BaseModel):
      access_token: str
      user_id: UUID
      email: str
      is_new_user: bool

  # services/api/adapters/http/deps.py
  async def current_user_id(...) -> UUID: ...   # FastAPI Depends，解析 Bearer JWT

  # services/api/adapters/jwt_issuer.py
  class HmacTokenIssuer:
      def __init__(self, secret: str, ttl_seconds: int, clock: ClockPort) -> None: ...

  # services/api/container.py
  @dataclass(frozen=True)
  class ApiContainer:
      settings: ApiSettings
      # repos
      users: UserRepo; profiles: ProfileRepo; ...（全部 repo）
      # infra ports
      storage: StoragePort; queue: QueuePort; cache: CachePort; clock: ClockPort
      tokens: TokenIssuerPort; oidc: GoogleOidcPort
      # use cases（每個 use case 一個屬性，adapters 只認 container）
      login_with_google: LoginWithGoogle
      ...
  def build_container(settings: ApiSettings | None = None) -> ApiContainer: ...
  def build_test_container(**overrides: Any) -> ApiContainer: ...   # 全 Fake，測試用

  # services/api/settings.py
  class ApiSettings(BaseSettings):   # pydantic-settings，讀 .env
      database_url: str; redis_url: str
      jwt_secret: str; jwt_ttl_seconds: int = 2592000
      storage_backend: Literal["local", "memory", "r2"] = "local"
      storage_local_root: Path = Path("./.data/storage")
      storage_public_base_url: str; storage_signing_secret: str
      google_client_id: str = ""; google_client_secret: str = ""
      google_redirect_uri: str = ""
      oauth_token_enc_key: str = ""
      role_model_base_url: str = "http://127.0.0.1:8001"
      llm_fixtures_dir: Path = Path("tests/fixtures/llm")
  ```

- [ ] **Step 1: 寫失敗測試（use case 層，全 Fake，無 HTTP）**

```python
async def test_first_login_creates_user_and_profile():
    c = build_test_container(oidc=FakeOidc(GoogleIdentity(google_sub="g1", email="a@b.c")))
    r = await c.login_with_google("code", "http://cb")
    assert r.is_new_user is True
    assert await c.users.get_by_google_sub("g1") is not None
    assert (await c.profiles.get(r.user_id)) is not None       # 自動建 profile
    assert c.tokens.verify(r.access_token) == r.user_id


async def test_second_login_reuses_user():
    c = build_test_container(oidc=FakeOidc(GoogleIdentity(google_sub="g1", email="a@b.c")))
    first = await c.login_with_google("code", "http://cb")
    second = await c.login_with_google("code", "http://cb")
    assert second.user_id == first.user_id and second.is_new_user is False


def test_jwt_expired_raises_unauthorized():
    clock = FakeClock(datetime(2026, 1, 1, tzinfo=UTC))
    issuer = HmacTokenIssuer("s", ttl_seconds=60, clock=clock)
    token = issuer.issue(UID)
    clock.advance(seconds=61)
    with pytest.raises(Unauthorized):
        issuer.verify(token)


def test_jwt_tampered_signature_raises():
    ...
```

HTTP 層測試（`httpx.ASGITransport` + `app.dependency_overrides` 注入 test container）：
```python
async def test_post_auth_google_returns_token(client):
    r = await client.post("/v1/auth/google", json={"code": "c", "redirect_uri": "http://cb"})
    assert r.status_code == 200 and "access_token" in r.json()


async def test_protected_endpoint_without_token_is_401(client):
    assert (await client.get("/v1/profile")).status_code == 401
```

- [ ] **Step 2–4: 確認失敗 → 實作（`uv add fastapi uvicorn pyjwt httpx python-multipart`）→ 轉綠**
- [ ] **Step 5: 實作 `GoogleOidc`（httpx 打 `https://oauth2.googleapis.com/token` + 驗證 id_token）與 `FakeGoogleOidc`**
- [ ] **Step 6: 寫 `cmd/api_server.py`（≤30 行：`build_container()` → `create_app(container)` → uvicorn）**
- [ ] **Step 7: 加全域 exception handler：`DomainError` → 對應 status + `{"error": {"code": ..., "message": ...}}`**
- [ ] **Step 8: 寫 `services/api/README.md` 並 commit** — `feat(api): service skeleton, google login, jwt auth`

---

## Task 14: Profile 端點

**Files:**
- Create: `services/api/application/{get_profile.py,update_profile.py}`
- Create: `services/api/adapters/http/profile_router.py`
- Modify: `services/api/container.py`, `services/api/adapters/http/app.py`
- Test: `tests/application/api/test_profile.py`

**Interfaces:**
- Produces:
  ```python
  class ProfileView(BaseModel):
      user_id: UUID
      answers: dict[str, Any]
      timezone: str
      updated_at: datetime

  class GetProfile:
      async def __call__(self, user_id: UUID) -> ProfileView: ...
  class UpdateProfile:
      async def __call__(self, user_id: UUID, answers: dict[str, Any],
                         timezone: str | None) -> ProfileView: ...
      # timezone 需通過 zoneinfo.ZoneInfo 驗證，非法 -> InvalidInput
  ```
  `answers` 對應 PRD 13.2 的 `helpful` 指標鍵（`difficulty_preference`、`accountability`、`time_method`、`past_attempts`、`constraints`），MVP 不強制 schema，只驗證是 dict 且 key 都是 str。

- [ ] **Step 1: 寫失敗測試** — GET 未建 profile 時回預設（`answers={}`、`timezone="UTC"`）；PUT 後 GET 讀回；PUT 非法 timezone 回 422；跨使用者無法讀到別人 profile。
- [ ] **Step 2–4: 確認失敗 → 實作 → 轉綠**
- [ ] **Step 5: commit** — `feat(api): profile endpoints`

---

## Task 15: 檔案上傳匯入（presign → complete → `import.parse` worker）

**Files:**
- Create: `services/api/application/{presign_import.py,complete_import.py,list_imports.py,parse_import.py}`
- Create: `services/api/adapters/http/imports_router.py`
- Create: `services/api/adapters/http/files_router.py`（`LocalFileStorage` 的 presigned PUT/GET 落地端點）
- Create: `services/api/adapters/queue/import_consumer.py`
- Create: `cmd/api_worker.py`
- Modify: `services/api/container.py`, `app.py`
- Test: `tests/application/api/test_imports.py`, `tests/application/api/test_parse_import.py`

**Interfaces:**
- Produces:
  ```python
  class PresignResult(BaseModel):
      import_id: UUID
      upload_url: str
      storage_key: str
      expires_in: int

  class PresignImport:
      MAX_BYTES = 20 * 1024 * 1024
      EXPIRES_IN = 900
      async def __call__(self, user_id: UUID, filename: str, content_type: str,
                         size_bytes: int) -> PresignResult: ...
      # storage_key = f"imports/{user_id}/{import_id}/{safe_filename}"
      # size > MAX_BYTES 或格式不支援 -> InvalidInput
      # 建 imports 列，status="pending"

  class CompleteImport:
      async def __call__(self, user_id: UUID, import_id: UUID) -> ImportView: ...
      # 檢查物件已存在（storage.exists），否則 InvalidInput
      # status="queued"，enqueue ImportParseJobV1(import_id)

  class ParseImport:                       # worker handler，無 user 情境
      def __init__(self, imports: ImportRepo, documents: DocumentRepo,
                   storage: StoragePort, registry: ParserRegistry) -> None: ...
      async def __call__(self, job: ImportParseJobV1) -> None: ...
      # 讀 blob → registry.parse → documents.create → imports.set_status("parsed")
      # UnsupportedFormat / 任何例外 -> set_status("failed", error=str(e))，不重拋

  class ImportView(BaseModel):
      id: UUID; source: str; format: str; filename: str
      status: str; error: str | None; created_at: datetime
      event_count: int = 0; chunk_count: int = 0
  ```

- [ ] **Step 1: 寫失敗測試**

```python
async def test_presign_rejects_oversize():
    with pytest.raises(InvalidInput, match="20"):
        await c.presign_import(U, "a.pdf", "application/pdf", 21 * 1024 * 1024)


async def test_presign_rejects_unsupported_format():
    with pytest.raises(InvalidInput):
        await c.presign_import(U, "a.exe", "application/x-msdownload", 10)


async def test_complete_requires_uploaded_object():
    r = await c.presign_import(U, "a.csv", "text/csv", 100)
    with pytest.raises(InvalidInput):
        await c.complete_import(U, r.import_id)


async def test_complete_enqueues_parse_job():
    r = await c.presign_import(U, "a.csv", "text/csv", 100)
    await c.storage.put(r.storage_key, b"title,start\n", "text/csv")
    await c.complete_import(U, r.import_id)
    assert c.queue.enqueued == [ImportParseJobV1(import_id=r.import_id)]


async def test_parse_import_writes_document():
    ...  # 走完 presign→put→complete→drain，斷言 documents.get_by_import 非 None
         # 且 imports.status == "parsed"


async def test_parse_import_marks_failed_on_bad_content():
    # 上傳一個宣稱 xlsx 但內容是亂碼的檔 → status == "failed" 且 error 非空
    ...


async def test_list_imports_is_user_scoped():
    ...
```

- [ ] **Step 2–4: 確認失敗 → 實作 → 轉綠**
- [ ] **Step 5: 實作 `files_router`**：`PUT /v1/files/{key:path}` 與 `GET /v1/files/{key:path}`，驗證 `exp`/`op`/`sig`（`LocalFileStorage.verify_signature`），簽章錯或過期回 403。加測試：合法簽章可上傳可下載、過期 403、竄改 403。
- [ ] **Step 6: 寫 `cmd/api_worker.py`（≤30 行：`build_container()` → `run_worker(redis_url, {"import.parse": c.parse_import, "export.push": c.push_export})`；`export.push` 於 Task 35 接上，此處先註冊 `parse_import` 一個）**
- [ ] **Step 7: commit** — `feat(api): file upload imports with parse worker`

---

## Task 16: Google OAuth 連線管理 + Google Calendar 匯入

**Files:**
- Create: `services/api/application/{authorize_integration.py,complete_integration.py,list_integrations.py,disconnect_integration.py,import_google_calendar.py}`
- Create: `services/api/adapters/http/integrations_router.py`
- Create: `services/api/adapters/google/{oauth.py,calendar.py}`
- Create: `services/api/adapters/crypto.py`
- Modify: `services/api/container.py`, `imports_router.py`
- Test: `tests/unit/api/test_crypto.py`, `tests/application/api/test_integrations.py`, `tests/application/api/test_google_calendar_import.py`

**Interfaces:**
- Produces:
  ```python
  # application/ports.py 追加
  class OAuthTokens(BaseModel):
      access_token: str
      refresh_token: str | None
      expires_at: datetime | None
      scopes: list[str]

  class GoogleOAuthPort(Protocol):
      def authorize_url(self, state: str, scopes: Sequence[str]) -> str: ...
      async def exchange_code(self, code: str) -> OAuthTokens: ...
      async def refresh(self, refresh_token: str) -> OAuthTokens: ...   # invalid_grant -> ReauthRequired
      async def revoke(self, refresh_token: str) -> None: ...

  class CalendarEvent(BaseModel):
      external_id: str; summary: str
      start_at: datetime; end_at: datetime; all_day: bool

  class CalendarPort(Protocol):
      async def list_events(self, access_token: str, time_min: datetime,
                            time_max: datetime) -> list[CalendarEvent]: ...
      async def create_calendar(self, access_token: str, summary: str) -> str: ...
      async def create_event(self, access_token: str, calendar_id: str,
                             event: CalendarEventWrite) -> str: ...
      async def update_event(self, access_token: str, calendar_id: str,
                             event_id: str, event: CalendarEventWrite) -> None: ...
      async def delete_event(self, access_token: str, calendar_id: str,
                             event_id: str) -> None: ...
      async def delete_calendar(self, access_token: str, calendar_id: str) -> None: ...

  class CalendarEventWrite(BaseModel):
      summary: str; description: str
      start_at: datetime; end_at: datetime; all_day: bool
      color_id: str | None = None
      private_props: dict[str, str] = {}

  class TokenCipherPort(Protocol):
      def encrypt(self, plaintext: str) -> bytes: ...
      def decrypt(self, ciphertext: bytes) -> str: ...

  # adapters/crypto.py
  class FernetTokenCipher:      # cryptography.fernet；key 來自 OAUTH_TOKEN_ENC_KEY
      def __init__(self, key: str) -> None: ...
  class PlainTokenCipher: ...   # 測試用，不加密

  # use cases
  CALENDAR_SCOPES = ["https://www.googleapis.com/auth/calendar.readonly",
                     "https://www.googleapis.com/auth/calendar.events",
                     "https://www.googleapis.com/auth/spreadsheets"]

  class AuthorizeIntegration:
      async def __call__(self, user_id: UUID, provider: str) -> str: ...   # 回 authorize_url
  class CompleteIntegration:
      async def __call__(self, user_id: UUID, provider: str, code: str) -> IntegrationView: ...
  class ListIntegrations:
      async def __call__(self, user_id: UUID) -> list[IntegrationView]: ...
  class DisconnectIntegration:
      async def __call__(self, user_id: UUID, provider: str) -> None: ...

  class IntegrationView(BaseModel):
      provider: str; connected: bool; scopes: list[str]
      needs_reauth: bool; connected_at: datetime | None

  # 給所有需要 Google access token 的地方共用
  class GoogleAccessTokenProvider:
      def __init__(self, oauth_repo: OAuthConnectionRepo, oauth: GoogleOAuthPort,
                   cipher: TokenCipherPort, cache: CachePort, clock: ClockPort) -> None: ...
      async def get(self, user_id: UUID) -> str: ...
      # 用 refresh token 換 access token，結果以 f"gtok:{user_id}" 快取到 expires_at-60s
      # invalid_grant -> 寫 revoked_at 並 raise ReauthRequired

  class ImportGoogleCalendar:
      DEFAULT_WINDOW_DAYS = 90
      async def __call__(self, user_id: UUID, days: int = 90) -> ImportView: ...
      # 建 imports(source="google_calendar", format="ics"), 拉事件 → 直接寫 documents
      # （不走 storage，因為沒有原始檔）→ status="parsed"
  ```

- [ ] **Step 1: 寫失敗測試**

```python
def test_fernet_cipher_roundtrip():
    c = FernetTokenCipher(Fernet.generate_key().decode())
    assert c.decrypt(c.encrypt("refresh-abc")) == "refresh-abc"


async def test_authorize_url_contains_calendar_scopes():
    url = await c.authorize_integration(U, "google")
    assert "calendar.events" in url and "spreadsheets" in url


async def test_callback_stores_encrypted_refresh_token():
    await c.complete_integration(U, "google", "code")
    conn = await c.oauth_connections.get(U, "google")
    assert conn.encrypted_refresh_token != b"refresh-abc"       # 有加密
    assert c.cipher.decrypt(conn.encrypted_refresh_token) == "refresh-abc"


async def test_list_integrations_flags_needs_reauth_after_revoke():
    await c.complete_integration(U, "google", "code")
    await c.oauth_connections.mark_revoked(U, "google", NOW)
    [v] = await c.list_integrations(U)
    assert v.needs_reauth is True and v.connected is False


async def test_access_token_provider_raises_reauth_on_invalid_grant():
    c = build_test_container(google_oauth=FakeOAuth(refresh_raises=InvalidGrant()))
    await c.complete_integration(U, "google", "code")
    with pytest.raises(ReauthRequired):
        await c.google_token_provider.get(U)
    assert (await c.oauth_connections.get(U, "google")).revoked_at is not None


async def test_access_token_is_cached():
    await c.google_token_provider.get(U)
    await c.google_token_provider.get(U)
    assert c.google_oauth.refresh_calls == 1


async def test_import_google_calendar_creates_document_with_events():
    c = build_test_container(calendar=FakeCalendar([CalendarEvent(...)]))
    await c.complete_integration(U, "google", "code")
    view = await c.import_google_calendar(U)
    assert view.status == "parsed" and view.event_count == 1
```

- [ ] **Step 2–4: 確認失敗 → 實作（`uv add cryptography`）→ 轉綠**
- [ ] **Step 5: 實作 `GoogleOAuth` 與 `GoogleCalendar`（httpx，端點 `https://oauth2.googleapis.com/token`、`https://www.googleapis.com/calendar/v3/...`），以 `httpx.MockTransport` 寫 adapter 單元測試**
- [ ] **Step 6: commit** — `feat(api): google oauth connections and calendar import`

### M1 驗收

- [ ] `make check` 全綠
- [ ] 手動冒煙：啟動 `uv run python -m cmd.api_server` 與 `uv run python -m cmd.api_worker`，用 curl 走完 presign → PUT 檔案 → complete → 輪詢 `GET /v1/imports` 直到 `parsed`
- [ ] commit: `chore: M1 inputs complete`

---

# Phase M2 — 計畫引擎

## Task 17: Plan Engine domain — PlanTemplate 型別與 session 狀態機

**Files:**
- Create: `services/plan_engine/domain/{__init__,template.py,session.py,errors.py}`
- Test: `tests/unit/plan_engine/test_template.py`, `tests/unit/plan_engine/test_session.py`

**Interfaces:**
- Produces（PRD 4.3.1 逐欄位對應；**`difficulty` 不在 template 內**）：
  ```python
  # template.py
  class Milestone(BaseModel):
      title: str
      metric: str

  class Phase(BaseModel):
      index: int
      name: str
      week_start: int = Field(ge=0)
      week_end: int = Field(ge=0)
      focus: str
      milestone: Milestone

  DayHint = Literal["mon","tue","wed","thu","fri","sat","sun","any","weekend","weekday"]
  SlotHint = Literal["morning","noon","evening","any"]
  TaskType = Literal["session","habit","checkpoint","rest"]

  class WeeklyItem(BaseModel):
      key: str = Field(pattern=r"^[a-z0-9_]+$")
      title: str
      task_type: TaskType
      day_hint: DayHint
      slot_hint: SlotHint
      duration_minutes: int = Field(ge=5, le=300)
      description: str = ""
      times_per_week: int = Field(default=1, ge=1, le=7)  # habit 每日 -> 7

  class PlanTemplate(BaseModel):
      model_config = ConfigDict(extra="forbid")
      title: str = Field(max_length=40)
      goal_statement: str
      duration_weeks: int = Field(ge=1, le=104)
      assumptions: list[str] = []
      success_criteria: list[str] = Field(min_length=1)
      phases: list[Phase] = Field(min_length=1, max_length=6)
      weekly_template: list[WeeklyItem] = Field(min_length=1, max_length=12)

      @model_validator(mode="after")
      def phases_cover_duration(self) -> PlanTemplate: ...
      # 規則：phases 依 index 遞增、week_start<=week_end、相鄰 phase 連續無縫、
      #      最後一個 phase 的 week_end == duration_weeks - 1；違反 raise ValueError

  # LLM 輸出 wrapper（generate_plans 的 output_schema）
  class PlanTemplateOutput(BaseModel):
      template: PlanTemplate

  # session.py — PRD 3.1 狀態機
  class SessionStatus(StrEnum):
      collecting = "collecting"; evaluating = "evaluating"
      questioning = "questioning"; generating = "generating"
      done = "done"; failed = "failed"

  TRANSITIONS: dict[SessionStatus, frozenset[SessionStatus]] = {
      SessionStatus.collecting:  frozenset({SessionStatus.evaluating, SessionStatus.failed}),
      SessionStatus.evaluating:  frozenset({SessionStatus.questioning,
                                            SessionStatus.generating, SessionStatus.failed}),
      SessionStatus.questioning: frozenset({SessionStatus.evaluating, SessionStatus.failed}),
      SessionStatus.generating:  frozenset({SessionStatus.done, SessionStatus.failed}),
      SessionStatus.done:        frozenset(),
      SessionStatus.failed:      frozenset(),
  }

  class IllegalTransition(ValueError): ...
  def assert_transition(current: SessionStatus, target: SessionStatus) -> None: ...
  def is_terminal(status: SessionStatus) -> bool: ...
  ```

- [ ] **Step 1: 寫失敗測試**

```python
def test_phases_must_cover_full_duration():
    with pytest.raises(ValidationError, match="week_end"):
        PlanTemplate(duration_weeks=12, phases=[_phase(0, 0, 3)], ...)


def test_phases_must_be_contiguous():
    with pytest.raises(ValidationError):
        PlanTemplate(duration_weeks=8, phases=[_phase(0, 0, 3), _phase(1, 5, 7)], ...)


def test_valid_template_accepted():
    t = PlanTemplate(duration_weeks=8,
                     phases=[_phase(0, 0, 3), _phase(1, 4, 7)], ...)
    assert t.duration_weeks == 8


def test_template_rejects_unknown_field():
    with pytest.raises(ValidationError):
        PlanTemplate(difficulty="hard", ...)      # difficulty 不該在 template 內


def test_legal_transition_passes():
    assert_transition(SessionStatus.evaluating, SessionStatus.questioning)


def test_illegal_transition_raises():
    with pytest.raises(IllegalTransition):
        assert_transition(SessionStatus.done, SessionStatus.evaluating)


def test_every_status_has_transition_entry():
    assert set(TRANSITIONS) == set(SessionStatus)
```

- [ ] **Step 2–4: 確認失敗 → 實作 → 轉綠**
- [ ] **Step 5: commit** — `feat(plan-engine): plan template schema and session state machine`

---

## Task 18: Plan Engine domain — 難度推導

**Files:**
- Create: `services/plan_engine/domain/difficulty.py`
- Create: `config/difficulty_coefficients.yaml`
- Test: `tests/unit/plan_engine/test_difficulty.py`

**Interfaces:**
- Produces（PRD 4.3.1.1）：
  ```python
  class Difficulty(StrEnum):
      easy = "easy"; hard = "hard"; extremely_hard = "extremely_hard"

  class DifficultyCoefficients(BaseModel):
      frequency: float; duration: float; weeks: float
      title_suffix: str

  class DifficultyConfig(BaseModel):
      coefficients: dict[Difficulty, DifficultyCoefficients]

  class Pacing(BaseModel):                      # trait role model 的硬約束
      sessions_per_week: tuple[int, int]
      session_minutes: tuple[int, int]
      rest_days_min: int
      progression_rate: float
      missed_policy: Literal["none", "same-week", "next-day"]
      deload_every_weeks: int | None
      intensity_bias: Literal["low", "medium", "high"]

  def derive(base: PlanTemplate, difficulty: Difficulty,
             config: DifficultyConfig, pacing: Pacing | None) -> PlanTemplate: ...
  # 1. weeks = max(1, round(base.duration_weeks * c.weeks))
  # 2. 每個 WeeklyItem：times_per_week = max(1, round(t * c.frequency))
  #                     duration_minutes = max(5, round(d * c.duration))
  # 3. phases 依新 duration_weeks 等比例重算 week_start/week_end（保持連續、覆蓋全期）
  # 4. pacing 非 None 時夾住：
  #    sum(times_per_week for session 類) 夾進 sessions_per_week[min..max]
  #      （超上限時從 times_per_week 最大的項目逐一減 1，直到符合；不足下限時同理加）
  #    每項 duration_minutes 夾進 session_minutes[min..max]
  #    週內排程日數不得超過 7 - rest_days_min（由 Scheduler 再驗一次）
  # 5. title = f"{base.title}{c.title_suffix}"
  # 6. goal_statement / success_criteria / assumptions 原樣沿用（三份必須相同）
  ```

  `config/difficulty_coefficients.yaml`：
  ```yaml
  coefficients:
    easy:           {frequency: 0.6,  duration: 0.75, weeks: 1.25, title_suffix: "（輕鬆）"}
    hard:           {frequency: 1.0,  duration: 1.0,  weeks: 1.0,  title_suffix: "（穩健）"}
    extremely_hard: {frequency: 1.3,  duration: 1.25, weeks: 0.85, title_suffix: "（挑戰）"}
  ```

- [ ] **Step 1: 寫失敗測試**

```python
def test_hard_is_identity_except_title():
    out = derive(BASE, Difficulty.hard, CFG, None)
    assert out.duration_weeks == BASE.duration_weeks
    assert out.weekly_template == BASE.weekly_template
    assert out.title.endswith("（穩健）")


def test_easy_reduces_frequency_and_extends_weeks():
    out = derive(BASE, Difficulty.easy, CFG, None)     # BASE: 12 週, 4 次/週, 40 分
    assert out.duration_weeks == 15
    assert sum(i.times_per_week for i in out.weekly_template) == 2   # round(4*0.6)=2
    assert out.weekly_template[0].duration_minutes == 30             # round(40*0.75)


def test_extremely_hard_capped_by_trait_pacing():
    pacing = Pacing(sessions_per_week=(2, 3), session_minutes=(20, 45), rest_days_min=2,
                    progression_rate=0.05, missed_policy="none",
                    deload_every_weeks=None, intensity_bias="low")
    out = derive(BASE, Difficulty.extremely_hard, CFG, pacing)
    assert sum(i.times_per_week for i in out.weekly_template
               if i.task_type == "session") <= 3
    assert all(i.duration_minutes <= 45 for i in out.weekly_template)


def test_all_three_share_goal_and_criteria():
    outs = [derive(BASE, d, CFG, None) for d in Difficulty]
    assert len({o.goal_statement for o in outs}) == 1
    assert len({tuple(o.success_criteria) for o in outs}) == 1


def test_phases_remain_contiguous_after_scaling():
    out = derive(BASE, Difficulty.easy, CFG, None)
    assert out.phases[0].week_start == 0
    assert out.phases[-1].week_end == out.duration_weeks - 1
    for a, b in zip(out.phases, out.phases[1:]):
        assert b.week_start == a.week_end + 1


def test_derive_never_produces_zero_frequency():
    base = _base(times_per_week=1)
    out = derive(base, Difficulty.easy, CFG, None)
    assert all(i.times_per_week >= 1 for i in out.weekly_template)
```

- [ ] **Step 2–4: 確認失敗 → 實作 → 轉綠**
- [ ] **Step 5: commit** — `feat(plan-engine): difficulty derivation with pacing clamps`

---

## Task 19: Plan Engine domain — Scheduler

**Files:**
- Create: `services/plan_engine/domain/{scheduler.py,capacity.py}`
- Create: `config/scheduler.yaml`
- Test: `tests/unit/plan_engine/test_scheduler.py`（本 task 測試數量最多，是整個系統回歸防線的主力）

**Interfaces:**
- Produces（PRD 4.3.2）：
  ```python
  # capacity.py
  class TimeWindow(BaseModel):
      start_minute: int      # 自當日 00:00 起算的分鐘數
      end_minute: int

  class Capacity(BaseModel):
      timezone: str = "UTC"
      # weekday(0=Mon..6=Sun) -> slot -> 可用區間
      slots: dict[int, dict[SlotHint, list[TimeWindow]]] = {}
      def windows(self, weekday: int, slot: SlotHint) -> list[TimeWindow]: ...
      @classmethod
      def default(cls, timezone: str) -> Capacity: ...
      # 預設：每天 morning 07:00–09:00、noon 12:00–13:00、evening 19:00–22:00

  class BusyBlock(BaseModel):
      start_at: datetime
      end_at: datetime

  # scheduler.py
  class SchedulerConfig(BaseModel):
      default_start: Literal["next_monday", "tomorrow"] = "next_monday"
      min_gap_minutes: int = 30              # 兩個任務之間最小間隔
      max_shift_days: int = 3                # 衝突時最多往後找幾天（仍在同週內）
      checkpoint_hour: int = 0               # checkpoint 為全天
      slot_order: list[SlotHint] = ["morning", "evening", "noon", "any"]

  class ScheduledTask(BaseModel):
      template_key: str; week_index: int; phase_index: int; occurrence: int
      task_type: TaskType; title: str; description: str
      start_at: datetime; end_at: datetime; all_day: bool; sort_order: int

  class PacingViolation(BaseModel):
      week_index: int
      rule: Literal["sessions_per_week_max", "sessions_per_week_min", "rest_days_min",
                    "session_minutes"]
      detail: str

  class ScheduleResult(BaseModel):
      tasks: list[ScheduledTask]
      violations: list[PacingViolation]
      unplaced: list[str]        # 找不到空檔的 template_key，會寫入 assumptions

  def schedule(template: PlanTemplate, *, start_date: date, capacity: Capacity,
               busy: Sequence[BusyBlock], pacing: Pacing | None,
               config: SchedulerConfig) -> ScheduleResult: ...
  ```

  排程規則（照 PRD 4.3.2，逐條實作）：
  1. 第 0 週起於 `start_date`（預設下週一），共 `duration_weeks` 週。
  2. 每週依 `weekly_template` 展開；`times_per_week > 1` 時 `occurrence` 從 0 遞增。
  3. `day_hint` 決定候選星期（`any` → 週一~日；`weekday` → 一~五；`weekend` → 六日；具體星期 → 該日）。多次出現時在候選日中盡量分散（取間隔最大的排列）。
  4. `slot_hint` 決定當日候選區間；`any` 依 `config.slot_order` 逐一嘗試。
  5. 在候選區間內找第一個能容納 `duration_minutes` 且與已排任務、`busy` 皆保持 `min_gap_minutes` 的位置。
  6. 找不到 → 往後一天再試，最多 `max_shift_days` 天且不得跨出該週；仍失敗 → 記入 `unplaced`，不產生該任務。
  7. 每個 phase 的最後一週的週日加一個 `checkpoint` 全天任務，`title = phase.milestone.title`，`description = phase.milestone.metric`，`template_key = f"checkpoint_p{phase.index}"`。
  8. `rest` 類任務不排具體時間，產生全天任務。
  9. `pacing` 非 None 時逐週檢查：`session` 類任務數 > `sessions_per_week[1]` → `sessions_per_week_max` 違規；< `[0]` → `sessions_per_week_min`；當週有任務的天數 > `7 - rest_days_min` → `rest_days_min` 違規；任一任務時長超出 `session_minutes` → `session_minutes` 違規。違規只記錄在 `violations`，**不 raise**——由 use case 決定是否回灌 LLM 重試。
  10. `sort_order` 依 `start_at` 遞增，同時間依 `template_key` 字典序。
  11. 全部時間為 aware datetime，以 `capacity.timezone` 計算當地時刻後轉 UTC 儲存。

- [ ] **Step 1: 寫失敗測試（至少 18 個案例）**

```python
def test_week_zero_starts_on_given_date(): ...
def test_duration_weeks_produces_that_many_weeks():
    r = schedule(_tpl(duration_weeks=4, items=[_item("run", "tue", "evening", 30)]), ...)
    assert {t.week_index for t in r.tasks if t.template_key == "run"} == {0, 1, 2, 3}

def test_day_hint_specific_weekday_lands_on_that_weekday(): ...
def test_day_hint_weekday_never_lands_on_weekend(): ...
def test_day_hint_weekend_only_lands_on_sat_or_sun(): ...
def test_times_per_week_three_spreads_across_week():
    # 3 次 any → 三天不同，且兩兩間隔 >= 1 天
    ...
def test_slot_hint_morning_lands_in_morning_window(): ...
def test_slot_hint_any_falls_back_through_slot_order(): ...
def test_busy_block_is_avoided():
    busy = [BusyBlock(start_at=..., end_at=...)]      # 佔滿 evening 前半
    r = schedule(..., busy=busy)
    assert all(not _overlaps(t, busy[0]) for t in r.tasks)

def test_min_gap_between_two_tasks_respected(): ...
def test_conflict_shifts_to_next_day_within_week(): ...
def test_unplaceable_task_recorded_in_unplaced_not_raised():
    r = schedule(_tpl(items=[_item("run", "tue", "morning", 240)]),
                 capacity=_capacity_with_only_30min_morning(), ...)
    assert "run" in r.unplaced and r.tasks == []

def test_checkpoint_added_on_last_sunday_of_each_phase():
    r = schedule(_tpl(duration_weeks=8, phases=[_p(0,0,3), _p(1,4,7)]), ...)
    cps = [t for t in r.tasks if t.task_type == "checkpoint"]
    assert len(cps) == 2
    assert all(t.all_day for t in cps)
    assert cps[0].week_index == 3 and cps[1].week_index == 7
    assert cps[0].start_at.weekday() == 6

def test_rest_task_is_all_day(): ...

def test_pacing_max_violation_recorded():
    pacing = Pacing(sessions_per_week=(2, 3), ...)
    r = schedule(_tpl(items=[_item("a", "any", "any", 30, times=5)]), pacing=pacing, ...)
    assert any(v.rule == "sessions_per_week_max" for v in r.violations)

def test_pacing_rest_days_violation_recorded():
    pacing = Pacing(..., rest_days_min=2)
    # 一週排 6 天 -> 只休 1 天 -> 違規
    ...

def test_no_violations_when_within_pacing(): ...

def test_sort_order_is_monotonic_by_start_at():
    r = schedule(...)
    ordered = sorted(r.tasks, key=lambda t: t.sort_order)
    assert [t.start_at for t in ordered] == sorted(t.start_at for t in r.tasks)

def test_unique_key_tuple_never_repeats():
    r = schedule(...)
    keys = [(t.template_key, t.week_index, t.occurrence) for t in r.tasks]
    assert len(keys) == len(set(keys))

def test_timezone_conversion_produces_local_morning():
    cap = Capacity.default("Asia/Taipei")
    r = schedule(_tpl(items=[_item("run", "tue", "morning", 30)]), capacity=cap, ...)
    local = r.tasks[0].start_at.astimezone(ZoneInfo("Asia/Taipei"))
    assert 7 <= local.hour < 9
```

- [ ] **Step 2: 跑測試確認全部失敗**
- [ ] **Step 3: 實作 `capacity.py` 與 `scheduler.py`，逐個測試轉綠**
- [ ] **Step 4: 全部 PASS 後跑 `uv run mypy services/plan_engine/domain --strict`**
- [ ] **Step 5: commit** — `feat(plan-engine): deterministic scheduler`

---

## Task 20: Plan Engine domain — 修訂 diff

**Files:**
- Create: `services/plan_engine/domain/diff.py`
- Test: `tests/unit/plan_engine/test_diff.py`

**Interfaces:**
- Produces（PRD 3.8 / 4.3.6）：
  ```python
  DiffKind = Literal["added", "moved", "removed", "shortened", "lengthened",
                     "reduced", "unchanged"]

  class TaskDiffEntry(BaseModel):
      template_key: str; week_index: int; occurrence: int
      kind: DiffKind
      title: str
      before: TaskSnapshot | None
      after: TaskSnapshot | None

  class TaskSnapshot(BaseModel):
      title: str; start_at: datetime; end_at: datetime; all_day: bool

  def diff_tasks(before: Sequence[ScheduledTask] | Sequence[TaskSnapshotWithKey],
                 after: Sequence[ScheduledTask]) -> list[TaskDiffEntry]: ...
  # 以 (template_key, week_index, occurrence) 對齊：
  #   只在 after -> added；只在 before -> removed
  #   兩邊都有：start_at 不同 -> moved；時長變短 -> shortened；變長 -> lengthened
  #             （同時位移與變長度時 kind 取 "moved"，並在 before/after 呈現完整快照）
  #             完全相同 -> unchanged
  # 排序：week_index, template_key, occurrence
  ```

- [ ] **Step 1: 寫失敗測試** — 涵蓋 added / removed / moved / shortened / lengthened / unchanged 各一，加上「同時位移且縮短時 kind == moved」、「輸出依 week_index 排序」、「空 before 時全部 added」、「空 after 時全部 removed」。
- [ ] **Step 2–4: 確認失敗 → 實作 → 轉綠**
- [ ] **Step 5: commit** — `feat(plan-engine): task diff by stable key`

---

## Task 21: Readiness 設定與四支 prompt 模板

**Files:**
- Create: `config/readiness_metrics.yaml`（**原文照抄 PRD 13.2，不得改寫或精簡**）
- Create: `services/plan_engine/domain/readiness.py`
- Create: `packages/llm/prompts/{evaluate_readiness.md,generate_plans.md,revise_plan.md,recommend_role_model.md,smoke.md}`
- Create: `tests/fixtures/llm/{evaluate_readiness.json,generate_plans.json,revise_plan.json,recommend_role_model.json}`
- Test: `tests/unit/plan_engine/test_readiness_config.py`, `tests/unit/packages/llm/test_prompt_templates.py`

**Interfaces:**
- Produces:
  ```python
  # readiness.py
  class MetricSpec(BaseModel):
      id: str; name: str
      fills: str | None = None
      check: str
      bad_example: str | None = None
      good_example: str | None = None
      default: str | None = None
      note: str | None = None

  class DomainProbeSpec(BaseModel):
      id: str; name: str; max_items: int
      instruction: str
      examples_for_llm: list[str]
      note: str

  class ReadinessConfig(BaseModel):
      version: int
      max_followup_rounds: int
      max_questions_per_round: int
      options_per_question: int
      ask_order: list[str]
      required: list[MetricSpec]
      domain_probe: DomainProbeSpec
      helpful: list[MetricSpec]
      ready_rule: str
      force_generate_rule: str
      def required_ids(self) -> list[str]: ...

  def load_readiness_config(path: Path | None = None) -> ReadinessConfig: ...

  # LLM 輸出 schema（evaluate_readiness 的 output_schema）
  class FollowupOption(BaseModel):
      text: str

  class FollowupQuestion(BaseModel):
      id: str
      metric_id: str
      text: str
      options: list[str] = Field(min_length=3, max_length=3)
      allow_custom: bool = True
      allow_skip: bool = True

  class ReadinessOutput(BaseModel):
      model_config = ConfigDict(extra="forbid")
      ready: bool
      missing: list[str] = []
      questions: list[FollowupQuestion] = Field(default=[], max_length=5)

  # 業務規則（給 complete_validated 用）
  def readiness_rules(cfg: ReadinessConfig, asked_metric_ids: Set[str]) -> list[BusinessRule]: ...
  # 規則：
  #  - ready=False 時 questions 不得為空
  #  - ready=True 時 missing 必須為空
  #  - 每個 question.metric_id 必須存在於 required/helpful/domain_probe 的 id 集合
  #  - 同一輪不得對同一 metric_id 出兩題
  #  - 第 2 輪不得重問第 1 輪已問過的 metric_id（asked_metric_ids）
  #  - options 恰好 3 個且互不相同、每個非空
  ```

  Prompt 模板要求（`evaluate_readiness.md`）：
  - frontmatter `version: "1"`
  - SYSTEM 段：說明角色是「計畫可行性評估器」，只輸出 JSON。
  - USER 段（jinja2）依序放：使用者目標 `{{ goal }}`、intake、已解析文件摘要、role model context、已問過的題目與答案、**指標清單（由 `readiness_metrics.yaml` 渲染）**。
  - **最後一段**（PRD 7.6 第 2 點）放硬約束：最多 5 題、每題恰好 3 個依 context 客製的選項（附 PRD 13.3 的好壞對照例）、一題只補一個指標、不得重問、輸出 schema、以及 `{% if _violations %}上一次輸出的問題：{{ _violations }}，只修正這些欄位{% endif %}`。

  `generate_plans.md` 同結構，最後一段包含：只產一份基準模板、不得含 `difficulty` 欄位、phases 必須連續覆蓋 `duration_weeks`、`weekly_template` 的 `key` 用小寫底線、pacing 約束句（若有 trait）、輸出 schema。

- [ ] **Step 1: 寫失敗測試**

```python
def test_readiness_config_loads_all_four_required():
    cfg = load_readiness_config()
    assert cfg.required_ids() == ["goal_outcome", "horizon", "capacity", "baseline"]
    assert cfg.max_followup_rounds == 2
    assert cfg.max_questions_per_round == 5
    assert cfg.options_per_question == 3


def test_readiness_rule_rejects_empty_questions_when_not_ready():
    rules = readiness_rules(cfg, asked_metric_ids=set())
    out = ReadinessOutput(ready=False, missing=["capacity"], questions=[])
    assert any("questions" in v for r in rules for v in r(out))


def test_readiness_rule_rejects_unknown_metric_id(): ...
def test_readiness_rule_rejects_duplicate_metric_in_round(): ...
def test_readiness_rule_rejects_repeat_of_previous_round(): ...
def test_readiness_rule_rejects_non_distinct_options(): ...
def test_readiness_rule_passes_valid_output(): ...


def test_all_prompts_render_without_error():
    reg = PromptRegistry(Path("packages/llm/prompts"))
    for name in ["evaluate_readiness", "generate_plans", "revise_plan",
                 "recommend_role_model", "smoke"]:
        r = reg.render(name, _full_context())
        assert r.system and r.user and r.version


def test_constraints_appear_at_end_of_user_prompt():
    r = PromptRegistry(Path("packages/llm/prompts")).render("generate_plans", _full_context())
    tail = r.user[-800:]
    assert "duration_weeks" in tail and "difficulty" in tail


def test_fixtures_validate_against_output_schemas():
    ReadinessOutput.model_validate_json(
        Path("tests/fixtures/llm/evaluate_readiness.json").read_text())
    PlanTemplateOutput.model_validate_json(
        Path("tests/fixtures/llm/generate_plans.json").read_text())
```

- [ ] **Step 2–4: 確認失敗 → 實作（fixtures 用 PRD 4.3.7 的 5K 跑步範例，補齊成合法 template）→ 轉綠**
- [ ] **Step 5: commit** — `feat(plan-engine): readiness config, output schemas, prompt templates`

---

## Task 22: Plan Engine — 評估與追問 use case

**Files:**
- Create: `services/plan_engine/application/{__init__,ports.py,context_builder.py,evaluate_session.py}`
- Create: `services/plan_engine/settings.py`, `services/plan_engine/container.py`, `services/plan_engine/README.md`
- Test: `tests/application/plan_engine/test_evaluate_session.py`

**Interfaces:**
- Produces:
  ```python
  # context_builder.py
  class SessionContext(BaseModel):
      goal: str
      intake: dict[str, Any]
      timezone: str
      profile_answers: dict[str, Any]
      documents_summary: list[str]        # 每個 text_chunk 截斷後的摘要行
      existing_events: list[DocEvent]
      use_calendar: bool
      trait_context: str                  # RoleModelRenderer 產出的 markdown，可為 ""
      persona_context: str
      previous_rounds: list[dict[str, Any]]   # [{round_no, questions, answers}]
      metrics_yaml: str                   # readiness_metrics.yaml 的渲染文字

  class ContextBuilder:
      def __init__(self, sessions: PlanSessionRepo, profiles: ProfileRepo,
                   documents: DocumentRepo, followups: FollowupRoundRepo,
                   role_models: RoleModelRepo, renderer: RoleModelRenderer,
                   readiness: ReadinessConfig) -> None: ...
      async def build(self, session_id: UUID, purpose: Purpose) -> SessionContext: ...

  # evaluate_session.py — 處理 plan.generate 與 plan.continue 兩個 job
  class EvaluateSession:
      def __init__(self, sessions: PlanSessionRepo, followups: FollowupRoundRepo,
                   context_builder: ContextBuilder, llm: LLMPort,
                   readiness: ReadinessConfig, generate_plans: GeneratePlans,
                   cache: CachePort, max_attempts: int) -> None: ...
      async def __call__(self, job: PlanGenerateJobV1 | PlanContinueJobV1) -> None: ...
  ```

  行為（PRD 3.1 / 3.4）：
  1. 讀 session；`status` 為終態則直接 return（冪等）。
  2. `set_status(evaluating)`（先 `assert_transition`）。
  3. `context_builder.build(..., Purpose.evaluate)`，寫入 `context_snapshot`。
  4. `complete_validated(llm, "evaluate_readiness", ctx, ReadinessOutput, Purpose.evaluate, max_attempts=cfg.retry.max_attempts, rules=readiness_rules(...), fallback=lambda v: ReadinessOutput(ready=True, missing=[], questions=[]))` — 降級即視為 ready，直接進生成並在 assumptions 標註。
  5. `ready == True` 或 `session.round >= max_followup_rounds` → `set_status(generating)` 並直接 `await generate_plans(session_id, forced_missing=out.missing, degraded=outcome.degraded)`。
  6. 否則 → `followups.create(session_id, round_no=session.round, questions=...)`、`bump_round()`、`set_status(questioning)`。
  7. 任何未預期例外 → `set_status(failed, error=...)` 並重拋（讓 ARQ 記錄）。
  8. 每次狀態變更同時寫 Redis 快取 `session:{id}:status`（TTL 1 小時）——**權威值仍在 DB**。

- [ ] **Step 1: 寫失敗測試**

```python
async def test_ready_true_goes_straight_to_generating():
    c = build_engine_test_container(llm=FakeLLM(overrides={
        "evaluate_readiness": {"ready": True, "missing": [], "questions": []}}))
    sid = await _seed_session(c, goal="12 週跑進 30 分")
    await c.evaluate_session(PlanGenerateJobV1(session_id=sid))
    s = await c.sessions.get_unscoped(sid)
    assert s.status == "done"                 # generate_plans 已同步跑完
    assert len(await c.plans.list_for_session(sid)) == 3


async def test_not_ready_creates_followup_round_and_questions():
    c = build_engine_test_container(llm=FakeLLM(overrides={
        "evaluate_readiness": {"ready": False, "missing": ["capacity"],
                               "questions": [_q("q1", "capacity")]}}))
    sid = await _seed_session(c)
    await c.evaluate_session(PlanGenerateJobV1(session_id=sid))
    s = await c.sessions.get_unscoped(sid)
    assert s.status == "questioning" and s.round == 1
    r = await c.followups.latest(sid)
    assert r.round_no == 0 and len(r.questions) == 1


async def test_second_round_then_force_generate():
    # round 已達 max_followup_rounds=2 時，即使 ready=False 也進 generating
    c = build_engine_test_container(llm=FakeLLM(overrides={
        "evaluate_readiness": {"ready": False, "missing": ["baseline"],
                               "questions": [_q("q1", "baseline")]}}))
    sid = await _seed_session(c, round=2)
    await c.evaluate_session(PlanContinueJobV1(session_id=sid))
    assert (await c.sessions.get_unscoped(sid)).status == "done"
    plan = (await c.plans.list_for_session(sid))[0]
    assert any("系統假設" in a or "假設" in a for a in plan.structure["assumptions"])


async def test_previous_answers_reach_the_prompt_context():
    # 第一輪答完後跑 plan.continue，斷言 FakeLLM.calls[-1] 的 context
    # previous_rounds[0]["answers"] 有那筆答案
    ...


async def test_terminal_session_is_noop():
    sid = await _seed_session(c, status="done")
    await c.evaluate_session(PlanGenerateJobV1(session_id=sid))
    assert c.llm.calls == []


async def test_llm_failure_marks_session_failed():
    c = build_engine_test_container(llm=RaisingLLM(LLMTransportError("boom")))
    sid = await _seed_session(c)
    with pytest.raises(LLMTransportError):
        await c.evaluate_session(PlanGenerateJobV1(session_id=sid))
    assert (await c.sessions.get_unscoped(sid)).status == "failed"


async def test_status_is_mirrored_to_cache():
    ...
```

- [ ] **Step 2–4: 確認失敗 → 實作 → 轉綠**（`RoleModelRenderer` 於 Task 27 才實作，此 task 先用回傳空字串的 `NullRoleModelRenderer` 佔位，Task 28 換掉）
- [ ] **Step 5: commit** — `feat(plan-engine): readiness evaluation and follow-up loop`

---

## Task 23: Plan Engine — 生成三份計畫 use case

**Files:**
- Create: `services/plan_engine/application/generate_plans.py`
- Test: `tests/application/plan_engine/test_generate_plans.py`

**Interfaces:**
- Produces:
  ```python
  class GeneratePlans:
      def __init__(self, sessions: PlanSessionRepo, plans: PlanRepo,
                   plan_tasks: PlanTaskRepo, documents: DocumentRepo,
                   role_models: RoleModelRepo, context_builder: ContextBuilder,
                   llm: LLMPort, difficulty_config: DifficultyConfig,
                   scheduler_config: SchedulerConfig, clock: ClockPort,
                   max_attempts: int) -> None: ...
      async def __call__(self, session_id: UUID, *, forced_missing: Sequence[str] = (),
                         degraded: bool = False) -> list[UUID]: ...
  ```

  行為（PRD 4.3 / 7.5）：
  1. 建 context（`Purpose.generate`）。
  2. `complete_validated(..., "generate_plans", ..., PlanTemplateOutput, Purpose.generate, rules=[_schedulable_rule], fallback=_conservative_template)`。
     - `_schedulable_rule(out)`：對 `out.template` 用 `hard` 係數 + trait pacing 跑一次 `schedule()`，把 `violations` 的 `detail` 與 `unplaced` 轉成違規訊息回灌。這就是 PRD 7.5 的「業務規則檢查」。
     - `_conservative_template()`：每週 3 次 × 40 分、三階段線性、12 週，`assumptions` 加上「以下項目為系統假設，建議補完後重新規劃」與 `forced_missing` 的缺項說明。
  3. 對 `Difficulty` 三個值各跑 `derive()` → `schedule()`。
  4. `assumptions` 累加：LLM 原有的 + `use_calendar=False` 時加「未參考既有行事曆」 + `unplaced` 的說明 + degraded 時的系統假設提示。
  5. 一次 `plans.create_many()` 建三列（`status="draft"`，`start_date` 依 `scheduler_config.default_start`，`deadline = start_date + duration_weeks*7 - 1`），再對每份 `plan_tasks.replace_all()`。
  6. `sessions.set_status(done)`。
  7. 任一步失敗 → `set_status(failed)` 並重拋。

- [ ] **Step 1: 寫失敗測試**

```python
async def test_generates_exactly_three_plans_one_per_difficulty():
    ids = await c.generate_plans(sid)
    plans = await c.plans.list_for_session(sid)
    assert len(ids) == 3
    assert {p.difficulty for p in plans} == {"easy", "hard", "extremely_hard"}
    assert all(p.status == "draft" for p in plans)


async def test_three_plans_share_goal_statement_and_criteria():
    plans = await c.plans.list_for_session(sid)
    assert len({p.goal_statement for p in plans}) == 1
    assert len({tuple(p.structure["success_criteria"]) for p in plans}) == 1


async def test_easy_plan_has_more_weeks_than_hard():
    by = {p.difficulty: p for p in await c.plans.list_for_session(sid)}
    assert by["easy"].duration_weeks > by["hard"].duration_weeks
    assert by["extremely_hard"].duration_weeks < by["hard"].duration_weeks


async def test_plan_tasks_are_created_with_absolute_times():
    plan = ...
    tasks = await c.plan_tasks.list(plan.id, None, None)
    assert tasks and all(t.start_at.tzinfo is not None for t in tasks)
    assert all(t.end_at > t.start_at or t.all_day for t in tasks)


async def test_template_stored_verbatim_for_revision():
    plan = ...
    assert PlanTemplate.model_validate(plan.template).goal_statement == plan.goal_statement


async def test_pacing_violation_triggers_retry_with_feedback():
    # trait pacing 每週最多 3 次；FakeLLM 第一次回 6 次/週的模板，第二次回 3 次/週
    c = build_engine_test_container(llm=_ScriptedLLM([_tpl(times=6), _tpl(times=3)]))
    await c.generate_plans(sid)
    assert c.llm.contexts[1]["_violations"]          # 違規訊息有回灌
    plan = ...
    assert len([t for t in tasks if t.week_index == 0
                and t.task_type == "session"]) <= 3


async def test_degrades_to_conservative_template_when_retries_exhausted():
    c = build_engine_test_container(llm=_AlwaysBadLLM())
    await c.generate_plans(sid)
    plan = (await c.plans.list_for_session(sid))[0]
    assert plan.duration_weeks in (12, 15, 10)       # 12 週基準經三難度縮放
    assert any("系統假設" in a for a in plan.structure["assumptions"])


async def test_assumption_added_when_calendar_not_connected():
    plan = ...
    assert any("行事曆" in a for a in plan.structure["assumptions"])


async def test_deadline_matches_duration():
    plan = ...
    assert (plan.deadline - plan.start_date).days == plan.duration_weeks * 7 - 1


async def test_session_ends_in_done():
    assert (await c.sessions.get_unscoped(sid)).status == "done"
```

- [ ] **Step 2–4: 確認失敗 → 實作 → 轉綠**
- [ ] **Step 5: commit** — `feat(plan-engine): generate three difficulty plans with scheduling`

---

## Task 24: Plan Engine worker 接線 + plan-session HTTP 端點 + 端到端

**Files:**
- Create: `services/plan_engine/adapters/queue/consumers.py`
- Create: `cmd/plan_engine_worker.py`
- Create: `services/api/application/{create_plan_session.py,get_plan_session.py,submit_answers.py,get_job.py}`
- Create: `services/api/adapters/http/{plan_sessions_router.py,jobs_router.py}`
- Modify: `services/api/container.py`, `app.py`
- Test: `tests/application/api/test_plan_sessions.py`, `tests/application/test_end_to_end_generate.py`

**Interfaces:**
- Produces:
  ```python
  class CreatePlanSession:
      async def __call__(self, user_id: UUID, goal: str, intake: dict[str, Any],
                         import_ids: Sequence[UUID],
                         trait_role_model_id: UUID | None,
                         persona_role_model_id: UUID | None) -> CreateSessionResult: ...
      # goal 空字串 -> InvalidInput；import_ids 必須全部屬於該 user 且 status=="parsed"
      # use_calendar = 該 user 是否有 google 連線且未 revoked
      # enqueue PlanGenerateJobV1

  class CreateSessionResult(BaseModel):
      session_id: UUID
      job_id: str

  class PlanSessionView(BaseModel):
      id: UUID; status: str; round: int; goal: str
      questions: list[FollowupQuestion] = []      # status==questioning 時填
      plans: list[PlanSummary] = []               # status==done 時填
      error: str | None = None

  class PlanSummary(BaseModel):
      id: UUID; title: str; difficulty: str; status: str
      duration_weeks: int; start_date: date; deadline: date
      goal_statement: str
      sessions_per_week: int          # 由 template.weekly_template 加總
      total_minutes_per_week: int
      completion_rate: float          # done / (done+missed+skipped)，無任務時 0.0

  class SubmitAnswers:
      async def __call__(self, user_id: UUID, session_id: UUID,
                         answers: Sequence[AnswerInput]) -> CreateSessionResult: ...
      # session.status 必須是 questioning，否則 Conflict
      # 寫入最新 followup_round 的 answers，enqueue PlanContinueJobV1

  class AnswerInput(BaseModel):
      question_id: str
      choice: str | None = None       # 選了第幾個選項的原文
      custom: str | None = None       # 自由回答
      skipped: bool = False

  class GetJob:
      async def __call__(self, job_id: str) -> JobView: ...
      # 先讀 cache，miss 時 fallback 佇列/DB（PRD 9.4 第 17 條）
  ```

  HTTP：`POST /v1/plan-sessions` → 202 + `{session_id, job_id}`；`GET /v1/plan-sessions/{id}`；`POST /v1/plan-sessions/{id}/answers` → 202；`GET /v1/jobs/{id}`。

- [ ] **Step 1: 寫失敗測試（API 層 + 端到端）**

```python
async def test_create_session_requires_goal(client):
    r = await client.post("/v1/plan-sessions", json={"goal": ""}, headers=AUTH)
    assert r.status_code == 422


async def test_create_session_returns_202_and_enqueues(client, container):
    r = await client.post("/v1/plan-sessions", json={"goal": "跑進 30 分"}, headers=AUTH)
    assert r.status_code == 202
    assert container.queue.enqueued[0].queue_name() == "plan.generate"


async def test_create_session_rejects_other_users_import(client):
    r = await client.post("/v1/plan-sessions",
                          json={"goal": "g", "import_ids": [str(OTHER_IMPORT)]}, headers=AUTH)
    assert r.status_code == 422


async def test_answers_on_non_questioning_session_conflicts(client):
    ...  # 409


async def test_end_to_end_goal_only_to_three_plans(container):
    """PRD M2 驗收：只填目標 → 三份 plans 與可勾選 tasks。"""
    r = await client.post("/v1/plan-sessions", json={"goal": "12 週 5K 跑進 30 分"},
                          headers=AUTH)
    sid = r.json()["session_id"]
    await container.queue.drain(ENGINE_HANDLERS)          # 第一輪：追問
    body = (await client.get(f"/v1/plan-sessions/{sid}", headers=AUTH)).json()
    assert body["status"] == "questioning" and len(body["questions"]) >= 1

    await client.post(f"/v1/plan-sessions/{sid}/answers", headers=AUTH, json={
        "answers": [{"question_id": q["id"], "choice": q["options"][0]}
                    for q in body["questions"]]})
    await container.queue.drain(ENGINE_HANDLERS)          # 第二輪：生成
    body = (await client.get(f"/v1/plan-sessions/{sid}", headers=AUTH)).json()
    assert body["status"] == "done" and len(body["plans"]) == 3
    plan_id = body["plans"][0]["id"]
    tasks = (await client.get(f"/v1/plans/{plan_id}/tasks", headers=AUTH)).json()
    assert len(tasks["items"]) > 0
```

- [ ] **Step 2–4: 確認失敗 → 實作 → 轉綠**
- [ ] **Step 5: 寫 `cmd/plan_engine_worker.py`（≤30 行，註冊 `plan.generate` / `plan.continue` / `plan.revise` 三個 handler；`plan.revise` 於 Task 39 接上，先註冊一個 raise NotImplementedError 的佔位並在該 task 換掉）**
- [ ] **Step 6: `make check` 全綠後 commit** — `feat: plan session endpoints and engine worker wiring`

### M2 驗收

- [ ] 端到端測試 `test_end_to_end_goal_only_to_three_plans` 綠
- [ ] `make check` 全綠
- [ ] commit: `chore: M2 plan engine complete`

---

# Phase M3 — Role model

## Task 25: Role Model domain — tag 詞彙、驗證與 content schema

**Files:**
- Create: `services/role_model/domain/{__init__,tags.py,content.py,errors.py}`
- Create: `config/tag_vocab.yaml`（**原文照抄 PRD 12.3 的初版**）
- Test: `tests/unit/role_model/test_tags.py`, `tests/unit/role_model/test_content.py`

**Interfaces:**
- Produces（PRD 12.3 / 12.4）：
  ```python
  # tags.py
  class ValueRules(BaseModel):
      pattern: str; max_length: int; max_tags_per_record: int

  class TagVocab(BaseModel):
      version: int
      mode: Literal["lenient", "strict"]
      namespaces: list[str]
      value_rules: ValueRules
      enum_only: dict[str, list[str]]
      known_values: dict[str, list[str]]
      required_tags: dict[str, list[str]]

  def load_tag_vocab(path: Path | None = None) -> TagVocab: ...

  class InvalidTag(ValueError): ...

  def validate_tags(tags: Sequence[str], kind: str, vocab: TagVocab) -> None: ...
  # 規則：
  #  - 每個 tag 形如 "namespace:value"，namespace 必須在 vocab.namespaces，否則 InvalidTag
  #  - value 必須符合 value_rules.pattern 與 max_length
  #  - namespace 在 enum_only 時，value 必須在該清單內
  #  - mode=="strict" 時 value 也必須在 known_values[namespace] 內
  #  - len(tags) <= max_tags_per_record
  #  - required_tags[kind] 列出的 namespace 必須至少各出現一次
  #  - persona 必須有 >=1 個 goal:（由 required_tags 表達）
  def parse_tag(tag: str) -> tuple[str, str]: ...
  def learn_values(tags: Sequence[str], vocab: TagVocab) -> TagVocab: ...
      # 回傳把新值加進 known_values 的新 vocab（不就地修改）

  # content.py — discriminated union
  class Provenance(BaseModel):
      sources: list[Source] = []
      confidence: Literal["high", "medium", "low"] = "medium"
      author: str | None = None
      notes: str | None = None

  class Source(BaseModel):
      title: str
      url: str
      accessed_at: date | None = None

  class Applicability(BaseModel):
      good_for: list[str] = []
      not_for: list[str] = []

  class PersonaSections(BaseModel):
      principles: list[str] = []
      weekly_structure: str = ""
      progress_metrics: list[str] = []
      pitfalls: list[str] = []
      applicability: Applicability = Applicability()
      example_milestones: list[str] = []

  class TraitContent(BaseModel):
      kind: Literal["trait"] = "trait"
      summary: str = Field(max_length=120)
      pacing: Pacing                       # 重用 plan_engine 的定義？不行——跨 service 禁止 import
      provenance: Provenance = Provenance()

  class PersonaContent(BaseModel):
      kind: Literal["persona"] = "persona"
      summary: str = Field(max_length=120)
      sections: PersonaSections = PersonaSections()
      provenance: Provenance = Provenance()

  RoleModelContent = Annotated[TraitContent | PersonaContent, Field(discriminator="kind")]

  def parse_content(kind: str, raw: dict[str, Any]) -> TraitContent | PersonaContent: ...
      # 把外層 kind 塞進 raw 再驗證；型別不符 raise InvalidContent
  class InvalidContent(ValueError): ...
  ```

  **跨 service 型別重複的處理**：`Pacing` 在 `plan_engine/domain/difficulty.py` 與 `role_model/domain/content.py` 各自定義一份同名同欄位的 model（services 之間禁止 import）。兩者以 `plan_sessions.context_snapshot` 的 JSON 為契約，Plan Engine 用 `Pacing.model_validate(dict)` 從 `role_models.content["pacing"]` 讀入。這是刻意的重複，兩處都加註解說明。

- [ ] **Step 1: 寫失敗測試**

```python
def test_rejects_unknown_namespace():
    with pytest.raises(InvalidTag, match="foo"):
        validate_tags(["foo:bar"], "persona", VOCAB)


def test_rejects_bad_value_pattern():
    with pytest.raises(InvalidTag):
        validate_tags(["domain:Fitness"], "persona", VOCAB)     # 大寫不合法


def test_enum_only_namespace_rejects_unknown_value():
    with pytest.raises(InvalidTag, match="level"):
        validate_tags(["domain:x", "goal:y", "level:godlike"], "persona", VOCAB)


def test_persona_requires_domain_and_goal():
    with pytest.raises(InvalidTag, match="goal"):
        validate_tags(["domain:fitness"], "persona", VOCAB)


def test_trait_has_no_required_tags():
    validate_tags(["cadence:daily"], "trait", VOCAB)      # 不 raise


def test_lenient_mode_accepts_new_domain_value():
    validate_tags(["domain:woodworking", "goal:skill"], "persona", VOCAB)


def test_strict_mode_rejects_new_value():
    strict = VOCAB.model_copy(update={"mode": "strict"})
    with pytest.raises(InvalidTag):
        validate_tags(["domain:woodworking", "goal:skill"], "persona", strict)


def test_max_tags_enforced(): ...
def test_learn_values_appends_without_mutating(): ...


def test_trait_content_requires_pacing():
    with pytest.raises(InvalidContent):
        parse_content("trait", {"summary": "x"})


def test_persona_content_rejects_pacing_field():
    with pytest.raises(InvalidContent):
        parse_content("persona", {"summary": "x", "pacing": {...}})


def test_parse_content_accepts_prd_example():
    c = parse_content("persona", PRD_P2_EXAMPLE)     # PRD 14.2 的 Kipchoge 範例
    assert c.sections.principles and c.sections.applicability.good_for
```

- [ ] **Step 2–4: 確認失敗 → 實作 → 轉綠**
- [ ] **Step 5: commit** — `feat(role-model): tag vocabulary validation and content schemas`

---

## Task 26: Role Model domain — 計分與 RoleModelRenderer

**Files:**
- Create: `services/role_model/domain/{scoring.py,renderer.py}`
- Test: `tests/unit/role_model/test_scoring.py`, `tests/unit/role_model/test_renderer.py`

**Interfaces:**
- Produces（PRD 12.5 / 12.6）：
  ```python
  # scoring.py
  class UserSignals(BaseModel):
      domains: list[str] = []        # 由目標推出的 domain: 值
      goals: list[str] = []
      level: str | None = None
      cadence: str | None = None
      horizon: str | None = None
      excluded_constraints: list[str] = []   # 使用者不符合的 constraint:

  class ScoredCandidate(BaseModel):
      role_model_id: UUID
      name: str
      tags: list[str]
      summary: str
      applicability: Applicability
      score: int

  def score_candidates(candidates: Sequence[RoleModelRow],
                       signals: UserSignals, limit: int = 8) -> list[ScoredCandidate]: ...
  # 計分：goal 命中 ×4、method 命中 ×3、level 相符 ×2、cadence 相符 ×1、horizon 相符 ×1
  # 帶有 signals.excluded_constraints 內任一 constraint: 的候選一律剔除（分數不計）
  # 依 score 遞減、同分依 name 字典序，取前 limit

  # renderer.py
  class RoleModelRenderer:
      def to_context(self, kind: str, name: str, content: dict[str, Any],
                     purpose: Purpose, budget_tokens: int) -> str: ...
  # 區塊順序（PRD 12.6），超出預算從尾端整段截掉，不截句子中間：
  #   evaluate: trait -> pacing.intensity_bias 一句；persona -> summary + applicability
  #   generate: trait -> 整份 pacing 渲染成約束句；
  #             persona -> principles, weekly_structure, progress_metrics,
  #                        pitfalls, example_milestones
  #   revise:   trait -> missed_policy + progression_rate；
  #             persona -> pitfalls, weekly_structure
  # token 估算：len(text) // 2（中文近似），實作為模組層級函式 estimate_tokens(text)
  # trait pacing 約束句格式（固定字串模板，測試逐字比對）：
  #   "節奏約束：每週 {a}–{b} 次，每次 {c}–{d} 分鐘，至少休息 {e} 天；"
  #   "每兩週增量不超過 {f}%；漏做的任務{g}；預設強度{h}。"
  #   g: none->「不補」 same-week->「在同週補一次」 next-day->「隔日補」
  #   h: low->「低」 medium->「中等」 high->「高」

  class NullRoleModelRenderer:      # Task 22 的佔位，保留給測試用
      def to_context(self, *args: Any, **kwargs: Any) -> str: return ""
  ```

- [ ] **Step 1: 寫失敗測試**

```python
def test_goal_hit_scores_higher_than_method_hit(): ...
def test_excluded_constraint_removes_candidate():
    out = score_candidates([_c(tags=["domain:fitness", "goal:x", "constraint:no-gym"])],
                           UserSignals(domains=["fitness"], excluded_constraints=["no-gym"]))
    assert out == []
def test_limit_is_respected(): ...
def test_ties_broken_by_name(): ...

def test_generate_purpose_renders_full_pacing_sentence():
    out = RoleModelRenderer().to_context("trait", "穩扎穩打型", T2_CONTENT,
                                         Purpose.generate, 600)
    assert out.strip().endswith(
        "節奏約束：每週 4–5 次，每次 30–60 分鐘，至少休息 1 天；"
        "每兩週增量不超過 10%；漏做的任務在同週補一次；預設強度中等。")

def test_evaluate_purpose_only_includes_intensity_bias():
    out = RoleModelRenderer().to_context("trait", "n", T2_CONTENT, Purpose.evaluate, 150)
    assert "強度" in out and "每週 4–5 次" not in out

def test_persona_generate_includes_all_five_sections(): ...

def test_budget_truncates_from_the_tail_by_whole_sections():
    full = RoleModelRenderer().to_context("persona", "n", P2_CONTENT, Purpose.generate, 600)
    tight = RoleModelRenderer().to_context("persona", "n", P2_CONTENT, Purpose.generate, 60)
    assert tight in full or full.startswith(tight.rstrip())
    assert "常見失敗點" not in tight        # 尾端區塊被截掉
    assert estimate_tokens(tight) <= 60

def test_revise_purpose_uses_pitfalls_and_weekly_structure(): ...
def test_empty_content_renders_empty_string(): ...
```

- [ ] **Step 2–4: 確認失敗 → 實作 → 轉綠**
- [ ] **Step 5: commit** — `feat(role-model): candidate scoring and context renderer`

---

## Task 27: Role Model Service — HTTP CRUD 與查詢

**Files:**
- Create: `services/role_model/application/{__init__,list_role_models.py,get_role_model.py,upsert_role_model.py,deactivate_role_model.py,list_tags.py}`
- Create: `services/role_model/adapters/http/{__init__,app.py,router.py,deps.py,schemas.py}`
- Create: `services/role_model/{settings.py,container.py,README.md}`
- Create: `cmd/role_model_server.py`
- Test: `tests/application/role_model/test_crud.py`

**Interfaces:**
- Produces:
  ```python
  class RoleModelView(BaseModel):
      id: UUID; kind: str; name: str; tags: list[str]
      content: dict[str, Any]; active: bool; version: int
      created_at: datetime; updated_at: datetime

  class RoleModelSummary(BaseModel):
      id: UUID; kind: str; name: str; tags: list[str]; summary: str

  class ListRoleModels:
      async def __call__(self, kind: str | None, tags: Sequence[str],
                         match: Literal["any", "all"] = "any",
                         limit: int = 50) -> list[RoleModelSummary]: ...
  class GetRoleModel:
      async def __call__(self, role_model_id: UUID) -> RoleModelView: ...   # 不存在 -> NotFound
  class UpsertRoleModel:
      async def __call__(self, role_model_id: UUID | None, kind: str, name: str,
                         tags: list[str], content: dict[str, Any]) -> RoleModelView: ...
      # validate_tags + parse_content，任一失敗 -> InvalidInput；成功時 learn_values 寫回
      # config/tag_vocab.yaml（附 file lock；測試以 tmp_path 覆寫路徑）
  class DeactivateRoleModel:
      async def __call__(self, role_model_id: UUID) -> None: ...
  class ListTags:
      async def __call__(self) -> dict[str, list[str]]: ...   # namespace -> 現存值
  ```

  HTTP（Role Model Service，port 8001）：
  | Method | Path | 保護 |
  |---|---|---|
  | GET | `/role-models` | 無（由 API Service 轉發） |
  | GET | `/role-models/tags` | 無 |
  | GET | `/role-models/{id}` | 無 |
  | POST | `/role-models` | `X-API-Key` |
  | PUT | `/role-models/{id}` | `X-API-Key` |
  | DELETE | `/role-models/{id}` | `X-API-Key` |
  | POST | `/role-models/recommend` | 無（Task 28） |

  API Service 端以 `RoleModelClient`（httpx）轉發，暴露 PRD 5 的 `/v1/role-models*` 路徑；`POST/PUT/DELETE` 需帶 `X-API-Key`（由 API Service 直接轉手 header，不用 JWT）。

- [ ] **Step 1: 寫失敗測試** — 建立 persona 後可 GET；tag 非法回 422；缺 `X-API-Key` 回 401；`GET /role-models?kind=trait` 只回 trait；`tags=domain:fitness&tags=goal:endurance&match=all` 兩個都要命中才回；`DELETE` 後 `active=false` 且不出現在預設列表；`GET /role-models/tags` 回按 namespace 分組的值。
- [ ] **Step 2–4: 確認失敗 → 實作 → 轉綠**
- [ ] **Step 5: 寫 `cmd/role_model_server.py`（≤30 行）並 commit** — `feat(role-model): crud http service`

---

## Task 28: Role Model 推薦（LLM）

**Files:**
- Create: `services/role_model/application/recommend_role_models.py`
- Create: `services/api/application/recommend_role_models.py`（轉發）
- Create: `services/api/adapters/http/role_models_router.py`
- Create: `services/api/adapters/role_model_client.py`
- Test: `tests/application/role_model/test_recommend.py`

**Interfaces:**
- Produces（PRD 3.9 / 12.5）：
  ```python
  class RecommendInput(BaseModel):
      goal: str
      intake: dict[str, Any] = {}
      profile_answers: dict[str, Any] = {}
      domains: list[str] = []                # 前端可帶，未帶則由 LLM 從 goal 推
      excluded_constraints: list[str] = []

  class Recommendation(BaseModel):
      role_model_id: UUID
      name: str
      reason: str = Field(max_length=120)

  class RecommendOutput(BaseModel):          # LLM output schema
      model_config = ConfigDict(extra="forbid")
      recommendations: list[Recommendation] = Field(max_length=3)

  class RecommendRoleModels:
      SQL_LIMIT = 30
      SCORE_LIMIT = 8
      def __init__(self, repo: RoleModelRepo, llm: LLMPort,
                   renderer: RoleModelRenderer, max_attempts: int) -> None: ...
      async def __call__(self, payload: RecommendInput) -> list[Recommendation]: ...
      # 1. SQL 硬過濾：kind="persona", active, tags_any=domains(有給才用), limit=30
      # 2. score_candidates(..., limit=8)
      # 3. 候選為空 -> 直接回 []（不呼叫 LLM）
      # 4. complete_validated(..., RecommendOutput, Purpose.recommend,
      #      rules=[_ids_must_be_in_candidates, _no_duplicates], fallback=前 3 名分數最高者)
      # 5. 固定排除 kind="trait"
  ```

- [ ] **Step 1: 寫失敗測試**

```python
async def test_returns_at_most_three(): ...
async def test_never_recommends_trait_kind():
    # 資料庫同時有 trait 與 persona，結果 id 全部是 persona
    ...
async def test_empty_candidates_skips_llm():
    out = await uc(RecommendInput(goal="x", domains=["nonexistent"]))
    assert out == [] and llm.calls == []
async def test_llm_returning_unknown_id_triggers_retry():
    # 第一次回不存在的 id，第二次回合法 -> attempts==2
    ...
async def test_falls_back_to_top_scored_when_llm_keeps_failing():
    out = await uc(...)      # LLM 永遠回不合法
    assert len(out) == 3 and out[0].reason      # fallback 附預設理由
async def test_candidates_passed_to_llm_include_summary_and_applicability():
    assert "applicability" in str(llm.calls[0][2])
async def test_constraint_excluded_candidates_not_offered(): ...
```

- [ ] **Step 2–4: 確認失敗 → 實作 → 轉綠**
- [ ] **Step 5: 實作 API Service 端 `RoleModelClient` + `GET /v1/role-models/recommend`（帶 JWT，服務端組 `RecommendInput`），加一個以 `httpx.MockTransport` 的轉發測試**
- [ ] **Step 6: commit** — `feat(role-model): llm-backed recommendation`

---

## Task 29: Seed script、12 筆 seed 資料、接進 Plan Engine

**Files:**
- Create: `seeds/role_models/{traits.yaml,personas.yaml}`
- Create: `cmd/seed_role_models.py`
- Modify: `services/plan_engine/application/context_builder.py`（換掉 `NullRoleModelRenderer`）
- Modify: `services/plan_engine/container.py`
- Test: `tests/unit/role_model/test_seeds_valid.py`, `tests/application/plan_engine/test_role_model_context.py`

**Interfaces:**
- Consumes: `UpsertRoleModel`、`validate_tags`、`parse_content`、`RoleModelRenderer`
- Produces: `cmd/seed_role_models.py`（≤30 行：讀 `seeds/role_models/*.yaml` → 逐筆 `upsert_role_model` → 印出結果）；`seeds/` 內容為 PRD 14.2 的 T1–T3 與 P1–P9，**`pacing` 數值逐格照 PRD 表填**，`sections` 內容依 PRD 敘述補齊（P2 用 PRD 給的完整範例）。

- [ ] **Step 1: 寫失敗測試**

```python
def test_all_seed_files_pass_validation():
    vocab = load_tag_vocab()
    for path in Path("seeds/role_models").glob("*.yaml"):
        for row in yaml.safe_load(path.read_text())["role_models"]:
            validate_tags(row["tags"], row["kind"], vocab)
            parse_content(row["kind"], row["content"])


def test_seed_counts_match_prd():
    rows = _all_seed_rows()
    assert len([r for r in rows if r["kind"] == "trait"]) == 3
    assert len([r for r in rows if r["kind"] == "persona"]) == 9


def test_trait_pacing_values_match_prd_table():
    t1 = _seed("輕鬆寫意型")["content"]["pacing"]
    assert t1["sessions_per_week"] == [2, 3]
    assert t1["session_minutes"] == [20, 45]
    assert t1["rest_days_min"] == 2 and t1["progression_rate"] == 0.05
    assert t1["missed_policy"] == "none" and t1["deload_every_weeks"] is None
    assert t1["intensity_bias"] == "low"
    # T2、T3 同樣逐格斷言


async def test_plan_engine_context_includes_trait_pacing_sentence():
    c = build_engine_test_container()
    await _seed_role_models(c)
    sid = await _seed_session(c, trait_role_model_id=T2_ID)
    await c.evaluate_session(PlanGenerateJobV1(session_id=sid))
    ctx = c.llm.calls[0][2]
    assert "節奏約束：每週 4–5 次" in ctx["trait_context"]


async def test_context_snapshot_is_persisted_for_reproducibility():
    s = await c.sessions.get_unscoped(sid)
    assert s.context_snapshot["trait_context"]


async def test_trait_pacing_constrains_generated_plan():
    # 選 T1（每週最多 3 次），產出的 extremely_hard 每週仍 <= 3 次
    ...
```

- [ ] **Step 2–4: 確認失敗 → 撰寫 seeds → 實作 → 轉綠**
- [ ] **Step 5: 實際跑一次 seed 對本機 DB**

Run: `uv run python -m cmd.seed_role_models`
Expected: 印出 `upserted 12 role models`，且 `docker exec local-postgres psql -U postgres -d guru_core -c 'select kind, count(*) from role_models group by kind'` 回 `trait 3` / `persona 9`

- [ ] **Step 6: commit** — `feat(role-model): seed data and plan engine context wiring`

### M3 驗收

- [ ] 12 筆 seed 通過 schema 與 tag 驗證並可寫入本機 DB
- [ ] Plan Engine 的 prompt context 含 trait pacing 約束句與 persona 方法論
- [ ] `make check` 全綠；commit: `chore: M3 role models complete`

---

# Phase M4 — 管理與輸出

## Task 30: 計畫列表、詳情、改名、啟用、封存、刪除

**Files:**
- Create: `services/api/application/{list_plans.py,get_plan.py,update_plan.py,archive_plan.py,delete_plan.py}`
- Create: `services/api/adapters/http/plans_router.py`
- Create: `services/api/domain/plan_status.py`
- Test: `tests/unit/api/test_plan_status.py`, `tests/application/api/test_plan_management.py`

**Interfaces:**
- Produces（PRD 3.5）：
  ```python
  # domain/plan_status.py
  class PlanStatus(StrEnum):
      draft = "draft"; active = "active"; archived = "archived"

  PLAN_TRANSITIONS: dict[PlanStatus, frozenset[PlanStatus]] = {
      PlanStatus.draft:    frozenset({PlanStatus.active, PlanStatus.archived}),
      PlanStatus.active:   frozenset({PlanStatus.draft, PlanStatus.archived}),
      PlanStatus.archived: frozenset({PlanStatus.active}),
  }
  def assert_plan_transition(current: PlanStatus, target: PlanStatus) -> None: ...

  # application
  class PlanDetail(BaseModel):
      id: UUID; session_id: UUID; title: str; difficulty: str; status: str
      goal_statement: str; duration_weeks: int
      start_date: date; deadline: date
      phases: list[dict[str, Any]]          # structure["phases"]
      success_criteria: list[str]
      assumptions: list[str]
      progress: PlanProgress
      exports: list[ExportStatusView]

  class PlanProgress(BaseModel):
      total: int; done: int; missed: int; skipped: int; pending: int
      completion_rate: float                 # done / (done+missed+skipped)，分母 0 -> 0.0
      phase_rates: list[PhaseRate]
      checkpoints: list[CheckpointStatus]

  class PhaseRate(BaseModel):
      phase_index: int; name: str; done: int; total: int; rate: float

  class CheckpointStatus(BaseModel):
      phase_index: int; title: str; metric: str
      due_at: datetime; status: str

  class ListPlans:
      async def __call__(self, user_id: UUID, status: str | None) -> list[PlanSummary]: ...
  class GetPlan:
      async def __call__(self, user_id: UUID, plan_id: UUID) -> PlanDetail: ...
  class UpdatePlan:
      async def __call__(self, user_id: UUID, plan_id: UUID, *, title: str | None,
                         status: str | None) -> PlanDetail: ...
      # status="active" 時：先 assert_plan_transition，再把同 session 其他 plan 設回 draft
      #                     並寫 activated_at
  class ArchivePlan:
      async def __call__(self, user_id: UUID, plan_id: UUID) -> PlanDetail: ...
      # 寫 archived_at；不動任何外部行事曆（PRD 3.5）
  class DeletePlan:
      async def __call__(self, user_id: UUID, plan_id: UUID) -> None: ...
      # 若有匯出紀錄 -> 先 enqueue 一個解除匯出的 ExportJobV1(mode="full") 前置刪除，
      #   MVP 簡化為：呼叫 UnexportPlan（Task 35）同步刪除外部事件後再刪 DB 列
  ```

- [ ] **Step 1: 寫失敗測試**

```python
def test_archived_cannot_go_straight_to_draft():
    with pytest.raises(IllegalTransition):
        assert_plan_transition(PlanStatus.archived, PlanStatus.draft)

async def test_activate_demotes_siblings_to_draft():
    plans = await _three_plans(c)
    await c.update_plan(U, plans[0].id, title=None, status="active")
    await c.update_plan(U, plans[1].id, title=None, status="active")
    fresh = await c.list_plans(U, None)
    assert [p.status for p in sorted(fresh, key=lambda p: p.id)].count("active") == 1

async def test_activate_sets_activated_at(): ...
async def test_rename_only_changes_title(): ...
async def test_list_filters_by_status(): ...
async def test_archived_plans_hidden_from_default_list(): ...
async def test_get_plan_of_other_user_is_404(): ...

async def test_progress_counts_and_rate():
    # 10 個任務：3 done、1 missed、1 skipped、5 pending
    p = (await c.get_plan(U, plan_id)).progress
    assert p.total == 10 and p.done == 3 and p.pending == 5
    assert p.completion_rate == pytest.approx(0.6)      # 3 / 5

async def test_completion_rate_zero_when_nothing_resolved():
    assert (await c.get_plan(U, plan_id)).progress.completion_rate == 0.0

async def test_phase_rates_cover_every_phase(): ...
async def test_checkpoints_listed_with_due_date(): ...
async def test_delete_removes_plan_and_tasks(): ...
```

- [ ] **Step 2–4: 確認失敗 → 實作 → 轉綠**
- [ ] **Step 5: commit** — `feat(api): plan lifecycle management endpoints`

---

## Task 31: 內建行事曆 / Todo — 任務查詢與更新

**Files:**
- Create: `services/api/application/{list_plan_tasks.py,update_plan_task.py}`
- Modify: `services/api/adapters/http/plans_router.py`
- Test: `tests/application/api/test_plan_tasks.py`

**Interfaces:**
- Produces:
  ```python
  class PlanTaskView(BaseModel):
      id: UUID; template_key: str; week_index: int; phase_index: int
      occurrence: int; task_type: str; title: str; description: str
      start_at: datetime; end_at: datetime; all_day: bool
      status: str; completed_at: datetime | None; missed_reason: str | None
      synced: bool                     # external_ref is not None and synced_at >= updated

  class PlanTaskList(BaseModel):
      items: list[PlanTaskView]
      total: int

  class ListPlanTasks:
      async def __call__(self, user_id: UUID, plan_id: UUID,
                         from_: date | None, to: date | None) -> PlanTaskList: ...
      # 依 plan owner 的 timezone 把 from/to 轉成 UTC 區間；預設回全部

  class UpdatePlanTask:
      async def __call__(self, user_id: UUID, plan_id: UUID, task_id: UUID, *,
                         status: str | None, start_at: datetime | None,
                         end_at: datetime | None,
                         missed_reason: str | None) -> PlanTaskView: ...
      # 規則：
      #  - status 只接受 pending/done/missed/skipped，否則 InvalidInput
      #  - status=="done" 時寫 completed_at=clock.now()；改回 pending 時清空
      #  - status=="missed" 時可帶 missed_reason
      #  - 同時給 start_at/end_at 時必須 end_at > start_at，否則 InvalidInput
      #  - 改時間或狀態後把 synced_at 設為 None（標記為 dirty）
      #  - 該 plan 已有 google_calendar 匯出紀錄時，enqueue
      #    ExportJobV1(plan_id, "google_calendar", "incremental")
  ```

- [ ] **Step 1: 寫失敗測試** — 依日期區間過濾（含跨時區邊界：`Asia/Taipei` 的 09-08 應包含 UTC 09-07T16:00 的任務）；標 done 寫入 `completed_at`；改回 pending 清空；非法 status 422；`end_at <= start_at` 422；改時間後 `synced_at is None`；有匯出時 enqueue incremental、無匯出時不 enqueue；跨使用者 404。
- [ ] **Step 2–4: 確認失敗 → 實作 → 轉綠**
- [ ] **Step 5: commit** — `feat(api): plan task listing and updates`

---

## Task 32: 每日 check-in

**Files:**
- Create: `services/api/application/{submit_checkin.py,list_checkins.py}`
- Modify: `services/api/adapters/http/plans_router.py`
- Test: `tests/application/api/test_checkins.py`

**Interfaces:**
- Produces（PRD 3.7）：
  ```python
  class CheckinResultInput(BaseModel):
      task_id: UUID
      status: Literal["done", "missed", "skipped"]
      reason: str | None = None

  class CheckinView(BaseModel):
      id: UUID; checkin_date: date
      results: list[CheckinResultInput]
      note: str | None
      created_at: datetime

  class CheckinHistory(BaseModel):
      items: list[CheckinView]
      daily_rates: list[DailyRate]       # 達成率曲線

  class DailyRate(BaseModel):
      date: date; done: int; total: int; rate: float

  class SubmitCheckin:
      async def __call__(self, user_id: UUID, plan_id: UUID, checkin_date: date,
                         results: Sequence[CheckinResultInput],
                         note: str | None) -> CheckinView: ...
      # 1. 所有 task_id 必須屬於該 plan，否則 InvalidInput
      # 2. checkins.upsert（UNIQUE(plan_id, date)，重複提交為覆寫）
      # 3. plan_tasks.bulk_set_status：同步寫 status / completed_at / missed_reason
      #    並把這些任務的 synced_at 設為 None
      # 4. 有 google_calendar 匯出時 enqueue incremental
  class ListCheckins:
      async def __call__(self, user_id: UUID, plan_id: UUID) -> CheckinHistory: ...
  ```

- [ ] **Step 1: 寫失敗測試** — 提交後 `plan_tasks.status` 同步更新；同日重複提交為覆寫（`checkins` 仍只有一筆，且任務狀態以最後一次為準）；帶不屬於該 plan 的 task_id 回 422；`daily_rates` 每天一筆且 rate 正確；有匯出時 enqueue incremental；跨使用者 404。
- [ ] **Step 2–4: 確認失敗 → 實作 → 轉綠**
- [ ] **Step 5: commit** — `feat(api): daily check-in`

---

## Task 33: Markdown 匯出（同步）

**Files:**
- Create: `services/api/domain/markdown_export.py`
- Create: `services/api/application/export_markdown.py`
- Modify: `services/api/adapters/http/plans_router.py`
- Test: `tests/unit/api/test_markdown_export.py`, `tests/application/api/test_export_markdown.py`

**Interfaces:**
- Produces（PRD 4.3.5，輸出格式逐行對齊）：
  ```python
  # domain/markdown_export.py — 純函式，無 IO
  class MarkdownOptions(BaseModel):
      include_completed: bool = True
      from_: date | None = None
      to: date | None = None

  def render_markdown(plan: PlanDetailData, tasks: Sequence[PlanTaskData],
                      options: MarkdownOptions, timezone: str) -> str: ...
  # 區塊順序：# 標題 / goal_statement / 期程行 / ## 達成標準 / ## 系統假設 /
  #           ## 階段（表格）/ ## 週計畫（每週一個 ### 小節）/ ## 進度
  # 任務行格式：
  #   done:    "- [x] 09/08 (一) 19:30–20:00　輕鬆跑 — 描述"
  #   pending: "- [ ] 09/10 (三) 19:30–20:05　間歇跑 — 描述"
  #   missed:  "- [ ] ~~09/12 (六) 07:00–07:45　長距離慢跑~~ ✗ 未達標"
  #   skipped: "- [ ] 09/12 (六) 07:00–07:45　長距離慢跑 — 略過"
  #   all_day: "- [ ] 09/28 (日) 全天　連續慢跑 5K 不停"
  # 星期用 一二三四五六日；時間依 timezone 轉換
  # 進度行："完成 12 / 48（25%）　未達標 3　略過 1"

  # application/export_markdown.py
  class MarkdownExportResult(BaseModel):
      content: str            # 純文字，供前端直接複製
      download_url: str       # presigned GET，15 分鐘
      storage_key: str

  class ExportMarkdown:
      async def __call__(self, user_id: UUID, plan_id: UUID,
                         options: MarkdownOptions) -> MarkdownExportResult: ...
      # 渲染 → storage.put(f"exports/{user_id}/{plan_id}/{ts}.md") → presign_get
      # 不走佇列（PRD 4.3.5）
  ```

- [ ] **Step 1: 寫失敗測試（domain 層逐行比對整份輸出）**

```python
def test_renders_full_document_matching_prd_shape():
    out = render_markdown(PLAN, TASKS, MarkdownOptions(), "Asia/Taipei")
    assert out.splitlines()[0] == "# 12 週 5K 跑進 30 分（穩健）"
    assert "**期程**：2026-09-08 – 2026-11-29（12 週）　**難度**：hard" in out
    assert "## 達成標準" in out and "## 系統假設" in out
    assert "| 階段 | 週次 | 重點 | 里程碑 |" in out
    assert "### 第 1 週（09/08 – 09/14）　基礎期" in out

def test_done_task_uses_checked_box():
    assert "- [x] 09/08 (一) 19:30–20:00　輕鬆跑" in out

def test_missed_task_is_struck_through_with_mark():
    assert "- [ ] ~~09/12 (六) 07:00–07:45　長距離慢跑~~ ✗ 未達標" in out

def test_all_day_task_shows_full_day(): ...
def test_progress_line_format():
    assert "完成 12 / 48（25%）　未達標 3　略過 1" in out

def test_include_completed_false_omits_done_tasks(): ...
def test_from_to_filters_weeks(): ...
def test_timezone_affects_displayed_time():
    utc = render_markdown(PLAN, TASKS, MarkdownOptions(), "UTC")
    tpe = render_markdown(PLAN, TASKS, MarkdownOptions(), "Asia/Taipei")
    assert utc != tpe

async def test_export_stores_file_and_returns_url():
    r = await c.export_markdown(U, plan_id, MarkdownOptions())
    assert r.content.startswith("# ")
    assert await c.storage.exists(r.storage_key)
    assert r.download_url
```

- [ ] **Step 2–4: 確認失敗 → 實作 → 轉綠**
- [ ] **Step 5: commit** — `feat(api): markdown export`

---

## Task 34: Google Calendar 匯出 — full 模式

**Files:**
- Create: `services/api/domain/calendar_mapping.py`
- Create: `services/api/application/{request_export.py,push_export.py}`
- Create: `config/calendar_colors.yaml`
- Modify: `services/api/adapters/queue/`（加 export consumer）、`plans_router.py`、`cmd/api_worker.py`
- Test: `tests/unit/api/test_calendar_mapping.py`, `tests/application/api/test_export_calendar_full.py`

**Interfaces:**
- Produces（PRD 4.3.4）：
  ```python
  # domain/calendar_mapping.py — 純函式
  class ColorMap(BaseModel):
      default: str
      by_template_key: dict[str, str] = {}
      by_task_type: dict[str, str] = {}
      def color_for(self, template_key: str, task_type: str) -> str: ...

  def to_calendar_event(task: PlanTaskData, plan_title: str,
                        color_map: ColorMap) -> CalendarEventWrite: ...
  # summary: task.status=="done" -> f"✓ {title}"；"missed" -> f"✗ {title}"；否則 title
  # description: f"{task.description}\n\n來自 guru-core · {plan_title} · 第 {week_index+1} 週"
  # all_day 時使用日期而非時間（由 CalendarPort 實作決定送 date 或 dateTime）
  # private_props: {"guru_task_id": str(task.id), "guru_plan_id": str(task.plan_id)}
  # color_id: color_map.color_for(template_key, task_type)

  def should_export(task: PlanTaskData, include_rest: bool) -> bool: ...
  # rest 類預設不匯出（PRD 4.3.4）

  # application/request_export.py
  class RequestExport:
      async def __call__(self, user_id: UUID, plan_id: UUID, target: str,
                         options: dict[str, Any]) -> ExportRequestResult: ...
      # target=="markdown" -> 直接呼叫 ExportMarkdown 同步回傳
      # 其他 -> upsert plan_exports(status="queued")，
      #         mode = "full" if 尚無 external_calendar_id else "incremental"
      #         enqueue ExportJobV1
      # 未連結 Google 時 raise ReauthRequired（PRD 3.6：App 據此跳連結提示）
      # plan.status 必須是 active，否則 Conflict（PRD 3.5：匯出只作用於 active）

  class ExportRequestResult(BaseModel):
      target: str
      mode: str | None
      job_id: str | None
      markdown: MarkdownExportResult | None

  # application/push_export.py — worker handler
  class PushExport:
      def __init__(self, plans: PlanRepo, plan_tasks: PlanTaskRepo,
                   exports: PlanExportRepo, calendar: CalendarPort,
                   tokens: GoogleAccessTokenProvider, color_map: ColorMap,
                   clock: ClockPort) -> None: ...
      async def __call__(self, job: ExportJobV1) -> None: ...
      # mode=="full":
      #   1. create_calendar(f"guru · {plan.title}") -> external_calendar_id
      #   2. 對每個 should_export 的任務 create_event，回填 external_ref 與 synced_at
      #   3. exports.upsert(status="synced", last_synced_at=now)
      # 任一步失敗 -> exports.upsert(status="failed", error=...)，不重拋
      # ReauthRequired -> status="failed", error="reauth_required"
  ```

  `config/calendar_colors.yaml`：
  ```yaml
  default: "8"
  by_task_type:
    session: "9"
    habit: "2"
    checkpoint: "11"
    rest: "8"
  by_template_key: {}       # 匯入方可自行加映射
  ```

- [ ] **Step 1: 寫失敗測試**

```python
def test_done_task_summary_gets_check_prefix():
    e = to_calendar_event(_task(status="done", title="輕鬆跑"), "P", CM)
    assert e.summary == "✓ 輕鬆跑"

def test_missed_task_summary_gets_cross_prefix(): ...
def test_description_has_provenance_line():
    assert e.description.endswith("來自 guru-core · P · 第 1 週")
def test_private_props_carry_ids(): ...
def test_color_by_task_type(): ...
def test_rest_excluded_by_default():
    assert should_export(_task(task_type="rest"), include_rest=False) is False

async def test_full_export_creates_calendar_and_events():
    cal = FakeCalendar()
    await c.push_export(ExportJobV1(plan_id=P, target="google_calendar", mode="full"))
    assert cal.created_calendars == ["guru · 12 週 5K 跑進 30 分（穩健）"]
    assert len(cal.created_events) == _exportable_task_count()

async def test_full_export_backfills_external_ref_and_synced_at():
    tasks = await c.plan_tasks.list(P, None, None)
    assert all(t.external_ref for t in tasks if t.task_type != "rest")
    assert all(t.synced_at is not None for t in tasks if t.task_type != "rest")

async def test_export_record_marked_synced(): ...

async def test_reauth_required_marks_export_failed():
    c = build_test_container(google_oauth=FakeOAuth(refresh_raises=InvalidGrant()))
    await c.push_export(_job())
    e = await c.exports.get(P, "google_calendar")
    assert e.status == "failed" and e.error == "reauth_required"

async def test_request_export_on_draft_plan_conflicts(): ...
async def test_request_export_without_connection_raises_reauth(): ...
async def test_request_markdown_returns_inline_content_without_enqueue(): ...
```

- [ ] **Step 2–4: 確認失敗 → 實作 → 轉綠**
- [ ] **Step 5: 在 `cmd/api_worker.py` 註冊 `export.push` handler**
- [ ] **Step 6: commit** — `feat(api): google calendar full export`

---

## Task 35: Calendar 增量同步、匯出狀態與解除匯出

**Files:**
- Modify: `services/api/application/push_export.py`
- Create: `services/api/application/{get_export_status.py,unexport_plan.py}`
- Modify: `services/api/adapters/http/plans_router.py`
- Test: `tests/application/api/test_export_incremental.py`

**Interfaces:**
- Produces（PRD 3.5 / 3.7）：
  ```python
  # PushExport 增補 mode=="incremental" 分支：
  #   1. 取 plan_tasks.list_dirty(plan_id)（synced_at is null 者）
  #   2. 有 external_ref 的 -> update_event；沒有的 -> create_event 並回填
  #   3. 已不該匯出（rest 或被修訂刪除）但有 external_ref 的 -> delete_event 並清空 external_ref
  #   4. 全部成功後 exports.upsert(last_synced_at=now, status="synced")

  class ExportStatusView(BaseModel):
      target: str
      status: str                       # never | queued | synced | failed
      external_calendar_id: str | None
      last_synced_at: datetime | None
      error: str | None
      pending_changes: int              # list_dirty 的筆數

  class GetExportStatus:
      async def __call__(self, user_id: UUID, plan_id: UUID) -> list[ExportStatusView]: ...

  class UnexportPlan:
      async def __call__(self, user_id: UUID, plan_id: UUID, target: str) -> None: ...
      # google_calendar：delete_calendar(external_calendar_id)（整個 secondary calendar
      #   刪掉，PRD 4.3.4），清空所有 plan_tasks.external_ref / synced_at，
      #   刪除 plan_exports 該列
      # 外部已不存在（404）視為成功
  ```

- [ ] **Step 1: 寫失敗測試**

```python
async def test_incremental_only_touches_dirty_tasks():
    await _full_export(c)
    cal = c.calendar; cal.reset()
    await c.update_plan_task(U, P, T1, status="done", start_at=None, end_at=None,
                             missed_reason=None)
    await c.push_export(ExportJobV1(plan_id=P, target="google_calendar",
                                    mode="incremental"))
    assert len(cal.updated_events) == 1 and cal.created_events == []

async def test_incremental_creates_event_for_new_task():
    # 修訂新增的任務沒有 external_ref -> 走 create
    ...

async def test_incremental_deletes_event_for_removed_task():
    ...

async def test_done_task_title_gets_check_prefix_on_sync():
    assert cal.updated_events[0].summary.startswith("✓")

async def test_synced_at_updated_after_push():
    assert all(t.synced_at is not None for t in await c.plan_tasks.list(P, None, None))

async def test_pending_changes_reported_in_status():
    await c.update_plan_task(...)          # 造成一筆 dirty
    [v] = await c.get_export_status(U, P)
    assert v.pending_changes == 1

async def test_unexport_deletes_calendar_and_clears_refs():
    await c.unexport_plan(U, P, "google_calendar")
    assert c.calendar.deleted_calendars == [CAL_ID]
    assert all(t.external_ref is None for t in await c.plan_tasks.list(P, None, None))
    assert await c.exports.get(P, "google_calendar") is None

async def test_unexport_tolerates_already_deleted_calendar():
    c.calendar.delete_calendar_raises = NotFoundOnGoogle()
    await c.unexport_plan(U, P, "google_calendar")      # 不 raise

async def test_archive_does_not_touch_calendar():
    await c.archive_plan(U, P)
    assert c.calendar.deleted_calendars == [] and c.calendar.deleted_events == []
```

- [ ] **Step 2–4: 確認失敗 → 實作 → 轉綠**
- [ ] **Step 5: commit** — `feat(api): incremental calendar sync and unexport`

### M4 驗收

- [ ] 匯出後 `plan_tasks.external_ref` 全部回填；改任務後 incremental 只同步變動筆數
- [ ] Markdown 匯出可下載且內容符合 PRD 4.3.5 格式
- [ ] `make check` 全綠；commit: `chore: M4 management and export complete`

---

# Phase M4.5 — 計畫修訂

## Task 36: 修訂策略約束與 revise use case

**Files:**
- Create: `services/plan_engine/domain/revision.py`
- Create: `services/plan_engine/application/revise_plan.py`
- Modify: `services/plan_engine/adapters/queue/consumers.py`, `cmd/plan_engine_worker.py`
- Test: `tests/unit/plan_engine/test_revision_rules.py`, `tests/application/plan_engine/test_revise_plan.py`

**Interfaces:**
- Produces（PRD 3.8 / 3.8.1）：
  ```python
  # domain/revision.py
  class Strategy(StrEnum):
      postpone = "postpone"; reduce = "reduce"

  class RevisedTemplateOutput(BaseModel):     # LLM output schema
      model_config = ConfigDict(extra="forbid")
      template: PlanTemplate
      rationale: str = Field(min_length=1, max_length=500)

  def strategy_rules(strategy: Strategy, original: PlanTemplate,
                     pacing: Pacing | None) -> list[BusinessRule]: ...
  # postpone：
  #   - goal_statement 必須與原本完全相同
  #   - success_criteria 必須與原本完全相同
  #   - 每個 weekly_template item 的 times_per_week 與 duration_minutes 不得改變
  #     （比對 key；key 集合也不得改變）
  #   - duration_weeks 必須 >= 原本（只能往後推）
  # reduce：
  #   - duration_weeks 必須與原本完全相同（截止日固定）
  #   - goal_statement 必須改變（目標量縮小）
  #   - success_criteria 必須改變
  # 兩者共同：
  #   - pacing 非 None 時，session 類 times_per_week 總和須落在 sessions_per_week 內
  #   - 每項 duration_minutes 須落在 session_minutes 內
  #   - rationale 必須提到策略名稱（"延後" 或 "降標"）

  # application/revise_plan.py
  class RevisePlan:
      def __init__(self, plans: PlanRepo, plan_tasks: PlanTaskRepo,
                   revisions: PlanRevisionRepo, checkins: CheckinRepo,
                   context_builder: ContextBuilder, llm: LLMPort,
                   scheduler_config: SchedulerConfig, clock: ClockPort,
                   max_attempts: int) -> None: ...
      async def __call__(self, job: PlanReviseJobV1) -> None: ...
  ```

  行為：
  1. 讀 plan、`plan_tasks`（含 done/missed）、`checkins`；revision 已非 `pending` 則 return（冪等）。
  2. 建 context（`Purpose.revise`）：原 template、已完成/未達標統計、missed 原因、剩餘週數、策略說明、trait/persona 的 revise 區塊。
  3. `complete_validated(..., "revise_plan", ..., RevisedTemplateOutput, Purpose.revise, rules=strategy_rules(...) + [_schedulable_rule], fallback=None)`。無 fallback——修訂失敗就標 failed，讓用戶重試（不能擅自改用戶的計畫）。
  4. `cutoff = 今天 00:00（plan owner timezone）`；`schedule()` 從 `cutoff` 起重排剩餘週數，已過去的任務保持不動。
  5. `diff_tasks(before=今天之後的舊任務, after=新任務)`。
  6. `revisions.set_proposal(proposed_tasks, diff, rationale)` + `set_status("proposed")`。
  7. 失敗 → `set_status("failed")` 並在 `trigger_detail` 記 error。

- [ ] **Step 1: 寫失敗測試**

```python
def test_postpone_rejects_changed_goal_statement():
    rules = strategy_rules(Strategy.postpone, ORIG, None)
    out = RevisedTemplateOutput(template=_tpl(goal_statement="不同目標"), rationale="延後")
    assert any("goal_statement" in v for r in rules for v in r(out))

def test_postpone_rejects_shorter_duration(): ...
def test_postpone_rejects_changed_task_density(): ...
def test_postpone_accepts_longer_duration_same_density(): ...
def test_reduce_rejects_changed_duration(): ...
def test_reduce_requires_changed_goal_statement(): ...
def test_rationale_must_mention_strategy(): ...
def test_pacing_still_enforced_in_both_strategies(): ...

async def test_revise_produces_proposed_status_with_diff():
    await c.revise_plan(PlanReviseJobV1(plan_id=P, revision_id=R, strategy="postpone"))
    rev = await c.revisions.get_unscoped(R)
    assert rev.status == "proposed" and rev.diff and rev.rationale

async def test_revise_only_reschedules_future_tasks():
    rev = ...
    keys = {(d["template_key"], d["week_index"]) for d in rev.diff}
    assert all(_task_by_key(k).start_at >= TODAY for k in keys)

async def test_past_done_tasks_untouched():
    before = await c.plan_tasks.list(P, None, TODAY)
    await c.revise_plan(...)
    assert await c.plan_tasks.list(P, None, TODAY) == before

async def test_revise_marks_failed_when_llm_never_satisfies_strategy():
    rev = await c.revisions.get_unscoped(R)
    assert rev.status == "failed"

async def test_revise_is_idempotent_on_already_decided_revision():
    await c.revisions.set_status(R, "accepted", NOW)
    await c.revise_plan(...)
    assert c.llm.calls == []
```

- [ ] **Step 2–4: 確認失敗 → 實作 → 轉綠**
- [ ] **Step 5: 在 `cmd/plan_engine_worker.py` 換掉 `plan.revise` 佔位 handler**
- [ ] **Step 6: commit** — `feat(plan-engine): plan revision with postpone and reduce strategies`

---

## Task 37: 修訂端點與 accept / reject

**Files:**
- Create: `services/api/application/{create_revision.py,list_revisions.py,get_revision.py,decide_revision.py}`
- Modify: `services/api/adapters/http/plans_router.py`
- Test: `tests/application/api/test_revisions.py`, `tests/application/test_end_to_end_revision.py`

**Interfaces:**
- Produces:
  ```python
  class RevisionView(BaseModel):
      id: UUID; plan_id: UUID; strategy: str; status: str
      rationale: str | None
      diff: list[TaskDiffEntry]
      summary: RevisionDiffSummary
      created_at: datetime; decided_at: datetime | None

  class RevisionDiffSummary(BaseModel):
      added: int; moved: int; removed: int
      shortened: int; lengthened: int; unchanged: int

  class CreateRevision:
      async def __call__(self, user_id: UUID, plan_id: UUID, strategy: str,
                         note: str | None) -> CreateRevisionResult: ...
      # plan 必須是 active，否則 Conflict
      # revisions.has_open(plan_id) 為 True -> Conflict（一次只能有一個 pending/proposed）
      # strategy 必須是 postpone|reduce，否則 InvalidInput
      # enqueue PlanReviseJobV1

  class DecideRevision:
      async def __call__(self, user_id: UUID, plan_id: UUID, revision_id: UUID,
                         decision: Literal["accept", "reject"]) -> RevisionView: ...
      # 狀態必須是 proposed，否則 Conflict
      # accept：cutoff=今天 00:00（owner timezone）；
      #         plan_tasks.replace_from(plan_id, cutoff, proposed_tasks)
      #         更新 plans.deadline / duration_weeks / goal_statement / template / structure
      #         set_status("accepted", decided_at=now)
      #         有 google_calendar 匯出時 enqueue incremental
      # reject：只寫 status="rejected"，計畫不動
  ```

- [ ] **Step 1: 寫失敗測試**

```python
async def test_create_revision_on_draft_plan_conflicts(): ...
async def test_second_open_revision_conflicts(): ...
async def test_invalid_strategy_is_422(): ...

async def test_get_revision_returns_diff_and_summary():
    v = await c.get_revision(U, P, R)
    assert v.summary.moved + v.summary.added + v.summary.removed > 0
    assert len(v.diff) == sum(v.summary.model_dump().values())

async def test_accept_replaces_future_tasks_only():
    before_past = await c.plan_tasks.list(P, None, TODAY)
    await c.decide_revision(U, P, R, "accept")
    assert await c.plan_tasks.list(P, None, TODAY) == before_past
    assert (await c.plan_tasks.list(P, TODAY, None)) != []

async def test_accept_updates_plan_deadline_for_postpone():
    old = (await c.get_plan(U, P)).deadline
    await c.decide_revision(U, P, R, "accept")
    assert (await c.get_plan(U, P)).deadline > old

async def test_accept_updates_goal_statement_for_reduce(): ...

async def test_accept_enqueues_incremental_export_when_exported():
    assert c.queue.enqueued[-1] == ExportJobV1(plan_id=P, target="google_calendar",
                                               mode="incremental")

async def test_reject_leaves_plan_untouched():
    before = await c.plan_tasks.list(P, None, None)
    await c.decide_revision(U, P, R, "reject")
    assert await c.plan_tasks.list(P, None, None) == before

async def test_decide_on_pending_revision_conflicts(): ...

async def test_end_to_end_missed_then_revise_then_accept(client, container):
    """PRD M4.5 驗收。"""
    # 1. 產計畫 → 啟用 → 匯出 Calendar
    # 2. check-in 把本週任務標 missed
    # 3. POST /plans/{id}/revisions {"strategy": "postpone"} → 202
    # 4. drain engine queue
    # 5. GET .../revisions/{rev} → status=proposed，diff 非空
    # 6. POST .../accept → 未來任務被取代、deadline 往後、
    #    佇列多一筆 export.push incremental
    # 7. drain api queue → FakeCalendar 收到 update/create
```

- [ ] **Step 2–4: 確認失敗 → 實作 → 轉綠**
- [ ] **Step 5: `make check` 全綠後 commit** — `feat(api): revision endpoints with accept and reject`

### M4.5 驗收

- [ ] `test_end_to_end_missed_then_revise_then_accept` 綠
- [ ] commit: `chore: M4.5 revisions complete`

---

# Phase M5 — 硬化

## Task 38: 觀測落地與限流

**Files:**
- Create: `packages/llm/observability.py` 的 `DbLlmObserver`（放 `packages/repo/pg/llm_call.py` 已有 repo）
- Create: `services/api/adapters/http/middleware.py`
- Create: `packages/logging/__init__.py`（結構化 log helper）
- Modify: 三個 `container.py`
- Test: `tests/unit/api/test_rate_limit.py`, `tests/application/test_llm_observability.py`

**Interfaces:**
- Produces（PRD 7.8 / 10）：
  ```python
  # packages/logging
  def configure_logging(service: str) -> None: ...    # JSON lines to stdout
  def bind_job_id(job_id: str) -> AbstractContextManager[None]: ...
  def get_logger(name: str) -> Logger: ...
  # 每筆 log 都帶 service、job_id（若在 job 情境中）、timestamp、level、event

  # DbLlmObserver
  class DbLlmObserver:
      def __init__(self, repo: LlmCallRepo) -> None: ...
      async def record(self, log: LlmCallLog) -> None: ...

  # middleware.py
  class RateLimitMiddleware:
      def __init__(self, app: ASGIApp, cache: CachePort, limit: int = 60,
                   window_seconds: int = 60) -> None: ...
      # key = f"rl:{user_id or client_ip}:{minute}"，超過回 429 + Retry-After
      # 排除 /health 與 /v1/files/*
  ```

- [ ] **Step 1: 寫失敗測試** — 同一 user 第 61 次請求回 429 且帶 `Retry-After`；不同 user 互不影響；視窗過後恢復；`/health` 不受限；一次 LLM 呼叫在 `llm_calls` 落一列且欄位齊全（`prompt_version`、`attempts`、`degraded`）；降級時 `degraded=True`。
- [ ] **Step 2–4: 確認失敗 → 實作 → 轉綠**
- [ ] **Step 5: 每個 worker handler 進入時 `bind_job_id`，加測試斷言 log 帶 job_id**
- [ ] **Step 6: commit** — `feat: structured logging, llm call persistence, rate limiting`

---

## Task 39: `R2Storage`（接回 Cloudflare R2）

**Files:**
- Create: `packages/storage/r2.py`
- Modify: `packages/storage/__init__.py`, `services/api/container.py`, `services/api/settings.py`, `.env.example`
- Test: `tests/unit/packages/storage/test_r2.py`

**Interfaces:**
- Produces:
  ```python
  class R2Storage:
      def __init__(self, *, account_id: str, access_key_id: str,
                   secret_access_key: str, bucket: str,
                   endpoint_url: str | None = None) -> None: ...
      # boto3 client("s3", endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
      #               region_name="auto", signature_version="s3v4")
      # presign_put/get -> generate_presigned_url("put_object"/"get_object")
      # get 對 NoSuchKey -> raise ObjectNotFound
      # 所有同步 boto3 呼叫包在 asyncio.to_thread 內
  ```
  `ApiSettings` 增 `storage_backend: Literal["local","memory","r2"]` 與 `r2_account_id / r2_access_key_id / r2_secret_access_key / r2_bucket`。`build_container` 依 `storage_backend` 選實作——**這是整個 R2 接回的唯一改動點，任何 use case 都不變**（PRD 9.2 第 8 條）。

- [ ] **Step 1: 寫失敗測試**（`uv add boto3 moto[s3]`；用 `moto` 的 mock S3 跑與 Task 3 相同的契約測試：put/get round-trip、missing raise `ObjectNotFound`、delete 冪等、presign 產生含 bucket 與 key 的 URL）
- [ ] **Step 2–4: 確認失敗 → 實作 → 轉綠**
- [ ] **Step 5: 把 Task 3 的 `tests/unit/packages/storage/test_contract.py` 的 fixture params 加入 `"r2"`（用 moto），確認三個實作跑同一份契約全綠**
- [ ] **Step 6: 在 `.env.example` 與 `README.md` 寫清楚「切到 R2 只需改 `STORAGE_BACKEND=r2` 與四個 R2 變數」**
- [ ] **Step 7: commit** — `feat(storage): cloudflare r2 adapter behind the same port`

---

## Task 40: 容器化與端到端冒煙

**Files:**
- Create: `Dockerfile`, `docker-compose.yml`, `.dockerignore`
- Create: `scripts/smoke.sh`
- Modify: `README.md`
- Test: 手動 + `scripts/smoke.sh`

**Interfaces:**
- Produces：
  - `Dockerfile`：單一映像，`ENTRYPOINT ["python", "-m"]`、`CMD ["cmd.api_server"]`（PRD 8.1）。
  - `docker-compose.yml`：`postgres`、`redis`、`api`（`cmd.api_server`）、`api-worker`（`cmd.api_worker`）、`engine`（`cmd.plan_engine_worker`）、`role-model`（`cmd.role_model_server`）六個服務，全部共用同一個 image。**注意本機已有 5432 / 6379 佔用**，compose 內的 postgres/redis 對外映射改為 `5433` / `6380`，並在 README 說明「本機開發直接用既有的 5432/6379，compose 僅供整套隔離驗證」。
  - `scripts/smoke.sh`：對執行中的 API 依序跑：健康檢查 → 假登入取 JWT（`LOGIN_FAKE=1` 時 `POST /v1/auth/google` 接受 `{"code": "fake:<email>"}`）→ 建 plan session → 輪詢至 `questioning` → 送答案 → 輪詢至 `done` → 取三份計畫 → 啟用一份 → 列出 tasks → 標一筆 done → 匯出 markdown → 印出結果。任何一步非預期就 `exit 1`。

- [ ] **Step 1: 寫 `Dockerfile`（多階段：`uv sync --frozen --no-dev` → runtime）**
- [ ] **Step 2: 寫 `docker-compose.yml`**
- [ ] **Step 3: 寫 `scripts/smoke.sh`**
- [ ] **Step 4: 對本機（非 compose）跑一次冒煙**

```bash
uv run alembic upgrade head
uv run python -m cmd.seed_role_models
uv run python -m cmd.api_server &          # 8000
uv run python -m cmd.role_model_server &   # 8001
uv run python -m cmd.api_worker &
uv run python -m cmd.plan_engine_worker &
LLM_ADAPTER=fake bash scripts/smoke.sh
```
Expected: 印出三份計畫的 id 與 markdown 前 20 行，`exit 0`

- [ ] **Step 5: 對 compose 跑一次冒煙**

```bash
docker compose up -d --build
docker compose exec api python -m alembic upgrade head
docker compose exec api python -m cmd.seed_role_models
API_BASE=http://127.0.0.1:8000 bash scripts/smoke.sh
docker compose down -v
```
Expected: `exit 0`

- [ ] **Step 6: 更新 `README.md`**（專案簡介、架構圖、本機啟動、環境變數、測試指令、R2 切換說明、六個入口說明）
- [ ] **Step 7: commit** — `chore: dockerfile, compose, end-to-end smoke script`

---

## Task 41: Notion / Google Sheets 匯出（P1，可選）

**Files:**
- Create: `services/api/adapters/{notion.py,google_sheets.py}`
- Modify: `services/api/application/push_export.py`, `container.py`
- Test: `tests/application/api/test_export_sheets.py`, `test_export_notion.py`

**Interfaces:**
- Produces：
  ```python
  class SheetsPort(Protocol):
      async def create_spreadsheet(self, access_token: str, title: str) -> str: ...
      async def write_rows(self, access_token: str, spreadsheet_id: str,
                           rows: Sequence[Sequence[str]]) -> None: ...

  class NotionPort(Protocol):
      async def create_page(self, token: str, parent_id: str, title: str,
                            markdown: str) -> str: ...
  ```
  `PushExport` 依 `job.target` 分派；Sheets 用既有的 Google token（`spreadsheets` scope 已在 Task 16 一併授權），Notion 需新增 `oauth_connections(provider="notion")`。欄位為 `render_markdown` 的資料來源攤平成表格：`週次 | 日期 | 時間 | 任務 | 類型 | 狀態`。

- [ ] **Step 1–4: TDD 走完（Fake ports，斷言列數與標題）**
- [ ] **Step 5: commit** — `feat(api): google sheets and notion export`

**此 task 為 P1，若時間不足可跳過，不影響 MVP 驗收。**

---

# 最終驗收清單

- [ ] `make check` 全綠（`ruff` → `mypy --strict` → `lint-imports` → `pytest`，全程不起 Docker）
- [ ] `uv run pytest -m integration` 對本機 PostgreSQL 全綠
- [ ] `uv run alembic check` 回 "No new upgrade operations detected."
- [ ] `bash scripts/smoke.sh` 端到端 `exit 0`
- [ ] PRD 第 5 節的每一個 API 端點都有對應的 router 與至少一個測試
- [ ] PRD 7.7 表列的四個 prompt 都存在且有 fixture
- [ ] PRD 9.2 第 6 條：每個 port 都有正式 + Fake 實作
- [ ] 三個 service 與六個 package 各有 `README.md`
- [ ] `CONTRIBUTING.md` 含 PRD 第 9 節全部 17 條

---

## Self-Review 紀錄

**Spec coverage**（PRD 章節 → task）：
1 產品概述 → 全部；2 架構 → T1/T13/T22/T27；3.1 狀態機 → T17/T22；3.2 生成時序 → T22/T23/T24；
3.3 onboarding → T24；3.4 指標評估 → T21/T22；3.5 生命週期與同步 → T30/T34/T35；
3.6 OAuth → T16；3.7 check-in → T32；3.8 修訂 → T36/T37；3.9 推薦 → T28；3.10 匯入抽象 → T11/T12；
4.1 ERD → T6；4.2 owner → T6（docstring）；4.3.1 template → T17；4.3.1.1 難度 → T18；
4.3.2 scheduler → T19；4.3.3 表 → T6；4.3.4 Calendar 對應 → T34；4.3.5 Markdown → T33；
4.3.6 前端對應 → T24/T30/T31/T37；5 API → T13–T16、T24、T27–T37；5.1 佇列 → T5；
6 選型 → T1；7 LLM 抽象 → T8/T9/T10；7.5 驗證鏈 → T9/T23/T36；7.8 觀測 → T9/T38；
8 架構與 cmd/ → T1/T13/T15/T24/T27/T29/T40；9 紀律 → T1（.importlinter + CONTRIBUTING）；
10 非功能 → T15（20MB/15 分）、T38（限流、log）、T22（輪詢）；11 里程碑 → Phase 對應；
12 role model 資料設計 → T25/T26/T29；13 readiness → T21；14 seed → T29。
**未涵蓋（刻意）**：15 待決事項（託管平台、本地模型選型）——不影響程式碼，`config/llm.yaml` 已預留。

**已知的刻意偏離 PRD**：
1. **R2 延後**：`StoragePort` 的 MVP 正式實作是 `LocalFileStorage`，`R2Storage` 在 T39 補上，切換只改 `STORAGE_BACKEND`。（依使用者指示）
2. **Redis port 是 6379**，非 PRD 討論中提到的 6397。
3. **新增兩張 PRD ERD 未列的表**：`plan_exports`（PRD 5 的 `GET /plans/{id}/export` 需要）、`llm_calls`（PRD 7.8 需要）。
4. **不裝 `openai` / `anthropic` SDK**，兩個 adapter 直接用 `httpx`——port 邊界更乾淨。
5. **`Pacing` 在 plan_engine 與 role_model 各定義一份**（services 之間禁止 import），以 JSON 為契約。

