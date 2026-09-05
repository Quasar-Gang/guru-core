# guru-core 資料庫結構詳解

> 對應 `packages/repo/models.py`，schema 的權威來源是 `migrations/` 底下的 Alembic migration。
> 欄位表由 ORM 定義直接產出；若與程式碼不符，以程式碼與 migration 為準。
>
> 驗證方式：`uv run alembic check` 會比對 model 與 migration，CI 每次都跑。

---

## 1. 全貌

單一 PostgreSQL 資料庫，14 張表，三個 service 共用。**沒有跨服務的資料庫**，也沒有 read replica——MVP 階段的一致性靠單一資料庫本身，不靠協調。

```
users ─┬─ profiles                    使用者與問卷
       ├─ oauth_connections           Google 授權
       ├─ imports ── documents        匯入與解析結果
       └─ plan_sessions ─┬─ followup_rounds     追問回合
                         └─ plans ─┬─ plan_tasks       展開後的每一筆任務
                                   ├─ checkins         每日打卡
                                   ├─ plan_revisions   修訂提案
                                   └─ plan_exports     匯出狀態

role_models    獨立，被 plan_sessions 參照
llm_calls      獨立，僅追加，用於觀測
```

### 1.1 表的擁有者

**一張表只有一個 service 能寫，其餘只讀。** 這條規則寫在每個 model 的 docstring 第一行，並由 `tests/unit/packages/repo/test_models_metadata.py` 強制檢查——沒有 `Owner:` 開頭的 docstring 會讓測試失敗。

| 表 | 寫入者 | 備註 |
|---|---|---|
| `users`、`profiles`、`oauth_connections` | API Service | 使用者身分與授權 |
| `imports`、`documents` | API Service | 匯入流程含 worker |
| `checkins`、`plan_exports` | API Service | 使用者操作的結果 |
| `plan_sessions`、`followup_rounds` | Plan Engine | API Service 負責建立列與寫入答案，狀態轉移由 Plan Engine 負責 |
| `plans`、`plan_tasks` | Plan Engine 建立 | 建立後的管理欄位（`title`、`status`、任務完成與時間）由 API Service 寫 |
| `plan_revisions` | Plan Engine 建立與寫 `proposed_tasks` / `diff` | `status` 的決定由 API Service 寫 |
| `role_models` | Role Model Service | 團隊透過 API key 寫入 |
| `llm_calls` | 所有 service | 僅追加，永不更新 |

為什麼要這條規則：兩個 service 同時寫同一張表，衝突會以資料損毀的形式出現，而不是以錯誤的形式出現。限制寫入方之後，任何一列的變更歷史都只有一個來源可查。

### 1.2 共通約定

| 約定 | 內容 |
|---|---|
| 主鍵 | 一律 `uuid`，應用層以 `uuid4()` 產生，不用序號——避免跨 service 的序號協調，也不洩漏資料量 |
| 時間 | 一律 `timestamptz`，以 UTC 儲存。程式內禁用 `datetime.utcnow()`，一律 `datetime.now(UTC)` |
| 使用者本地時間 | 不存在資料庫，由 `profiles.timezone`（IANA 字串）在讀取時換算 |
| 刪除 | 所有外鍵 `ON DELETE CASCADE`。刪一個 user 會連帶清掉他的全部資料 |
| 軟刪除 | 只有 `role_models.active` 與 `plans.archived_at` 兩處，且語意不同：前者是停用、後者是封存 |
| JSONB | 用於 LLM 產出與結構會演進的內容。**不用於需要查詢條件的欄位**——那些一律拉成獨立欄位 |
| 空值 | 「還沒發生」用 `NULL`（如 `completed_at`），「空集合」用 `[]` / `{}` 而非 `NULL` |

---

## 2. 身分與授權

### `users`

登入身分。Google 是唯一的登入方式，`google_sub` 是 Google 的穩定使用者識別碼（不是 email——email 可以更換）。

| 欄位 | 型別 | 可空 | 預設 |
|---|---|:--:|---|
| `id` | uuid |  | PK |
| `email` | varchar(320) |  |  |
| `google_sub` | varchar(128) |  |  |
| `created_at` | timestamptz |  | `now()` |

- `email` 與 `google_sub` 各自 UNIQUE。查詢一律用 `google_sub`，`email` 僅供顯示與識別。

### `profiles`

問卷答案與時區。與 `users` 一對一，主鍵就是 `user_id`。

| 欄位 | 型別 | 可空 | 預設 |
|---|---|:--:|---|
| `user_id` | uuid → `users.id` |  | PK |
| `answers` | jsonb |  | `{}` |
| `timezone` | varchar(64) |  | `UTC` |
| `updated_at` | timestamptz |  | `now()` |

- `answers` 對應 `config/readiness_metrics.yaml` 的 `helpful` 指標鍵（`difficulty_preference`、`accountability`、`time_method`、`past_attempts`、`constraints`）。MVP 不強制 schema，只驗證是 dict 且 key 皆為字串——這些欄位只影響 prompt 內容，寫錯不會壞掉系統。
- `timezone` 寫入時會通過 `zoneinfo.ZoneInfo` 驗證；讀取時若解析失敗會退回 UTC，避免一個壞值讓整條讀取路徑失效。

### `oauth_connections`

Google 授權連線。**登入與行事曆授權是兩件事**：登入只要 `openid email profile`，連結 Calendar 才要 `calendar.readonly`、`calendar.events`、`spreadsheets`。

| 欄位 | 型別 | 可空 | 預設 |
|---|---|:--:|---|
| `id` | uuid |  | PK |
| `user_id` | uuid → `users.id` |  |  |
| `provider` | varchar(32) |  |  |
| `encrypted_refresh_token` | bytea |  |  |
| `scopes` | text |  | `` |
| `expires_at` | timestamptz | ✓ |  |
| `revoked_at` | timestamptz | ✓ |  |
| `created_at` | timestamptz |  | `now()` |

- `encrypted_refresh_token` 以 Fernet 加密後儲存（金鑰來自 `OAUTH_TOKEN_ENC_KEY`）。**App 端從頭到尾拿不到 Google token**，只拿我們自己簽的 JWT。
- `UNIQUE (user_id, provider)`：一個使用者對一個 provider 只有一筆連線，重新授權是覆寫而非新增。
- `revoked_at` 非空代表需要重新授權。Worker 拿到 Google 的 `invalid_grant` 時會寫入這個欄位，`GET /v1/integrations` 據此回報 `needs_reauth`。

---

## 3. 匯入

### `imports`

一次匯入 = 一列。來源可以是使用者上傳的檔案，也可以是連結的 Google Calendar。

| 欄位 | 型別 | 可空 | 預設 |
|---|---|:--:|---|
| `id` | uuid |  | PK |
| `user_id` | uuid → `users.id` |  |  |
| `source` | varchar(32) |  |  |
| `format` | varchar(16) |  |  |
| `storage_key` | text |  | `` |
| `filename` | text |  | `` |
| `status` | varchar(16) |  | `pending` |
| `error` | text | ✓ |  |
| `created_at` | timestamptz |  | `now()` |

- `status` 的流程：`pending`（已 presign，檔案還沒上傳）→ `queued`（上傳完成，已進佇列）→ `parsed` 或 `failed`。
- `storage_key` 形如 `imports/{user_id}/{uuid}/{safe_filename}`。Google Calendar 匯入沒有原始檔，此欄為空字串。
- `error` 記錄解析失敗的原因。**解析 worker 永不拋出例外**——任何失敗都寫進這裡並把 status 設為 `failed`，否則佇列會不斷重試一個永遠不會成功的任務。

### `documents`

解析結果。Plan Engine 只認識這個格式，不認識來源與檔案格式。

| 欄位 | 型別 | 可空 | 預設 |
|---|---|:--:|---|
| `id` | uuid |  | PK |
| `import_id` | uuid → `imports.id` |  |  |
| `events` | jsonb |  | `[]` |
| `text_chunks` | jsonb |  | `[]` |
| `created_at` | timestamptz |  | `now()` |

- `events`：有時間的內容（行事曆事件、含日期欄位的表格列），每筆有 `title` / `start_at` / `end_at` / `all_day`。Scheduler 用它避開既有行程。
- `text_chunks`：其餘內容，每筆有 `text` / `section` / `order`。進入 prompt context。
- `UNIQUE (import_id)`：一次匯入只產生一份 Document。重新解析是覆寫。

---

## 4. Role model

### `role_models`

兩類角色模型。**沒有預設分類，tag 是唯一的分類機制**。

| 欄位 | 型別 | 可空 | 預設 |
|---|---|:--:|---|
| `id` | uuid |  | PK |
| `kind` | varchar(16) |  |  |
| `name` | varchar(128) |  |  |
| `tags` | text[] |  | `[]` |
| `content` | jsonb |  | `{}` |
| `active` | bool |  | `True` |
| `version` | int |  | `1` |
| `created_at` | timestamptz |  | `now()` |
| `updated_at` | timestamptz |  | `now()` |

- `kind` 只有兩個值：
  - `trait`（基本特質類）——內容主體是 `content.pacing` 的**數值約束**，直接變成生成計畫時的硬上限。
  - `persona`（角色卡類）——內容主體是 `content.sections` 的**結構化敘述**，作為方法論參考。
- `tags` 是 `namespace:value` 形式的字串陣列，帶 GIN 索引。`domain:` 與 `goal:` 用於硬過濾（SQL `WHERE`），`constraint:` 用於硬排除，其餘只影響排序分數。命名空間白名單在 `config/tag_vocab.yaml`。
- `content` 是 discriminated union：`trait` 必須有 `pacing` 且不得有 `sections`，`persona` 反之。寫入時型別不符直接拒絕。
- `version` 每次更新遞增。`plan_sessions.context_snapshot` 保存的是**當時渲染出來的文字**，所以之後改 role model 不會影響已產生的計畫。

`content` 的形狀（`services/role_model/domain/content.py`）：

```yaml
# kind = trait
summary: string                      # ≤ 120 字元
pacing:
  sessions_per_week: [min, max]      # 每週次數上下限，Scheduler 的硬上限
  session_minutes: [min, max]        # 單次時長上下限
  rest_days_min: int                 # 每週至少休息幾天
  progression_rate: float            # 每兩週增量上限，0.10 = 10%
  missed_policy: none | same-week | next-day
  deload_every_weeks: int | null
  intensity_bias: low | medium | high
provenance: {sources[], confidence, author, notes}

# kind = persona
summary: string
sections:
  principles: string[]               # 3–5 條原則
  weekly_structure: string           # 一週長什麼樣，≤ 150 字
  progress_metrics: string[]         # 怎麼判斷有進步
  pitfalls: string[]                 # 常見失敗點
  applicability: {good_for[], not_for[]}
  example_milestones: string[]       # 含具體數字的里程碑
provenance: {sources[], confidence, author, notes}
```

---

## 5. 計畫生成

### `plan_sessions`

一次計畫生成的完整過程。這是整個系統最複雜的一張表，因為它同時是**狀態機**與**可重現性的錨點**。

| 欄位 | 型別 | 可空 | 預設 |
|---|---|:--:|---|
| `id` | uuid |  | PK |
| `user_id` | uuid → `users.id` |  |  |
| `trait_role_model_id` | uuid → `role_models.id` | ✓ |  |
| `persona_role_model_id` | uuid → `role_models.id` | ✓ |  |
| `goal` | text |  |  |
| `intake` | jsonb |  | `{}` |
| `import_ids` | jsonb |  | `[]` |
| `use_calendar` | bool |  | `False` |
| `status` | varchar(16) |  | `collecting` |
| `round` | int |  | `0` |
| `context_snapshot` | jsonb | ✓ |  |
| `error` | text | ✓ |  |
| `created_at` | timestamptz |  | `now()` |
| `updated_at` | timestamptz |  | `now()` |

**狀態機**（`services/plan_engine/domain/session.py` 的 `TRANSITIONS` 是唯一定義）：

```
collecting ──► evaluating ──┬─► questioning ──► evaluating   (最多兩輪)
                            │
                            └─► generating ──► done
                     任何一步 LLM 重試耗盡 ──► failed
```

- `collecting`：剛建立，任務已進佇列還沒被處理。
- `evaluating`：正在判斷資訊是否足夠。
- `questioning`：等待使用者回答追問，`followup_rounds` 有一列待答。
- `generating`：資訊足夠，正在產生計畫。
- `done` / `failed`：終態，不再轉移。

**這張表是狀態的權威來源，Redis 只是快取。** 清空 Redis 不會遺失任何 session。

欄位的用途：

| 欄位 | 為什麼存在 |
|---|---|
| `goal` | 唯一必填的使用者輸入 |
| `intake` | onboarding 第一步順帶問到的 `horizon` / `capacity` / `baseline`，可以是空的 |
| `import_ids` | 本次納入的匯入。JSONB 陣列存 UUID 字串——它只被整批讀取，不需要索引或 join |
| `use_calendar` | 建立當下是否已連結 Calendar。**存起來而不是每次查**，因為它決定 Scheduler 要不要避開既有行程，也讓計畫可重現 |
| `round` | 已完成的追問輪數，上限來自 `config/readiness_metrics.yaml` 的 `max_followup_rounds` |
| `context_snapshot` | 送進 LLM 的完整 context。**可重現性的來源**——role model 之後改了、文件之後刪了，都不影響回頭理解這份計畫是怎麼來的 |
| `error` | 失敗原因，供 App 顯示 |

### `followup_rounds`

一輪追問 = 一列。

| 欄位 | 型別 | 可空 | 預設 |
|---|---|:--:|---|
| `id` | uuid |  | PK |
| `session_id` | uuid → `plan_sessions.id` |  |  |
| `round_no` | int |  |  |
| `questions` | jsonb |  | `[]` |
| `answers` | jsonb | ✓ |  |
| `answered_at` | timestamptz | ✓ |  |
| `created_at` | timestamptz |  | `now()` |

- `questions`：LLM 產出的題目，每題有 `id` / `metric_id` / `text` / `options`（恰好 3 個）/ `allow_custom` / `allow_skip`。
- `answers`：使用者的回答，每筆有 `question_id` / `choice` / `custom` / `skipped`。未回答時為 `NULL`。
- `UNIQUE (session_id, round_no)`：一輪只能有一列。`round_no` 從 0 起算。

### `plans`

一份計畫。**一次 session 產生三列**（easy / hard / extremely_hard），共用同一個目標與達成標準，只有期程與密度不同。

| 欄位 | 型別 | 可空 | 預設 |
|---|---|:--:|---|
| `id` | uuid |  | PK |
| `user_id` | uuid → `users.id` |  |  |
| `session_id` | uuid → `plan_sessions.id` |  |  |
| `title` | varchar(128) |  |  |
| `difficulty` | varchar(16) |  |  |
| `status` | varchar(16) |  | `draft` |
| `goal_statement` | text |  |  |
| `duration_weeks` | int |  |  |
| `start_date` | date |  |  |
| `deadline` | date |  |  |
| `template` | jsonb |  | `{}` |
| `structure` | jsonb |  | `{}` |
| `activated_at` | timestamptz | ✓ |  |
| `archived_at` | timestamptz | ✓ |  |
| `created_at` | timestamptz |  | `now()` |
| `updated_at` | timestamptz |  | `now()` |

- `difficulty` 不在 `template` 裡，而是這張表的欄位。LLM 只產一份不帶難度標籤的基準模板，三份由程式依 `config/difficulty_coefficients.yaml` 的係數推導。
- `template` 是 LLM 產出的 `PlanTemplate` **原文**。修訂時要重跑 Scheduler，需要這份原始的相對排程。
- `structure` 是前端直接讀的展示資料：`{phases[], success_criteria[], assumptions[]}`。
- `deadline` 是權威截止日。`postpone` 策略只改這個欄位與 `duration_weeks`。
- `status` 的規則：**同一個 session 同時只能有一份 `active`**。改選另一個難度時，程式會把同 session 的其他計畫設回 `draft`。內建行事曆與匯出只作用於 `active` 的計畫。

```
draft ──► active ──► archived
  ▲         │           │
  └─────────┘           │
  ▲                     │
  └─────────────────────┘   (還原)
```

`template` 的形狀（`services/plan_engine/domain/template.py`）：

```yaml
title: string                    # ≤ 40 字元
goal_statement: string           # 一句可衡量的目標
duration_weeks: int              # 1–104
assumptions: string[]            # 缺資料時補的假設，前端會顯示
success_criteria: string[]       # 怎麼算達標
phases:                          # 1–6 個，必須連續且完整覆蓋 duration_weeks
  - index: int
    name: string
    week_start: int              # 相對週，從 0 起
    week_end: int
    focus: string
    milestone: {title, metric}
weekly_template:                 # 1–12 項，一週的骨架
  - key: string                  # 小寫底線，如 long_run；修訂時用它對齊
    title: string
    task_type: session | habit | checkpoint | rest
    day_hint: mon..sun | any | weekday | weekend
    slot_hint: morning | noon | evening | any
    duration_minutes: int        # 5–300
    description: string
    times_per_week: int          # 1–7
```

### `plan_tasks`

Scheduler 展開後的每一筆任務，帶絕對時間。這是內建行事曆、check-in 與 Calendar 匯出共同的資料來源。

| 欄位 | 型別 | 可空 | 預設 |
|---|---|:--:|---|
| `id` | uuid |  | PK |
| `plan_id` | uuid → `plans.id` |  |  |
| `template_key` | varchar(64) |  |  |
| `week_index` | int |  |  |
| `phase_index` | int |  | `0` |
| `occurrence` | int |  | `0` |
| `task_type` | varchar(16) |  |  |
| `title` | varchar(256) |  |  |
| `description` | text |  | `` |
| `start_at` | timestamptz |  |  |
| `end_at` | timestamptz |  |  |
| `all_day` | bool |  | `False` |
| `status` | varchar(16) |  | `pending` |
| `completed_at` | timestamptz | ✓ |  |
| `missed_reason` | text | ✓ |  |
| `external_ref` | varchar(256) | ✓ |  |
| `synced_at` | timestamptz | ✓ |  |
| `sort_order` | int |  | `0` |

- `UNIQUE (plan_id, template_key, week_index, occurrence)` 是這張表的核心。這組鍵**穩定**——修訂時用它比對新舊任務產生 diff，而不是比對標題。標題會變，鍵不會。
- `INDEX (plan_id, start_at)` 支撐週視圖與今日清單的日期區間查詢。
- `all_day` 為真時（`checkpoint` 與 `rest`），`start_at` 是當地日的 00:00、`end_at` 是次日 00:00。
- `status` 是 `pending` / `done` / `missed` / `skipped`。**完成情況記在這裡，不記在 Google Calendar**——事件過了時間不代表做了，Calendar 也沒有可靠的「標記完成」語意。
- `external_ref` 是 Google Calendar 的 eventId，`synced_at` 是最後同步時間。**`synced_at` 為 `NULL` 代表這筆需要重新同步**；改時間或改狀態都會把它清空，增量同步只處理這些。

---

## 6. 執行與修訂

### `checkins`

每日打卡。

| 欄位 | 型別 | 可空 | 預設 |
|---|---|:--:|---|
| `id` | uuid |  | PK |
| `plan_id` | uuid → `plans.id` |  |  |
| `checkin_date` | date |  |  |
| `task_results` | jsonb |  | `[]` |
| `note` | text | ✓ |  |
| `created_at` | timestamptz |  | `now()` |

- `UNIQUE (plan_id, checkin_date)`：一天一筆，重複提交是覆寫。
- `task_results` 是**該次提交的快照**，`plan_tasks.status` 才是權威值。保留快照是為了看得出「使用者當時是怎麼回報的」，即使任務後來被修訂取代。

### `plan_revisions`

一次修訂提案。

| 欄位 | 型別 | 可空 | 預設 |
|---|---|:--:|---|
| `id` | uuid |  | PK |
| `plan_id` | uuid → `plans.id` |  |  |
| `trigger` | varchar(32) |  | `manual` |
| `strategy` | varchar(16) |  |  |
| `trigger_detail` | jsonb | ✓ |  |
| `proposed_tasks` | jsonb | ✓ |  |
| `diff` | jsonb | ✓ |  |
| `rationale` | text | ✓ |  |
| `status` | varchar(16) |  | `pending` |
| `created_at` | timestamptz |  | `now()` |
| `decided_at` | timestamptz | ✓ |  |

- `strategy` 兩種：
  - `postpone`（延後）——保持目標與每週強度，把截止日往後推。LLM 不得改任務內容與密度。
  - `reduce`（降標）——保持截止日，把目標量縮到剩餘時間做得到的程度。LLM 不得動截止日。
- `status` 的流程：`pending`（已進佇列）→ `proposed`（LLM 產出完成，等使用者決定）→ `accepted` / `rejected`；LLM 失敗則為 `failed`。
- **同一個 plan 同時只能有一個 `pending` 或 `proposed` 的修訂。**
- `proposed_tasks` 的第一筆是 plan 層級的修補（新的 `goal_statement` / `duration_weeks` / `deadline` / `template` / `structure`），其餘才是任務。這是因為 repo port 沒有另外的欄位可以承載修訂後的 template——這個約定寫在 `services/plan_engine/domain/revision.py` 與 `services/api/application/decide_revision.py` 兩處。
- `diff` 以 `template_key + week_index + occurrence` 對齊，每筆標 `added` / `moved` / `removed` / `shortened` / `lengthened` / `unchanged`。前端直接渲染，不靠 LLM 描述變更。
- 修訂**只重排今天之後的任務**，已完成或已錯過的歷史不動。

### `plan_exports`

一個計畫對一個外部目標的匯出狀態。

| 欄位 | 型別 | 可空 | 預設 |
|---|---|:--:|---|
| `id` | uuid |  | PK |
| `plan_id` | uuid → `plans.id` |  |  |
| `target` | varchar(32) |  |  |
| `external_calendar_id` | varchar(256) | ✓ |  |
| `last_synced_at` | timestamptz | ✓ |  |
| `status` | varchar(16) |  | `queued` |
| `error` | text | ✓ |  |
| `created_at` | timestamptz |  | `now()` |

- `UNIQUE (plan_id, target)`：一個計畫對每個 target 只有一筆。
- `external_calendar_id`：Google Calendar 匯出會為每個計畫建立一個專屬的 secondary calendar（名為 `guru · {plan.title}`），事件都放在裡面。使用者想隱藏整份計畫只要關掉那個日曆；解除匯出時整個日曆刪掉，不會污染主日曆。
- `status`：`queued` / `synced` / `failed`。`error` 為 `reauth_required` 代表 Google 授權已失效。
- **單向同步**：guru-core → Calendar。使用者直接在 Calendar 上改時間，下次增量同步會把它改回來。

---

## 7. 觀測

### `llm_calls`

每次 LLM 呼叫一列，僅追加。

| 欄位 | 型別 | 可空 | 預設 |
|---|---|:--:|---|
| `id` | uuid |  | PK |
| `prompt_name` | varchar(64) |  |  |
| `prompt_version` | varchar(16) |  | `` |
| `provider` | varchar(32) |  | `` |
| `model` | varchar(128) |  | `` |
| `purpose` | varchar(16) |  |  |
| `input_tokens` | int |  | `0` |
| `output_tokens` | int |  | `0` |
| `latency_ms` | int |  | `0` |
| `attempts` | int |  | `1` |
| `degraded` | bool |  | `False` |
| `job_id` | varchar(64) | ✓ |  |
| `created_at` | timestamptz |  | `now()` |

這張表是**日後判斷「哪幾條路值得切到雲端模型」的唯一依據**，所以從 M0 就存在，而不是等到需要時才加。

- `attempts`：schema 或業務規則驗證失敗會回灌錯誤重試，這裡記錄總共試了幾次。
- `degraded`：重試耗盡後改用保守預設時為真。**這個比例是模型品質的直接指標**——`fallback rate` 應該低於 1%。
- 沒有外鍵到 `users`。這是刻意的：觀測資料不該因為使用者刪除帳號而消失，也不該讓觀測查詢需要 join 使用者表。

---

## 8. 索引

MVP 只有兩個顯式索引，其餘依賴主鍵與唯一約束自動建立的索引。

| 索引 | 表 | 支撐什麼查詢 |
|---|---|---|
| `ix_plan_tasks_plan_start` | `plan_tasks` | 週視圖與今日清單的日期區間查詢 `WHERE plan_id = ? AND start_at BETWEEN ? AND ?` |
| `ix_role_models_tags` (GIN) | `role_models` | tag 的集合運算 `tags && ARRAY[...]`（任一命中）與 `tags @> ARRAY[...]`（全部命中） |

刻意**不加**的索引：

- `plans.user_id`、`imports.user_id` 等外鍵欄位——資料量在使用者層級，全表掃描的成本遠低於維護索引。等實際慢了再加。
- `plan_sessions.status`——只有 worker 會依狀態查，而 worker 是拿著明確的 id 來的。

---

## 9. Migration

schema 只透過 Alembic 改，migration 與功能在同一個 commit。

```bash
uv run alembic revision --autogenerate -m "描述"   # 產生
uv run alembic upgrade head                        # 套用
uv run alembic check                               # 確認 model 與 migration 一致
```

`alembic check` 在 CI 每次都跑。它會抓到「改了 model 卻忘了產 migration」——那是最容易在部署時才炸開的一種錯。

`migrations/env.py` 用同步的 psycopg 驅動（把 `DATABASE_URL` 的 `+asyncpg` 換成 `+psycopg`），因為 Alembic 的 autogenerate 不需要非同步，多一層只會多一個出錯的地方。
