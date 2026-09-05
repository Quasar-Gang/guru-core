# guru-core API 指南

這份文件寫給要串接 guru-core 後端的前端／App 工程師。它不是端點清單——端點清單在
[`openapi.json`](openapi.json)，也可以直接看跑起來的 `/docs`（Swagger UI）與 `/redoc`。
這裡回答的是另一個問題：**要做完一個功能，該按什麼順序打哪些 API。**

閱讀順序建議：先看〈開始之前〉把認證與錯誤格式搞定，再看〈完整流程走一遍〉——
那一節是一條從登入到拿到計畫的可執行路徑，複製貼上就能跑。之後再依你正在做的畫面
跳到對應的功能章節。最後兩節（速查表、狀態機）是查閱用的。

| 節 | 內容 |
|---|---|
| [1. 開始之前](#1-開始之前) | base URL、JWT 與 X-API-Key、錯誤信封、限流、非同步端點通則 |
| [2. 完整流程走一遍](#2-完整流程走一遍) | 登入 → 建 session → 追問 → 三份計畫 → 啟用 → 任務 → 匯出 |
| [3. 依功能分節](#3-依功能分節) | 每個功能的步驟、端點與完整範例 |
| [4. 端點速查表](#4-端點速查表) | 全部 43 個端點，一行一個 |
| [5. 狀態機附錄](#5-狀態機附錄) | 五張表的狀態轉移 |

資料庫層面的欄位語意與約束，見 [`docs/db/schema.md`](../db/schema.md)；產品需求與設計取捨見
[`guru-core-PRD.md`](../../guru-core-PRD.md)。

---

## 1. 開始之前

### 1.1 Base URL 與版本

本機開發預設是：

```
http://127.0.0.1:8000
```

所有應用端點都在 `/v1` 底下，例如 `http://127.0.0.1:8000/v1/plans`。
只有 `GET /health` 不帶版本前綴。

Role Model Service 另外跑在 `8001`，但 **App 不直接打它**——`/v1/role-models/*`
由 API Service 代理轉發，你只要認一個 host。

### 1.2 認證

系統有兩種憑證，用在完全不同的對象上。

**JWT（Bearer token）——所有使用者端點。**

1. 前端自己跑完 Google 登入流程（scope 只要 `openid email profile`），拿到一次性 `code`。
2. 把 `code` 和你剛才用的 `redirect_uri` 一起 `POST /v1/auth/google`。
3. 拿回 **guru-core 自己簽的** `access_token`。Google 的 token 從頭到尾不會流到客戶端。
4. 之後每個請求帶 `Authorization: Bearer <access_token>`。

```
Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
```

Token 的有效期由 `JWT_TTL_SECONDS` 決定（預設 `2592000`，即 30 天）。過期後任何端點都會回
`401 unauthorized`，唯一的處理方式是重跑一次 `POST /v1/auth/google`——**沒有 refresh token 端點**。
實務上：App 啟動時打一次 `GET /v1/me`，`200` 就是已登入，`401` 就導回登入頁。

**`X-API-Key`——團隊內容工具專用。**

`POST /v1/role-models`、`PUT /v1/role-models/{id}`、`DELETE /v1/role-models/{id}` 這三個寫入端點
**不吃 JWT**，只認 `X-API-Key` header，值就是 Role Model Service 的 `ROLE_MODEL_API_KEY`。
這是給內容維運腳本用的，App 不該有這把 key，也不該呼叫這三個端點。

**不需要任何認證的端點**只有四個：`GET /health`、`POST /v1/auth/google`，以及兩個 presigned
檔案路由 `PUT /v1/files/{key}` 與 `GET /v1/files/{key}`（授權寫在 URL 的簽章 query 參數裡，
**打這兩個端點時千萬不要帶 `Authorization` header**）。

### 1.3 錯誤信封

只要不是 2xx，body 一律是同一個形狀：

```json
{
  "error": {
    "code": "not_found",
    "message": "no plan 6f1c... for this user"
  }
}
```

`code` 是機器判讀用的，**請用它來分支**；`message` 是給工程師看的除錯字串，不要拿去直接顯示給使用者，
也不要對它的內容做字串比對。

| code | HTTP | 意思 | 客戶端該怎麼做 |
|---|:--:|---|---|
| `invalid_input` | 422 | 參數格式錯、值超出範圍、或欄位缺漏 | 修正請求；這是客戶端的 bug 或使用者輸入問題 |
| `unauthorized` | 401 | 沒帶 token、token 壞掉或過期；`X-API-Key` 不符 | 重跑 `POST /v1/auth/google`，導回登入 |
| `forbidden` | 403 | presigned URL 簽章不符、用錯 operation、或已過期 | 重新取得 presigned URL |
| `not_found` | 404 | 資源不存在，**或不屬於這個使用者** | 當成不存在處理 |
| `conflict` | 409 | 與目前狀態衝突（計畫不是 active、session 不在 questioning、已有未決修訂…） | 重讀資源狀態再決定 |
| `illegal_transition` | 409 | 狀態機不允許這個轉移（`conflict` 的子類） | 檢查目前 status，別送同一個 status |
| `reauth_required` | 409 | Google 授權沒連或已失效 | 導去 `GET /v1/integrations/google/authorize` 重新連線 |
| `rate_limited` | 429 | 超過每分鐘配額 | 依 `Retry-After` 等待後重試 |
| `domain_error` | 500 | 上游服務（Role Model Service）不可用或回了預期外的狀態 | 降級顯示，不要當成使用者錯誤 |

兩個安全性設計要先知道：

- **`404` 一律代表「不屬於你」**。別人的 plan、session、import，跟一個從來不存在的 id 回應完全一樣，
  客戶端無法分辨，這是刻意的。
- **`403` 只出現在 `/v1/files/*`**。應用端點的越權存取一律以 `404` 表達。

### 1.4 限流

預設每個呼叫端**每分鐘 60 次請求**（`RATE_LIMIT_PER_MINUTE`）。「呼叫端」的判定是：
帶了有效 JWT 就以使用者為單位，否則以來源 IP 為單位——所以一個使用者不會吃掉另一個使用者的配額，
但同一個使用者的多台裝置共用同一份配額。

超過時回 `429`，並帶 `Retry-After: 60`。計數視窗從一波請求的第一次呼叫開始算，不是滑動視窗。

兩類路徑**豁免**限流：`/health`（存活探針）與 `/v1/files/*`（大檔上傳下載，用每分鐘請求數來管沒有意義）。

輪詢會吃配額，這點很重要：一個 session 每秒輪詢一次，一分鐘就用掉 60 次配額的全部。
**間隔 2–3 秒是合理值**，詳見下一節。

### 1.5 非同步端點的通則：202 + 輪詢

計畫生成、匯入解析、Calendar 匯出、計畫修訂都跑在佇列上。這些端點**不會等工作做完才回應**，
而是立刻回 `202 Accepted`，body 裡有兩個 id：

```json
{ "session_id": "9f3b2a10-4c2e-4f0e-9b21-6a3d5e7c8f01", "job_id": "arq:job:0b7c9d" }
```

為什麼是輪詢而不是同步等待？因為 LLM 那一段真的很慢。系統預設跑本機模型（Ollama），
一次 `generating` 從讀 context、呼叫模型、驗證輸出、必要時重試，到 Scheduler 展開絕對時間，
可能要**數十秒到數分鐘**——`LLM_TIMEOUT` 預設就給到 240 秒。用一個 HTTP 連線撐住這段時間，
在手機網路下幾乎必然斷線，而且斷線後客戶端無從得知工作到底做完了沒有。改成「立刻回 id、之後查詢」，
App 可以放心切到別的畫面、可以關掉再打開繼續看進度。

**要輪詢哪個東西？永遠是資源本身，不是 job。**

| 非同步動作 | 輪詢這個 | 看哪個欄位 |
|---|---|---|
| 產生計畫 | `GET /v1/plan-sessions/{session_id}` | `status`、`questions`、`plans`、`error` |
| 匯入解析 | `GET /v1/imports` | 該筆的 `status`、`error`、`event_count` |
| 計畫修訂 | `GET /v1/plans/{plan_id}/revisions/{revision_id}` | `status`、`diff`、`summary` |
| Calendar／Sheets 匯出 | `GET /v1/plans/{plan_id}/export` | 該 target 的 `status`、`error` |

`GET /v1/jobs/{job_id}` 也存在，但它只是佇列自己的粗略視角。**PostgreSQL 才是狀態的權威來源，
Redis 只是快取**——job 記錄壽命很短，一個早就完成的 job 會回 `status: "unknown"`，
那不是錯誤，只是記錄過期了。所以 `/v1/jobs/{job_id}` 適合拿來做「還在排隊 vs 已經在跑」的細緻進度提示，
**不適合拿來判斷成功或失敗**。

輪詢節奏建議：

- 前 10 秒每 2 秒一次，之後每 3–5 秒一次。
- 遇到 `429` 就依 `Retry-After` 退避，別硬打。
- App 進背景時停止輪詢，回前景時先打一次補上進度。
- 終態（`done` / `failed` / `parsed` / `synced` / `proposed`）就停。`failed` 是終態，**不能續跑**，
  只能重新發起一次。

---

## 2. 完整流程走一遍

這一節把「從登入到手上有一份可執行的計畫」這條最短路徑完整走一次。所有請求都可以直接複製執行
（把 `$TOKEN`、id 換成你自己的）。中間會跳過所有可選步驟：不上傳檔案、不連 Google、不挑 role model。
**唯一必填的使用者輸入就是一句目標。**

```
①  POST /v1/auth/google            拿 JWT
②  POST /v1/plan-sessions          丟出目標 → 202 {session_id}
③  GET  /v1/plan-sessions/{id}     輪詢 → status: questioning
④  POST /v1/plan-sessions/{id}/answers   回答追問 → 202
⑤  GET  /v1/plan-sessions/{id}     繼續輪詢 → status: done，拿到三份 draft 計畫
⑥  PATCH /v1/plans/{plan_id}       {"status": "active"} 選定一份
⑦  GET  /v1/plans/{plan_id}/tasks  拿到內建行事曆的任務
⑧  POST /v1/plans/{plan_id}/export {"target": "markdown"} 立刻拿到文件
```

### ① 登入

```bash
curl -s -X POST http://127.0.0.1:8000/v1/auth/google \
  -H 'content-type: application/json' \
  -d '{
        "code": "4/0AeanS0b...",
        "redirect_uri": "http://localhost:3000/oauth/callback"
      }'
```

```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiI3YzIx...",
  "token_type": "bearer",
  "user_id": "7c21e4d8-5a3b-4e91-8f22-1d0c9b6a4e33",
  "email": "mei@example.com",
  "is_new_user": true
}
```

把 token 存起來：

```bash
TOKEN='eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...'
```

> `is_new_user: true` 代表這是這個帳號的第一次登入，帳號會以空白 profile 與 `UTC` 時區建立。
> 這時把使用者帶去 onboarding（`PUT /v1/profile`）；`false` 就直接進 App。
>
> **登入不等於拿到 Calendar 權限。** 那是第二次、獨立的授權，見 [3.4](#34-google-連線oauth-兩段式授權)。

### ② 建立 plan session

```bash
curl -s -X POST http://127.0.0.1:8000/v1/plan-sessions \
  -H "authorization: Bearer $TOKEN" \
  -H 'content-type: application/json' \
  -d '{
        "goal": "12 週內把 5K 跑進 30 分鐘",
        "intake": {
          "horizon": "12 週",
          "capacity": "平日晚上兩次，週末一次"
        }
      }'
```

```json
{
  "session_id": "9f3b2a10-4c2e-4f0e-9b21-6a3d5e7c8f01",
  "job_id": "plan-generate-0b7c9d3e"
}
```

`202`。只有 `goal` 是必填，`intake` 是自由格式的物件——你在 onboarding 順手問到什麼就放什麼，
**沒問到的東西不用假造，系統會在追問回合裡補**。

### ③ 輪詢，等到追問

```bash
curl -s http://127.0.0.1:8000/v1/plan-sessions/9f3b2a10-4c2e-4f0e-9b21-6a3d5e7c8f01 \
  -H "authorization: Bearer $TOKEN"
```

前幾次會拿到 `{"status": "collecting", ...}` 或 `{"status": "evaluating", ...}`，繼續等。
資訊不足時會變成：

```json
{
  "id": "9f3b2a10-4c2e-4f0e-9b21-6a3d5e7c8f01",
  "status": "questioning",
  "round": 1,
  "goal": "12 週內把 5K 跑進 30 分鐘",
  "questions": [
    {
      "id": "q1",
      "metric_id": "baseline",
      "text": "你現在跑 5K 大概要多久？",
      "options": ["還沒完整跑完過 5K", "大約 35–40 分鐘", "大約 30–34 分鐘"],
      "allow_custom": true,
      "allow_skip": true
    },
    {
      "id": "q2",
      "metric_id": "capacity",
      "text": "平常大概能怎麼安排跑步時間？",
      "options": [
        "平日 2 個晚上 + 週六早上，每次約 40 分",
        "只有週末，兩天各 60 分",
        "幾乎每天早上 20–30 分"
      ],
      "allow_custom": true,
      "allow_skip": true
    }
  ],
  "plans": [],
  "error": null
}
```

每題最多 3 個選項，選項是依這個使用者的 context 生出來的具體安排，不是通用區間。
`allow_custom` 為 true 表示可以填自由文字，`allow_skip` 為 true 表示可以跳過。

### ④ 回答

每題**恰好給一種答案**：`choice`（選項原文）、`custom`（自由文字）或 `skipped: true`。
不想答的題目直接不放進陣列也可以。

```bash
curl -s -X POST \
  http://127.0.0.1:8000/v1/plan-sessions/9f3b2a10-4c2e-4f0e-9b21-6a3d5e7c8f01/answers \
  -H "authorization: Bearer $TOKEN" \
  -H 'content-type: application/json' \
  -d '{
        "answers": [
          { "question_id": "q1", "choice": "大約 35–40 分鐘" },
          { "question_id": "q2", "custom": "週二週四晚上各 40 分，週日早上 60 分" }
        ]
      }'
```

```json
{
  "session_id": "9f3b2a10-4c2e-4f0e-9b21-6a3d5e7c8f01",
  "job_id": "plan-continue-4a1f8c22"
}
```

又是 `202`。session 回到 `evaluating`，接著可能再問一輪（最多兩輪），也可能直接進 `generating`。
**做法跟第一次完全一樣：繼續輪詢同一個 session。**

### ⑤ 拿到三份計畫

```json
{
  "id": "9f3b2a10-4c2e-4f0e-9b21-6a3d5e7c8f01",
  "status": "done",
  "round": 1,
  "goal": "12 週內把 5K 跑進 30 分鐘",
  "questions": [],
  "plans": [
    {
      "id": "c4a17b62-3f8d-4b0a-9e51-2c7d6f0a1b34",
      "title": "5K 破 30 分・輕量版",
      "difficulty": "easy",
      "status": "draft",
      "duration_weeks": 15,
      "start_date": "2026-09-08",
      "deadline": "2026-12-21",
      "goal_statement": "在 15 週內把 5K 完賽時間縮短到 30 分鐘以內",
      "sessions_per_week": 3,
      "total_minutes_per_week": 105,
      "completion_rate": 0.0
    },
    {
      "id": "8b0e5d31-7c94-4a22-b6f8-05e3a9c17d20",
      "title": "5K 破 30 分・標準版",
      "difficulty": "hard",
      "status": "draft",
      "duration_weeks": 12,
      "start_date": "2026-09-08",
      "deadline": "2026-11-30",
      "goal_statement": "在 12 週內把 5K 完賽時間縮短到 30 分鐘以內",
      "sessions_per_week": 4,
      "total_minutes_per_week": 150,
      "completion_rate": 0.0
    },
    {
      "id": "2d6f9a44-1b53-4c8e-aa07-9f4b2e5c8d16",
      "title": "5K 破 30 分・進階版",
      "difficulty": "extremely_hard",
      "status": "draft",
      "duration_weeks": 10,
      "start_date": "2026-09-08",
      "deadline": "2026-11-16",
      "goal_statement": "在 10 週內把 5K 完賽時間縮短到 30 分鐘以內",
      "sessions_per_week": 5,
      "total_minutes_per_week": 200,
      "completion_rate": 0.0
    }
  ],
  "error": null
}
```

三份計畫是同一份模板用係數推導出來的三個難度，不是三次獨立生成——所以它們的結構一致，
差別在期程長度與每週負荷。**三份都是 `draft`，使用者還沒選。**

### ⑥ 選定一份

```bash
curl -s -X PATCH http://127.0.0.1:8000/v1/plans/8b0e5d31-7c94-4a22-b6f8-05e3a9c17d20 \
  -H "authorization: Bearer $TOKEN" \
  -H 'content-type: application/json' \
  -d '{"status": "active"}'
```

回應是完整的計畫詳情（同 `GET /v1/plans/{plan_id}`）。**同一個 session 的另外兩份會自動退回 `draft`**，
一個 session 永遠只有一份 active。

### ⑦ 讀任務

```bash
curl -s "http://127.0.0.1:8000/v1/plans/8b0e5d31-7c94-4a22-b6f8-05e3a9c17d20/tasks?from=2026-09-08&to=2026-09-14" \
  -H "authorization: Bearer $TOKEN"
```

```json
{
  "items": [
    {
      "id": "e91c7a05-8d24-4b6f-9013-7a5c2e8f4b61",
      "template_key": "easy_run",
      "week_index": 1,
      "phase_index": 0,
      "occurrence": 0,
      "task_type": "session",
      "title": "輕鬆跑 30 分鐘",
      "description": "全程用可以講話的配速，重點是把跑步變成習慣。",
      "start_at": "2026-09-08T12:00:00Z",
      "end_at": "2026-09-08T12:30:00Z",
      "all_day": false,
      "status": "pending",
      "completed_at": null,
      "missed_reason": null,
      "synced": false
    }
  ],
  "total": 1
}
```

`from` / `to` 是**使用者時區的本地日期，兩端都含**；`start_at` / `end_at` 回來的是 UTC 瞬時，
渲染時自己轉回使用者時區。

### ⑧ 匯出成 Markdown

```bash
curl -s -X POST http://127.0.0.1:8000/v1/plans/8b0e5d31-7c94-4a22-b6f8-05e3a9c17d20/export \
  -H "authorization: Bearer $TOKEN" \
  -H 'content-type: application/json' \
  -d '{"target": "markdown"}'
```

```json
{
  "target": "markdown",
  "mode": null,
  "job_id": null,
  "markdown": {
    "content": "# 5K 破 30 分・標準版\n\n## 達成標準\n- 5K 完賽時間 < 30:00\n...",
    "download_url": "http://127.0.0.1:8000/v1/files/exports/7c21e4d8/8b0e5d31.md?exp=1789012345&op=get&sig=6f2a...",
    "storage_key": "exports/7c21e4d8-5a3b-4e91-8f22-1d0c9b6a4e33/8b0e5d31.md"
  }
}
```

Markdown 是**唯一同步**的匯出目標：文件在這個請求裡就渲染好了，`content` 直接可用，
沒有 `job_id`、不用輪詢。`download_url` 大約 15 分鐘後失效，**要下載就現在下載，不要存起來之後用**。

到這裡最短路徑就走完了。剩下的功能——上傳資料、連 Google、每日 check-in、修訂、Calendar 匯出——
都是掛在這條主線旁邊的可選分支，接下來一節一節說。

---

## 3. 依功能分節

### 3.1 登入與帳號

| 端點 | 用途 |
|---|---|
| `POST /v1/auth/google` | 用 Google 的一次性 code 換 guru-core 的 JWT |
| `GET /v1/me` | 確認手上的 token 還有效，以及它屬於誰 |
| `GET /health` | 服務存活探針，免認證、免限流 |

流程只有一段：

```
前端跑 Google OAuth（scope: openid email profile）
        │  拿到 code
        ▼
POST /v1/auth/google { code, redirect_uri }
        │
        ├─ 200 → 存下 access_token；is_new_user 決定要不要進 onboarding
        └─ 401 unauthorized → code 錯／已用過／過期／redirect_uri 不符 → 重跑授權
```

`redirect_uri` 必須跟你當初向 Google 要 code 時用的那一個**完全一樣**，否則 Google 會拒絕交換，
你會拿到 `401`。這是最常見的接線錯誤。

App 啟動時的判斷：

```bash
curl -s http://127.0.0.1:8000/v1/me -H "authorization: Bearer $TOKEN"
```

```json
{ "user_id": "7c21e4d8-5a3b-4e91-8f22-1d0c9b6a4e33", "email": "mei@example.com" }
```

- `200` → 已登入，直接進 App。
- `401` → token 沒了或過期，導回登入頁。
- `404` → token 本身有效但使用者已被刪除，當成登出處理。

`GET /v1/me` 只回身分。問卷答案與時區在 `GET /v1/profile`。

---

### 3.2 Profile

| 端點 | 用途 |
|---|---|
| `GET /v1/profile` | 讀 onboarding 問卷答案與時區 |
| `PUT /v1/profile` | 整份覆寫 |

profile 是每次生成計畫都會被讀進去的「常駐 context」：使用者是誰、在哪個時區。
**時區直接決定任務被排在幾點**，所以 onboarding 一定要問到。

```bash
curl -s -X PUT http://127.0.0.1:8000/v1/profile \
  -H "authorization: Bearer $TOKEN" \
  -H 'content-type: application/json' \
  -d '{
        "answers": {
          "occupation": "軟體工程師",
          "weekly_hours": 5,
          "preferred_time": "晚上",
          "constraints": ["週三固定加班"]
        },
        "timezone": "Asia/Taipei"
      }'
```

```json
{
  "user_id": "7c21e4d8-5a3b-4e91-8f22-1d0c9b6a4e33",
  "answers": {
    "occupation": "軟體工程師",
    "weekly_hours": 5,
    "preferred_time": "晚上",
    "constraints": ["週三固定加班"]
  },
  "timezone": "Asia/Taipei",
  "updated_at": "2026-09-05T04:12:33Z"
}
```

三個容易踩的地方：

1. **這是真正的 `PUT`，不是 merge。** `answers` 會整個取代掉舊的物件。要改一個欄位，
   先 `GET /v1/profile`，在客戶端改好，再把整份送回來。**送出時漏掉 `answers` 等於把它清成 `{}`。**
2. **`timezone` 是例外**：不送或送 `null` 代表「維持現狀」（第一次寫入則是 `UTC`）。
   要送就必須是 IANA 時區名——`Asia/Taipei` 可以，`GMT+8` 會被 `422 invalid_input` 擋下來，
   而且驗證發生在寫入之前，所以壞值不會造成半套寫入。
3. **沒有 `404`。** 從沒寫過 profile 的使用者，`GET` 會回 `answers: {}`、`timezone: "UTC"`。
   要判斷「該不該顯示 onboarding」，用登入回應的 `is_new_user`，或看 `answers` 是不是空的。

改了 profile 之後，**已經產生的計畫不會被重寫**，只有之後的生成與修訂會用到新值。

---

### 3.3 匯入資料

匯入是可選的加分項——履歷、訓練紀錄、課表、財務表都可以丟進來當 context。
它有兩條完全不同的路徑。

#### 3.3.1 檔案上傳（三步驟）

```
① POST /v1/imports/presign         宣告檔名／型別／大小 → 拿 import_id + upload_url
                                    （建立 imports 列，status = pending）
        ▼
② PUT  <upload_url>                原始 bytes 直傳，不帶 Authorization
                                    （URL 15 分鐘內有效）
        ▼
③ POST /v1/imports/{import_id}/complete   確認檔案落地 → status = queued，排入 import.parse
        ▼
④ GET  /v1/imports  （輪詢）        status → parsed（成功）或 failed（看 error）
```

為什麼要三步？因為檔案的 bytes **從不經過 API 服務**——presign 只是簽一張限時的通行證，
客戶端直接把檔案 PUT 到儲存空間（本機開發是 `/v1/files/{key}`，正式環境是 R2 bucket）。
這讓大檔上傳不佔用 API 的請求配額，也不需要 API 服務為了轉發而把整個檔案讀進記憶體。

**步驟 ①**

```bash
curl -s -X POST http://127.0.0.1:8000/v1/imports/presign \
  -H "authorization: Bearer $TOKEN" \
  -H 'content-type: application/json' \
  -d '{
        "filename": "training-log-2026.csv",
        "content_type": "text/csv",
        "size_bytes": 48213
      }'
```

```json
{
  "import_id": "b7d4e2c1-9a03-4f56-8e21-3c5d7b0a9e48",
  "upload_url": "http://127.0.0.1:8000/v1/files/imports/7c21e4d8/b7d4e2c1/training-log-2026.csv?exp=1789012345&op=put&sig=9c1e4f...",
  "storage_key": "imports/7c21e4d8-5a3b-4e91-8f22-1d0c9b6a4e33/b7d4e2c1/training-log-2026.csv",
  "expires_in": 900
}
```

限制都在這一步就檢查完，所以被拒絕的檔案根本不會被上傳：

- **上限 20 MB**（`20971520` bytes）。`size_bytes` 在這一步是被信任的，客戶端必須送真實大小。
- 支援格式：`csv`、`xlsx`、`md`、`html`、`pdf`、`docx`、`ics`。判斷順序是**先看副檔名，
  `content_type` 只是後備**。
- `filename` 會被縮成單一路徑片段，`../` 之類的東西是被剝掉而不是被拒絕。
- `upload_url` 只活 **900 秒**（`expires_in`）。過期後 PUT 會拿到 `403 forbidden`，重新 presign 即可。

**步驟 ②**

```bash
curl -s -X PUT \
  "http://127.0.0.1:8000/v1/files/imports/7c21e4d8/b7d4e2c1/training-log-2026.csv?exp=1789012345&op=put&sig=9c1e4f..." \
  -H 'content-type: text/csv' \
  --data-binary @training-log-2026.csv
```

- **URL 原封不動地用**，query string 一個字都不要改；`exp` / `op` / `sig` 是對這個 key、
  這個操作、這個到期時間簽出來的。
- **不要帶 `Authorization` header。**
- 直接 PUT 原始 bytes，不要包 multipart、不要包 JSON。
- `Content-Type` 送 presign 時宣告的那一個。
- `200` 只代表 bytes 存進去了，**import 仍然是 `pending`**。

**步驟 ③**

```bash
curl -s -X POST \
  http://127.0.0.1:8000/v1/imports/b7d4e2c1-9a03-4f56-8e21-3c5d7b0a9e48/complete \
  -H "authorization: Bearer $TOKEN"
```

```json
{
  "id": "b7d4e2c1-9a03-4f56-8e21-3c5d7b0a9e48",
  "source": "upload",
  "format": "csv",
  "filename": "training-log-2026.csv",
  "status": "queued",
  "error": null,
  "created_at": "2026-09-05T04:20:11Z",
  "event_count": 0,
  "chunk_count": 0
}
```

這一步會去儲存空間確認物件真的存在，然後把 import 推進 `queued` 並排入解析工作。
**忘了呼叫它，一個上傳得完美無缺的檔案會永遠卡在 `pending`，永遠不會被解析。**
如果檔案其實沒上傳成功（或 URL 已過期），這裡會回 `422 invalid_input`。

**步驟 ④**

```bash
curl -s http://127.0.0.1:8000/v1/imports -H "authorization: Bearer $TOKEN"
```

```json
[
  {
    "id": "b7d4e2c1-9a03-4f56-8e21-3c5d7b0a9e48",
    "source": "upload",
    "format": "csv",
    "filename": "training-log-2026.csv",
    "status": "parsed",
    "error": null,
    "created_at": "2026-09-05T04:20:11Z",
    "event_count": 12,
    "chunk_count": 34
  }
]
```

**沒有「查單筆 import」的端點**，輪詢就是重打這個清單（最新的在前）。
`parsed` 之後 `event_count`（有時間的項目）與 `chunk_count`（其他文字）才會有值，
它們是「解析器到底抓到多少東西」的可靠訊號。`failed` 時 `error` 會寫原因，
系統**不會自動重試**——修好檔案重新 presign 上傳。

#### 3.3.2 Google Calendar 匯入

```bash
curl -s -X POST http://127.0.0.1:8000/v1/imports/google-calendar \
  -H "authorization: Bearer $TOKEN" \
  -H 'content-type: application/json' \
  -d '{"days": 90}'
```

```json
{
  "id": "3e8a1c95-6f27-4d13-b0a4-8c2e5f9d1a76",
  "source": "google_calendar",
  "format": "ics",
  "filename": "",
  "status": "parsed",
  "error": null,
  "created_at": "2026-09-05T04:31:02Z",
  "event_count": 47,
  "chunk_count": 0
}
```

跟上傳完全相反的三件事：

- **前置條件**：使用者必須已經完成 Google 連線（[3.4](#34-google-連線oauth-兩段式授權)）。
  用 Google 登入**不算**，那是不同的授權範圍。沒連線會拿到 `409 reauth_required`。
- **它是同步的**：事件在這個請求裡就抓回來寫好了，回應中的 import 已經是 `parsed`，
  沒有 presign／complete，也不用輪詢。
- `days` 是**從現在往後**的天數，預設 `90`，最大 `365`（超出範圍 `422`）。過去的事件永遠不會被匯入。

重跑會建立一筆**新的、獨立的** import，不會更新舊的。所以計畫生成時會同時看到新舊兩份，
如果你只想要最新的一份，在 `POST /v1/plan-sessions` 的 `import_ids` 裡只放新的那個 id。

> 注意：這個匯入是「把行程當成 context 資料」。而在建立 plan session 時，
> **只要 Google 是連線狀態，Scheduler 就會自動避開既有行程**，這是另一條路徑，不需要先做匯入，
> 也沒有任何欄位可以控制它。

#### 3.3.3 把匯入餵進計畫

```json
{
  "goal": "12 週內把 5K 跑進 30 分鐘",
  "import_ids": [
    "b7d4e2c1-9a03-4f56-8e21-3c5d7b0a9e48",
    "3e8a1c95-6f27-4d13-b0a4-8c2e5f9d1a76"
  ]
}
```

每個 id 都必須屬於呼叫者、而且**已經是 `parsed`**。還在 `queued` 的 import 會讓整個請求
`422 invalid_input`，而不是被默默忽略——所以 UI 上「選擇要納入的資料」清單應該只列 `parsed` 的項目。

---

### 3.4 Google 連線（OAuth 兩段式授權）

| 端點 | 用途 |
|---|---|
| `GET /v1/integrations` | 查目前的連線狀態 |
| `GET /v1/integrations/{provider}/authorize` | 第一段：拿同意頁 URL |
| `POST /v1/integrations/{provider}/callback` | 第二段：把 code 換成 token 存起來 |
| `DELETE /v1/integrations/{provider}` | 解除連線 |

`provider` 目前只支援 `google`，其他值一律 `422 invalid_input`。

**為什麼要兩次授權？** 登入只需要 `openid email profile`，如果一開始就跟使用者要日曆的讀寫權限，
同意頁會很嚇人、轉換率會掉。所以權限拆成兩段：登入時要最小權限，等使用者真的按下
「連結 Google Calendar」或「匯出到 Calendar」時，才要第二段的 `calendar.readonly`、
`calendar.events`、`spreadsheets`——**一次同意涵蓋日曆匯入、日曆匯出、Sheets 匯出三件事。**

```
GET /v1/integrations/google/authorize        （帶自己的 JWT）
        │  { authorize_url }
        ▼
把使用者導去 authorize_url（redirect 或彈窗）
        │  Google 同意後 redirect 回你的 App，query string 帶 code
        ▼
POST /v1/integrations/google/callback { code }   （帶自己的 JWT）
        │
        ├─ 200 { connected: true, scopes } → 完成
        └─ 422 / 500 → 回到 authorize 重來
```

**第一段**

```bash
curl -s http://127.0.0.1:8000/v1/integrations/google/authorize \
  -H "authorization: Bearer $TOKEN"
```

```json
{
  "authorize_url": "https://accounts.google.com/o/oauth2/v2/auth?client_id=...&redirect_uri=...&response_type=code&scope=https%3A%2F%2Fwww.googleapis.com%2Fauth%2Fcalendar.events...&access_type=offline&prompt=consent&state=8f2c1b6d4e0a"
}
```

URL 原封不動地用。它已經帶了不可猜測的 `state` nonce 與伺服器端設定的 redirect URI，
也已經帶了 `access_type=offline` 與 `prompt=consent`——**這兩個參數是為了逼 Google 回傳 refresh token**，
沒有 refresh token 就無法完成連線。這一段完全不寫入任何資料，使用者中途放棄不留痕跡。

**第二段**

```bash
curl -s -X POST http://127.0.0.1:8000/v1/integrations/google/callback \
  -H "authorization: Bearer $TOKEN" \
  -H 'content-type: application/json' \
  -d '{"code": "4/0AeanS0c..."}'
```

```json
{
  "provider": "google",
  "connected": true,
  "scopes": [
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/spreadsheets"
  ],
  "needs_reauth": false,
  "connected_at": "2026-09-05T04:45:19Z"
}
```

注意這**不是** Google 會呼叫的 URL，而是你自己 App 的一般認證端點：客戶端接住 redirect、
從 query string 撈出 `code`、帶著平常的 Bearer token POST 過來。因為使用者身分是由 JWT 決定的，
`state` 只需要「不可猜測」，不必額外對照。

refresh token 加密後存在後端，**客戶端永遠拿不到 Google 的任何 token**。重複連線是 upsert，
不會產生重複列，所以 `needs_reauth` 之後重新連線是安全的。

**查狀態**

```bash
curl -s http://127.0.0.1:8000/v1/integrations -H "authorization: Bearer $TOKEN"
```

三種情況要一起看 `connected` 與 `needs_reauth`：

| 情況 | 回應 | UI |
|---|---|---|
| 從沒連過 | 陣列裡**根本沒有這一列**（空陣列是正常的） | 顯示「連結 Google」 |
| 連線正常 | `connected: true, needs_reauth: false` | 可以用匯入與匯出 |
| 授權失效／已解除 | `connected: false, needs_reauth: true` | 顯示「重新連結」，走一樣的 authorize → callback |

列**不會被刪掉**就是為了讓 App 能區分「沒連過」與「連過但斷了」，後者可以做更好的提示。

**解除連線**

```bash
curl -s -X DELETE http://127.0.0.1:8000/v1/integrations/google \
  -H "authorization: Bearer $TOKEN" -i
```

`204`，沒有 body。後端會去 Google 撤銷 refresh token、標記該列已撤銷、清掉快取的 access token，
所以下一次 Google 呼叫會乾脆地失敗成 `409 reauth_required`，而不是拿著過期 token 亂打。
呼叫兩次是安全的。**已經匯出到 Google Calendar 的計畫不會被刪掉**——只有未來的匯入與匯出會停擺；
要清掉外部日曆請用 `DELETE /v1/plans/{plan_id}/export/{target}`。

---

### 3.5 產生計畫

| 端點 | 用途 |
|---|---|
| `POST /v1/plan-sessions` | 丟出目標，開始生成（`202`） |
| `GET /v1/plan-sessions/{session_id}` | 唯一要輪詢的東西 |
| `POST /v1/plan-sessions/{session_id}/answers` | 回答一輪追問，續跑（`202`） |
| `GET /v1/jobs/{job_id}` | 佇列的粗略視角，僅供進度提示 |

#### 狀態機與 UI 對照

```mermaid
stateDiagram-v2
  [*] --> collecting : POST /v1/plan-sessions
  collecting --> evaluating : 讀 profile／文件／role model／行事曆，整併 context
  evaluating --> questioning : 資訊不足且 round < 2
  evaluating --> generating : 資訊足夠，或追問輪數用完
  questioning --> evaluating : POST .../answers
  generating --> done : 三份計畫與任務寫入完成
  evaluating --> failed : LLM 重試耗盡
  generating --> failed : LLM 重試耗盡
  done --> [*]
  failed --> [*]
```

| `status` | 哪些欄位有值 | 客戶端該做什麼 |
|---|---|---|
| `collecting` | — | 繼續輪詢，顯示「正在整理你的資料」 |
| `evaluating` | — | 繼續輪詢，顯示「正在判斷還需要問什麼」 |
| `questioning` | `questions[]` | **停止輪詢**，渲染題目，等使用者回答 |
| `generating` | — | 繼續輪詢，顯示「正在產生計畫」——這一段最久 |
| `done` | `plans[]`（三份） | 讓使用者挑一份，`PATCH` 成 `active` |
| `failed` | `error` | 顯示錯誤。**終態，不能續跑**，只能重新建一個 session |

`questions` **只有在 `questioning` 時非空**，`plans` **只有在 `done` 時非空**，`error` 只有 `failed` 時有值。
不要在其他狀態下期待這些欄位有內容。

#### 建立時能帶什麼

```json
{
  "goal": "12 週內把 5K 跑進 30 分鐘",
  "intake": {
    "horizon": "12 週",
    "capacity": "平日晚上兩次，週末一次",
    "baseline": "目前 5K 約 38 分"
  },
  "import_ids": ["b7d4e2c1-9a03-4f56-8e21-3c5d7b0a9e48"],
  "trait_role_model_id": "1a2b3c4d-5e6f-4708-9a0b-1c2d3e4f5a6b",
  "persona_role_model_id": "9f8e7d6c-5b4a-4392-8170-6f5e4d3c2b1a"
}
```

| 欄位 | 必填 | 說明 |
|---|:--:|---|
| `goal` | ✅ | 只有這個必填。空字串或只有空白會 `422` |
| `intake` | | 自由格式物件。**你在這裡補的越多，追問就問得越少** |
| `import_ids` | | 必須屬於呼叫者且已 `parsed`，否則整個請求 `422` |
| `trait_role_model_id` | | 特質類 role model，影響計畫的**結構與節奏上限** |
| `persona_role_model_id` | | 角色卡類 role model，影響計畫的**語氣與方法論** |

Google Calendar **沒有對應欄位**：只要使用者的連線是有效的，Scheduler 就會自動避開既有行程；
沒連線就完全不參考，計畫照排，只會在 `assumptions[]` 裡註明「未參考既有行事曆」。

#### 追問回合

最多 **2 輪**，每輪最多 **5 題**，每題恰好 3 個依 context 客製的選項。
輪數用完仍然資訊不足時，系統會用保守預設值直接生成，並把補了什麼寫進計畫的 `assumptions[]`——
**追問永遠不會無限循環，也不會因為使用者不回答就卡死。**

答案的三選一規則（每題只能給一種）：

```json
{
  "answers": [
    { "question_id": "q1", "choice": "大約 35–40 分鐘" },
    { "question_id": "q2", "custom": "週二週四晚上各 40 分" },
    { "question_id": "q3", "skipped": true }
  ]
}
```

`custom` 只有在該題 `allow_custom` 為 true 時有意義，`skipped` 同理對應 `allow_skip`。
沒答的題目可以整個不放進陣列。

**常見錯誤：`409 conflict`。** 這代表 session 已經不在 `questioning` 了——通常是使用者答太慢，
或是同一份答案送了兩次。處理方式是先 `GET /v1/plan-sessions/{session_id}` 重讀狀態再決定，
不要直接重送。

#### 輪詢策略

生成慢的原因在 [1.5](#15-非同步端點的通則202--輪詢) 說過了：本機 LLM 的一次 `generating`
可能要數十秒到數分鐘。實務建議：

- 間隔 2–3 秒。每秒一次會在一分鐘內耗盡限流配額。
- `questioning` 與 `done` 就停止輪詢，別繼續打。
- 想給更細的進度（「排隊中」vs「正在跑」），可以額外看 `GET /v1/jobs/{job_id}`：

```bash
curl -s http://127.0.0.1:8000/v1/jobs/plan-generate-0b7c9d3e \
  -H "authorization: Bearer $TOKEN"
```

```json
{ "job_id": "plan-generate-0b7c9d3e", "status": "running" }
```

`status` 是 `queued` / `running` / `done` / `failed` / `unknown`。
**`unknown` 不是錯誤**，只是 job 記錄過期了（Redis 只是快取），這個端點也永遠不會回 `404`。
所以：拿它做進度動畫可以，**拿它判斷成敗不行**，成敗看 session。
另外 job 記錄不帶使用者 id，所以這個端點只驗登入、不驗擁有權——把 `job_id` 當成秘密看待。

---

### 3.6 計畫管理

| 端點 | 用途 |
|---|---|
| `GET /v1/plans` | 計畫列表（首頁） |
| `GET /v1/plans/{plan_id}` | 單一計畫的完整詳情、進度、匯出狀態 |
| `PATCH /v1/plans/{plan_id}` | 改名，或改變生命週期狀態 |
| `POST /v1/plans/{plan_id}/archive` | 封存（`PATCH` 成 `archived` 的捷徑） |
| `DELETE /v1/plans/{plan_id}` | 永久刪除 |

#### 生命週期

```mermaid
stateDiagram-v2
  [*] --> draft : 生成完成（一次三份）
  draft --> active : 使用者選定（同 session 其餘退回 draft）
  active --> draft : 改選另一個難度
  active --> archived : 封存
  draft --> archived : 封存
  archived --> active : 還原
  draft --> [*] : 刪除
  active --> [*] : 刪除
  archived --> [*] : 刪除
```

| 從 | 可以到 |
|---|---|
| `draft` | `active`、`archived` |
| `active` | `draft`、`archived` |
| `archived` | `active` |

**任何不在這張表上的移動都是 `409 illegal_transition`，包含把一個計畫設成它現在已經是的狀態。**
`archived` 也不能直接回到 `draft`，只能先回 `active`。
所以「啟用」按鈕在計畫已經是 `active` 時應該是 disabled 的，不要送出去試。

#### 列表

```bash
curl -s "http://127.0.0.1:8000/v1/plans" -H "authorization: Bearer $TOKEN"
curl -s "http://127.0.0.1:8000/v1/plans?status=archived" -H "authorization: Bearer $TOKEN"
```

**不帶 `status` 時，封存的計畫是隱藏的**——預設語意是「我還在做的東西」，
所以會回 `draft` 與 `active`。要看封存區必須明確傳 `status=archived`。
可用值只有 `draft` / `active` / `archived`，其他值 `422`。

列表的每一筆已經帶了 `completion_rate` 與每週負荷，首頁不需要為每個計畫再打一次詳情。
`completion_rate` 的定義是 `done / (done + missed + skipped)`，沒人動過的計畫是 `0.0`。

#### 詳情

```bash
curl -s http://127.0.0.1:8000/v1/plans/8b0e5d31-7c94-4a22-b6f8-05e3a9c17d20 \
  -H "authorization: Bearer $TOKEN"
```

```json
{
  "id": "8b0e5d31-7c94-4a22-b6f8-05e3a9c17d20",
  "session_id": "9f3b2a10-4c2e-4f0e-9b21-6a3d5e7c8f01",
  "title": "5K 破 30 分・標準版",
  "difficulty": "hard",
  "status": "active",
  "goal_statement": "在 12 週內把 5K 完賽時間縮短到 30 分鐘以內",
  "duration_weeks": 12,
  "start_date": "2026-09-08",
  "deadline": "2026-11-30",
  "phases": [
    {
      "index": 0,
      "name": "基礎期",
      "week_start": 1,
      "week_end": 4,
      "focus": "建立每週三次的跑步習慣，先累積里程再談速度",
      "milestone_title": "連續四週完成每週三次跑步",
      "milestone_metric": "週跑量 ≥ 15 公里"
    },
    {
      "index": 1,
      "name": "強化期",
      "week_start": 5,
      "week_end": 9,
      "focus": "加入間歇與節奏跑",
      "milestone_title": "5K 測驗跑進 33 分",
      "milestone_metric": "5K < 33:00"
    }
  ],
  "success_criteria": ["5K 完賽時間 < 30:00", "連續 12 週每週至少 3 次訓練"],
  "assumptions": ["未參考既有行事曆", "假設每次訓練可用時間為 40 分鐘"],
  "progress": {
    "total": 48,
    "done": 9,
    "missed": 2,
    "skipped": 1,
    "pending": 36,
    "completion_rate": 0.75,
    "phase_rates": [
      { "phase_index": 0, "name": "基礎期", "done": 9, "total": 16, "rate": 0.5625 }
    ],
    "checkpoints": [
      {
        "phase_index": 0,
        "title": "連續四週完成每週三次跑步",
        "metric": "週跑量 ≥ 15 公里",
        "due_at": "2026-10-05T00:00:00Z",
        "status": "pending"
      }
    ]
  },
  "exports": [
    {
      "target": "google_calendar",
      "status": "synced",
      "external_calendar_id": "c_9a1f2e3d4b5c6@group.calendar.google.com",
      "last_synced_at": "2026-09-12T03:15:44Z",
      "error": null,
      "pending_changes": 0
    }
  ]
}
```

`assumptions[]` 值得在 UI 上呈現：它是系統為了在資訊不足時仍能產出計畫，所做的每一個假設。
使用者看到「未參考既有行事曆」才會知道去連 Google 可以讓計畫更準。

任務本身**不在這個回應裡**，走 `GET /v1/plans/{plan_id}/tasks`（可切日期區間），
免得一個 12 週的計畫在每次開啟詳情頁時都要傳幾百筆任務。

#### 啟用、改名

```bash
# 選定這一份（同 session 的其他份自動退回 draft）
curl -s -X PATCH http://127.0.0.1:8000/v1/plans/8b0e5d31-7c94-4a22-b6f8-05e3a9c17d20 \
  -H "authorization: Bearer $TOKEN" -H 'content-type: application/json' \
  -d '{"status": "active"}'

# 只改名字
curl -s -X PATCH http://127.0.0.1:8000/v1/plans/8b0e5d31-7c94-4a22-b6f8-05e3a9c17d20 \
  -H "authorization: Bearer $TOKEN" -H 'content-type: application/json' \
  -d '{"title": "破 30 分計畫"}'
```

兩個欄位都可選，都不帶等於什麼都不做。`title` 有帶但是空白會 `422`。
回應是完整的計畫詳情，跟 `GET /v1/plans/{plan_id}` 同形狀。
**改狀態永遠不會動到已匯出的外部日曆。**

#### 封存 vs 刪除

```bash
# 封存：資料全留，只是從預設列表消失
curl -s -X POST http://127.0.0.1:8000/v1/plans/8b0e5d31-7c94-4a22-b6f8-05e3a9c17d20/archive \
  -H "authorization: Bearer $TOKEN"

# 刪除：不可逆
curl -s -X DELETE http://127.0.0.1:8000/v1/plans/8b0e5d31-7c94-4a22-b6f8-05e3a9c17d20 \
  -H "authorization: Bearer $TOKEN" -i
```

| | 封存 | 刪除 |
|---|---|---|
| 計畫資料 | 保留 | 全部移除（任務、check-in、修訂一併） |
| Google Calendar | **原封不動保留** | 專屬日曆整個被刪掉 |
| 可還原 | 可以（`PATCH` 成 `active`） | 不可以 |
| 回應 | `200` + 計畫詳情 | `204`，空 body |

`POST .../archive` 對已經封存的計畫會回 `409 illegal_transition`。

刪除是**永久而且會影響 App 之外的東西**（使用者的 Google Calendar），
UI 上一定要二次確認，並優先推薦封存。刪外部日曆是 best effort——使用者自己先刪掉日曆、
或 Google 授權已過期，都不會阻擋刪除。**只要不是 `204`，就代表什麼都沒被刪掉。**

---

### 3.7 內建 todo 與每日 check-in

| 端點 | 用途 |
|---|---|
| `GET /v1/plans/{plan_id}/tasks` | 內建行事曆／今日清單的資料來源 |
| `PATCH /v1/plans/{plan_id}/tasks/{task_id}` | 單筆勾選、改時間、寫原因 |
| `POST /v1/plans/{plan_id}/checkins` | 一次記錄一整天 |
| `GET /v1/plans/{plan_id}/checkins` | check-in 歷史與每日達成率曲線 |

**完成情況記在 guru-core，不記在 Google Calendar。** 日曆事件過了時間不代表做了，
而且 Google Calendar 沒有可靠的「標記完成」語意。外部日曆只是投影，真相在 `plan_tasks`。

#### 讀任務

```bash
curl -s "http://127.0.0.1:8000/v1/plans/8b0e5d31-7c94-4a22-b6f8-05e3a9c17d20/tasks?from=2026-09-08&to=2026-09-14" \
  -H "authorization: Bearer $TOKEN"
```

- `from` / `to` 是 **ISO `YYYY-MM-DD` 的本地日期**，用的是計畫擁有者 profile 上的時區
  （沒設就是 UTC），而且**兩端都含**。`from=2026-09-08&to=2026-09-14` 就是完整的那一週，
  不管使用者在哪個時區。
- 兩端都可以省略：只給 `from` 是開放結尾，兩個都不給就是整份計畫。
- 格式不是 `YYYY-MM-DD` 會 `422`。

回應的幾個欄位要注意：

| 欄位 | 意思 |
|---|---|
| `task_type` | `session`（訓練／學習）、`habit`（習慣）、`checkpoint`（里程碑）、`rest`（休息） |
| `all_day` | `checkpoint` 與 `rest` 為 true，此時 `start_at` 是當地日 00:00、`end_at` 是隔天 00:00 |
| `start_at` / `end_at` | **UTC 瞬時**，自己轉成使用者時區再顯示 |
| `status` | `pending` / `done` / `missed` / `skipped` |
| `synced` | 這筆的現況有沒有推到外部日曆。任何編輯會讓它變 `false`，下次推送後變回 `true` |
| `template_key` + `week_index` + `occurrence` | 穩定的識別鍵，修訂的 diff 用它對齊新舊任務 |

#### 單筆修改

```bash
# 勾完成
curl -s -X PATCH http://127.0.0.1:8000/v1/plans/8b0e5d31-7c94-4a22-b6f8-05e3a9c17d20/tasks/e91c7a05-8d24-4b6f-9013-7a5c2e8f4b61 \
  -H "authorization: Bearer $TOKEN" -H 'content-type: application/json' \
  -d '{"status": "done"}'

# 拖到別的時間
curl -s -X PATCH http://127.0.0.1:8000/v1/plans/8b0e5d31-7c94-4a22-b6f8-05e3a9c17d20/tasks/e91c7a05-8d24-4b6f-9013-7a5c2e8f4b61 \
  -H "authorization: Bearer $TOKEN" -H 'content-type: application/json' \
  -d '{
        "start_at": "2026-09-09T13:00:00Z",
        "end_at": "2026-09-09T13:40:00Z"
      }'

# 標記錯過並寫原因
curl -s -X PATCH http://127.0.0.1:8000/v1/plans/8b0e5d31-7c94-4a22-b6f8-05e3a9c17d20/tasks/e91c7a05-8d24-4b6f-9013-7a5c2e8f4b61 \
  -H "authorization: Bearer $TOKEN" -H 'content-type: application/json' \
  -d '{"status": "missed", "missed_reason": "臨時加班"}'
```

```json
{
  "id": "e91c7a05-8d24-4b6f-9013-7a5c2e8f4b61",
  "template_key": "easy_run",
  "week_index": 1,
  "phase_index": 0,
  "occurrence": 0,
  "task_type": "session",
  "title": "輕鬆跑 30 分鐘",
  "description": "全程用可以講話的配速，重點是把跑步變成習慣。",
  "start_at": "2026-09-08T12:00:00Z",
  "end_at": "2026-09-08T12:30:00Z",
  "all_day": false,
  "status": "done",
  "completed_at": "2026-09-08T13:02:11Z",
  "missed_reason": null,
  "synced": false
}
```

規則：

- 每個欄位都可選，只有送出的欄位會變。什麼都不送就是原封不動地回傳。
- 改成 `done` 會自動蓋上 `completed_at`；改回 `pending` 會清掉它。
- `start_at` / `end_at` 可以只送一個，但**結果必須讓 `end_at` 嚴格晚於 `start_at`**，
  否則 `422`。只送一個 `start_at` 而它超過了原本的 `end_at`，就是這個錯誤。
- `missed_reason` 是自由文字，之後做 `postpone` / `reduce` 修訂時，它就是系統用來解釋「為什麼要改」的素材。
- **任何成功的修改都會把這筆標成未同步；如果計畫已經匯出到 Google Calendar，
  系統會自動排一次增量推送，你不需要再呼叫任何匯出端點。** 回應是在推送之前寫的，
  所以這裡的 `synced` 一定是 `false`，等 `GET /v1/plans/{plan_id}/export` 回到 `synced` 才算完成。

#### 每日 check-in

一次記錄一整天，比一筆一筆 PATCH 好用得多：

```bash
curl -s -X POST http://127.0.0.1:8000/v1/plans/8b0e5d31-7c94-4a22-b6f8-05e3a9c17d20/checkins \
  -H "authorization: Bearer $TOKEN" -H 'content-type: application/json' \
  -d '{
        "checkin_date": "2026-09-08",
        "results": [
          { "task_id": "e91c7a05-8d24-4b6f-9013-7a5c2e8f4b61", "status": "done" },
          { "task_id": "a3f80b17-2c95-4e61-8d04-b7e2f5a91c38", "status": "missed", "reason": "臨時加班" }
        ],
        "note": "腿有點緊，明天先做伸展"
      }'
```

```json
{
  "id": "5c1d9e73-8a26-4f30-b915-4e7d2c0a6b83",
  "checkin_date": "2026-09-08",
  "results": [
    { "task_id": "e91c7a05-8d24-4b6f-9013-7a5c2e8f4b61", "status": "done", "reason": null },
    { "task_id": "a3f80b17-2c95-4e61-8d04-b7e2f5a91c38", "status": "missed", "reason": "臨時加班" }
  ],
  "note": "腿有點緊，明天先做伸展",
  "created_at": "2026-09-08T14:03:52Z"
}
```

- **一個計畫一天只有一筆 check-in。** 同一個 `checkin_date` 再送一次是**整份取代**，
  不是追加——所以使用者修改當天記錄時，要把整天的結果重送一次。
- `status` 只能是 `done` / `missed` / `skipped`，**`pending` 不是 check-in 的結果**，送了會 `422`。
- `results[].task_id` 必須屬於這個計畫，否則 `422`。
- `results` 可以是空陣列，那就是一筆「只有心得、沒動到任何任務」的記錄。
- check-in 會**直接寫穿到任務**（`status`、`completed_at`、`missed_reason`），所以
  `GET /v1/plans/{plan_id}` 的進度數字會立刻跟著動；已匯出的計畫也會自動排增量推送。

#### 進度曲線

```bash
curl -s http://127.0.0.1:8000/v1/plans/8b0e5d31-7c94-4a22-b6f8-05e3a9c17d20/checkins \
  -H "authorization: Bearer $TOKEN"
```

```json
{
  "items": [
    {
      "id": "5c1d9e73-8a26-4f30-b915-4e7d2c0a6b83",
      "checkin_date": "2026-09-08",
      "results": [
        { "task_id": "e91c7a05-8d24-4b6f-9013-7a5c2e8f4b61", "status": "done", "reason": null }
      ],
      "note": "腿有點緊，明天先做伸展",
      "created_at": "2026-09-08T14:03:52Z"
    }
  ],
  "daily_rates": [
    { "date": "2026-09-08", "done": 1, "total": 2, "rate": 0.5 }
  ]
}
```

`daily_rates` 是**「使用者回報了什麼」的曲線，不是計畫整體的達成率**：分母是那天 check-in 涵蓋的任務數，
沒有 check-in 的日子在曲線上根本沒有點，只有心得的 check-in 是 `0` 分之 `0`、`rate: 0.0`。
要畫「整體完成度」「各階段完成度」「里程碑狀態」請讀 `GET /v1/plans/{plan_id}` 的 `progress`。

---

### 3.8 修訂（重新排程）

| 端點 | 用途 |
|---|---|
| `POST /v1/plans/{plan_id}/revisions` | 發起修訂（`202`） |
| `GET /v1/plans/{plan_id}/revisions/{revision_id}` | 輪詢並取得 diff |
| `GET /v1/plans/{plan_id}/revisions` | 修訂歷史 |
| `POST /v1/plans/{plan_id}/revisions/{revision_id}/accept` | 套用 |
| `POST /v1/plans/{plan_id}/revisions/{revision_id}/reject` | 拒絕 |

觸發只有一種：**使用者手動按「重新排程」**，通常發生在連續標了幾個 missed 之後。

```
POST /v1/plans/{id}/revisions {strategy, note?}     → 202 {revision_id, job_id}
        │  status = pending
        ▼
GET /v1/plans/{id}/revisions/{rev_id}  （輪詢）
        │
        ├─ pending   → 繼續等
        ├─ proposed  → 渲染 diff + rationale，讓使用者決定
        └─ failed    → 顯示錯誤，重新發起
        ▼
POST .../accept   → 今天之後的任務被取代，計畫欄位一起更新
   或 .../reject   → 什麼都不動，可以立刻改用另一種策略再試
```

#### 兩種策略

| `strategy` | 做法 | 適合誰 | 不會動什麼 |
|---|---|---|---|
| `postpone` | 保持目標與每週強度，**把截止日往後推** | 目標不能降、時間有彈性 | 不改任務內容與密度 |
| `reduce` | 保持截止日，**把目標量縮到剩餘時間做得到的程度** | 截止日固定（考試、比賽） | 不動截止日 |

```bash
curl -s -X POST http://127.0.0.1:8000/v1/plans/8b0e5d31-7c94-4a22-b6f8-05e3a9c17d20/revisions \
  -H "authorization: Bearer $TOKEN" -H 'content-type: application/json' \
  -d '{
        "strategy": "postpone",
        "note": "這兩週出差，幾乎都沒跑到"
      }'
```

```json
{
  "revision_id": "d2b73f18-4a90-4c67-8e15-3f0a7c9d2e64",
  "job_id": "plan-revise-7e4c1a90"
}
```

**前置條件與常見錯誤：**

- 計畫必須是 `active`——`draft` 或 `archived` 會拿到 `409 conflict`。
- **一個計畫同時只能有一個未決的修訂**（`pending` 或 `proposed`）。還沒 accept / reject 就再發一次是
  `409 conflict`；用 `GET /v1/plans/{plan_id}/revisions` 找出卡住的那一筆先處理掉。
- `strategy` 只能是 `postpone` 或 `reduce`，其他值 `422`。

#### 讀 diff

```bash
curl -s http://127.0.0.1:8000/v1/plans/8b0e5d31-7c94-4a22-b6f8-05e3a9c17d20/revisions/d2b73f18-4a90-4c67-8e15-3f0a7c9d2e64 \
  -H "authorization: Bearer $TOKEN"
```

```json
{
  "id": "d2b73f18-4a90-4c67-8e15-3f0a7c9d2e64",
  "plan_id": "8b0e5d31-7c94-4a22-b6f8-05e3a9c17d20",
  "strategy": "postpone",
  "status": "proposed",
  "rationale": "過去兩週有 5 次訓練未完成。維持每週 4 次的強度不變，把剩下的 7 週往後延 2 週，截止日改為 12/14。",
  "diff": [
    {
      "template_key": "easy_run",
      "week_index": 6,
      "occurrence": 0,
      "kind": "moved",
      "title": "輕鬆跑 40 分鐘",
      "before": { "start_at": "2026-10-13T12:00:00Z", "end_at": "2026-10-13T12:40:00Z" },
      "after":  { "start_at": "2026-10-27T12:00:00Z", "end_at": "2026-10-27T12:40:00Z" }
    },
    {
      "template_key": "interval",
      "week_index": 7,
      "occurrence": 1,
      "kind": "removed",
      "title": "間歇 6×400m",
      "before": { "start_at": "2026-10-22T12:00:00Z", "end_at": "2026-10-22T13:00:00Z" },
      "after": null
    }
  ],
  "summary": {
    "added": 0,
    "moved": 14,
    "removed": 1,
    "shortened": 0,
    "lengthened": 0,
    "unchanged": 19
  },
  "created_at": "2026-09-22T02:11:07Z",
  "decided_at": null
}
```

- 還在 `pending` 時，`diff` 是空的，`rationale` 裡放的還是**使用者自己填的 `note`**；
  等 `proposed` 之後才會被系統的說明取代。
- `kind` 可能是 `added` / `moved` / `removed` / `shortened` / `lengthened` / `reduced` / `unchanged`。
  `reduced` 是 `reduce` 策略下「目標量被縮小」的標記。
- `summary` 可以直接拿來做一行標題：「移動 14 筆、刪除 1 筆」。
- diff 用 `template_key + week_index + occurrence` 對齊新舊任務，**不是比對標題**——
  標題會被改寫，這組鍵不會。所以前端可以直接渲染，不需要自己算差異。
- **`proposed` 只是預覽。在 accept 之前，計畫的任務完全沒有變。**

#### 接受或拒絕

```bash
curl -s -X POST http://127.0.0.1:8000/v1/plans/8b0e5d31-7c94-4a22-b6f8-05e3a9c17d20/revisions/d2b73f18-4a90-4c67-8e15-3f0a7c9d2e64/accept \
  -H "authorization: Bearer $TOKEN"
```

接受之後：

- **只有今天以後的任務會被取代**，已經過去的日子連同勾選記錄原封不動保留。
- 計畫本身的 `deadline`、`duration_weeks`、`goal_statement` 與結構也會跟著提案改。
- 所以**接受後請重新讀 `GET /v1/plans/{plan_id}` 與 `GET /v1/plans/{plan_id}/tasks`**，
  不要在客戶端自己 patch 舊資料。
- 已匯出到 Google Calendar 的計畫會自動排一次增量推送，看 `GET /v1/plans/{plan_id}/export`。

```bash
curl -s -X POST http://127.0.0.1:8000/v1/plans/8b0e5d31-7c94-4a22-b6f8-05e3a9c17d20/revisions/d2b73f18-4a90-4c67-8e15-3f0a7c9d2e64/reject \
  -H "authorization: Bearer $TOKEN"
```

拒絕之後計畫、任務、匯出全部維持原狀，這筆修訂以 `rejected` 留在歷史裡，
而且計畫立刻恢復成「可以再發起修訂」的狀態——使用者可以馬上改用另一種策略再試一次。

兩個端點都只能用在 `status` 為 `proposed` 的修訂上。還在算、已經失敗、或已經決定過的修訂，
一律 `409 conflict`——**決定是最終的，沒有反悔**。

修訂歷史用 `GET /v1/plans/{plan_id}/revisions`（最舊的在前，每筆都帶完整 diff），
它同時也是「到底是哪一筆卡住了新的修訂」的查法。

---

### 3.9 匯出

| 端點 | 用途 |
|---|---|
| `POST /v1/plans/{plan_id}/export` | 發起匯出（Markdown 同步、其餘非同步） |
| `GET /v1/plans/{plan_id}/export` | 查每個 target 的狀態 |
| `DELETE /v1/plans/{plan_id}/export/{target}` | 解除匯出並刪掉外部日曆 |

**前置條件（兩個都要滿足，否則 `409`）：**

1. 計畫必須是 **`active`**。`draft` 或 `archived` 會拿到 `409 conflict`，
   先用 `PATCH /v1/plans/{plan_id}` 設成 `active`。
2. Google 類的 target 需要**有效的 Google 連線**，在排入佇列之前就會檢查，
   沒連線直接 `409 reauth_required`，導去 [3.4](#34-google-連線oauth-兩段式授權)。

同一個端點有兩種完全不同的行為，取決於 `target`：

```
target = "markdown"                    target = google_calendar / google_sheets / notion
  │ 在這個請求裡渲染完成                  │ 檢查 active + Google 連線 → 排入佇列
  ▼                                      ▼
200 { markdown: { content,             200 { job_id, mode: "full" | "incremental" }
      download_url, storage_key } }      │
  │ 沒有 job_id、不用輪詢                 ▼
  ▼                                    GET /v1/plans/{id}/export （輪詢）
直接顯示或下載                            queued → synced ／ failed（看 error）
```

#### Markdown（同步）

```bash
curl -s -X POST http://127.0.0.1:8000/v1/plans/8b0e5d31-7c94-4a22-b6f8-05e3a9c17d20/export \
  -H "authorization: Bearer $TOKEN" -H 'content-type: application/json' \
  -d '{
        "target": "markdown",
        "options": {
          "include_completed": false,
          "from": "2026-09-08",
          "to": "2026-10-31"
        }
      }'
```

```json
{
  "target": "markdown",
  "mode": null,
  "job_id": null,
  "markdown": {
    "content": "# 5K 破 30 分・標準版\n\n## 達成標準\n- 5K 完賽時間 < 30:00\n\n## 週計畫\n### 第 1 週（09/08 – 09/14）　基礎期\n...",
    "download_url": "http://127.0.0.1:8000/v1/files/exports/7c21e4d8/8b0e5d31.md?exp=1789012345&op=get&sig=6f2a...",
    "storage_key": "exports/7c21e4d8-5a3b-4e91-8f22-1d0c9b6a4e33/8b0e5d31.md"
  }
}
```

- `options` 可用的三個鍵：`include_completed`（布林，預設 `true`）、`from`、`to`（ISO 日期）。
  型別不對會 `422`。
- `content` 就是完整文件，可以直接渲染或複製。
- `download_url` 是 presigned 連結，**約 15 分鐘後失效**。要下載就當下下載，
  **不要存進資料庫或當成永久連結給使用者**。打它時不要帶 `Authorization`。
- Markdown 匯出**不會出現在 `GET /v1/plans/{plan_id}/export` 的列表裡**，因為它不留狀態。

#### Google Calendar（非同步）

```bash
curl -s -X POST http://127.0.0.1:8000/v1/plans/8b0e5d31-7c94-4a22-b6f8-05e3a9c17d20/export \
  -H "authorization: Bearer $TOKEN" -H 'content-type: application/json' \
  -d '{"target": "google_calendar"}'
```

```json
{
  "target": "google_calendar",
  "mode": "full",
  "job_id": "export-push-2f8b6c04",
  "markdown": null
}
```

`mode` 說明這次要做什麼：

- **`full`**：第一次匯出。系統會為這份計畫建立一個**專屬的 secondary calendar**
  （名稱像 `guru · 5K 破 30 分・標準版`），把所有任務寫成事件。
  用獨立日曆的好處是：使用者想暫時眼不見為淨，關掉那個日曆就好，不會污染主日曆。
- **`incremental`**：這份計畫已經有自己的日曆了，只推送有變動的任務。

輪詢：

```bash
curl -s http://127.0.0.1:8000/v1/plans/8b0e5d31-7c94-4a22-b6f8-05e3a9c17d20/export \
  -H "authorization: Bearer $TOKEN"
```

```json
[
  {
    "target": "google_calendar",
    "status": "synced",
    "external_calendar_id": "c_9a1f2e3d4b5c6@group.calendar.google.com",
    "last_synced_at": "2026-09-12T03:15:44Z",
    "error": null,
    "pending_changes": 0
  }
]
```

| 欄位 | 意思 |
|---|---|
| `status` | `queued`（排隊或執行中）、`synced`（完成）、`failed`（`error` 有原因） |
| `error` | 失敗原因。值為 `reauth_required` 代表推送途中 Google 授權失效，要重新連線 |
| `external_calendar_id` | 事件所在的日曆 |
| `pending_changes` | 還沒推上去的任務編輯筆數 |

空陣列代表這份計畫從沒匯出過。

#### 增量同步是自動的

**這是最容易誤解的地方：勾完成、改時間、送 check-in、接受修訂之後，
你不需要再呼叫一次 `POST .../export`。** 只要這份計畫已經匯出到 Google Calendar，
系統會自己排增量推送。你要做的只是在 UI 上呈現狀態：任務的 `synced` 為 `false`、
或匯出列的 `pending_changes > 0`，就顯示「同步中」，等 `status` 回到 `synced` 再收起提示。

**同步是單向的：guru-core → Google Calendar。** 使用者直接在 Google Calendar 上把 guru 的事件拖到別的時間，
guru-core 不會知道，而且下一次增量推送會把它改回計畫的時間。
UI 上應該在匯出設定旁邊寫清楚這件事，並引導使用者用 App 內的「改時間」。

#### 解除匯出

```bash
curl -s -X DELETE http://127.0.0.1:8000/v1/plans/8b0e5d31-7c94-4a22-b6f8-05e3a9c17d20/export/google_calendar \
  -H "authorization: Bearer $TOKEN" -i
```

`204`，空 body。**整個 secondary calendar 會被刪掉**（不是一個一個刪事件），
每筆任務會忘掉自己的外部參照，匯出列也會消失——所以下一次匯出會重新是一次 `full`。

刪除遠端日曆是 best effort：使用者早就自己刪了那個日曆，或 Google 授權已過期，
本地狀態一樣會被清乾淨。這是刻意的設計，**一個計畫永遠不會卡在「已匯出但解不掉」的狀態**。

`target` 用 `GET /v1/plans/{plan_id}/export` 回的值（實務上就是 `google_calendar`）。
從沒推送過、或已經解除過的 target 會回 `404 not_found`。

> 封存計畫**不會**動到外部日曆，事件會一直留著。要清掉只有兩條路：解除匯出，或刪除計畫。

---

### 3.10 Role model

Role model 是團隊策展的共享資料庫，計畫生成時會拿來當範本：

- **特質類（`trait`）**——影響計畫怎麼被組織起來（每週幾次的上限、最少休息日這類節奏約束）。
  由使用者自己挑，**不進推薦**。
- **角色卡類（`persona`）**——影響計畫的口吻與方法論。這是推薦端點會回的東西。

| 端點 | 認證 | 用途 |
|---|---|---|
| `GET /v1/role-models` | JWT | 瀏覽目錄，可依 `kind` 與 `tags` 過濾 |
| `GET /v1/role-models/tags` | JWT | 取得可用的 tag 詞彙 |
| `GET /v1/role-models/recommend` | JWT | 依使用者目標與 profile 推薦 persona |
| `GET /v1/role-models/{id}` | JWT | 單一 role model 的完整內容 |
| `POST /v1/role-models` | **`X-API-Key`** | 團隊建立 |
| `PUT /v1/role-models/{id}` | **`X-API-Key`** | 團隊整份取代 |
| `DELETE /v1/role-models/{id}` | **`X-API-Key`** | 團隊停用 |

這些端點由 API Service **原樣代理**給 Role Model Service，所以 `200` 的 body 是那個服務的格式，
不在本 API 的 schema 契約內（OpenAPI 上標成 `any`）——**渲染時請防禦性處理**。
錯誤信封兩邊是一樣的。

#### 瀏覽與過濾

```bash
curl -s "http://127.0.0.1:8000/v1/role-models?kind=persona&tags=domain:fitness&tags=goal:endurance&match=all&limit=20" \
  -H "authorization: Bearer $TOKEN"
```

```json
[
  {
    "id": "9f8e7d6c-5b4a-4392-8170-6f5e4d3c2b1a",
    "kind": "persona",
    "name": "馬拉松教練型",
    "tags": ["domain:fitness", "goal:endurance", "level:beginner"]
  }
]
```

- `tags` 是**可重複的 query 參數**：`?tags=a&tags=b`。
- `match=any`（預設語意）是「帶其中一個就算」，`match=all` 是「每個都要有」。
  其他值 `422`。
- `limit` 範圍 1–200，預設 50，超出 `422`。

Tag 詞彙不要寫死在 App 裡——目錄是團隊維護的，tag 會在不發版的情況下改變：

```bash
curl -s http://127.0.0.1:8000/v1/role-models/tags -H "authorization: Bearer $TOKEN"
```

回傳的是以 `kind` 為鍵、值為該類目前在用的 tag 清單的物件。

#### 推薦

在使用者剛打完目標、還沒送出 `POST /v1/plan-sessions` 之前呼叫：

```bash
curl -s "http://127.0.0.1:8000/v1/role-models/recommend?goal=12%20週內把%205K%20跑進%2030%20分鐘&domains=fitness" \
  -H "authorization: Bearer $TOKEN"
```

```json
[
  {
    "role_model_id": "9f8e7d6c-5b4a-4392-8170-6f5e4d3c2b1a",
    "name": "馬拉松教練型",
    "reason": "同樣以耐力目標為主，強調循序漸進與週跑量控制，適合從 38 分推進到 30 分的節奏。"
  }
]
```

- `goal` 是 query 參數（預設空字串）；`domains` 與 `excluded_constraints` 是可重複的 query 參數，
  用來收窄或否決候選。
- 後端會自動把使用者存在 profile 的問卷答案加進去，所以推薦是**個人化的**——這也是它要 JWT 的原因。
- **不會寫入任何東西**，只是建議。使用者選了之後，把 `role_model_id` 放進
  `POST /v1/plan-sessions` 的 `persona_role_model_id`（或 `trait_role_model_id`）。
- 錯誤處理上寬鬆一點：`404` 請當成「這次沒有推薦」而不是壞畫面；
  `500 domain_error` 代表上游服務不通，畫面可以退回 `GET /v1/role-models` 的一般瀏覽。

#### 詳情

```bash
curl -s http://127.0.0.1:8000/v1/role-models/9f8e7d6c-5b4a-4392-8170-6f5e4d3c2b1a \
  -H "authorization: Bearer $TOKEN"
```

回完整記錄，包含 `content`——那是計畫生成器實際會讀的策展文件。
**`content` 的形狀屬於 Role Model Service，不是本 API 的契約**，App 端不要對它的結構做強假設。

#### 團隊寫入（App 不該碰）

```bash
curl -s -X POST http://127.0.0.1:8000/v1/role-models \
  -H "X-API-Key: $ROLE_MODEL_API_KEY" \
  -H 'content-type: application/json' \
  -d '{
        "kind": "persona",
        "name": "馬拉松教練型",
        "tags": ["domain:fitness", "goal:endurance"],
        "content": { "summary": "...", "sections": [] }
      }'
```

- **不帶 JWT，只帶 `X-API-Key`**，header 錯或缺是 `401 unauthorized`。
  這是團隊憑證，一般使用者的 token 打不進來。
- `kind` 與非空的 `name` 必填，否則 `422`。
- `PUT` 是**整份取代**，沒送的欄位會被清空——送完整記錄。
  已經產生的計畫會保留當時用的文字，編輯只影響之後的生成。
- `DELETE` 是**停用而非抹除**：它會從 `GET /v1/role-models` 消失，但引用過它的計畫與 session 完好無損。

---

## 4. 端點速查表

全部 43 個端點。「認證」欄：**JWT** = `Authorization: Bearer <jwt>`；
**API Key** = `X-API-Key`；**簽章** = 授權寫在 URL 的 query 參數裡，不要帶任何 header；
**無** = 完全公開。

### ops

| 方法 | 路徑 | 用途 | 認證 |
|---|---|---|:--:|
| GET | `/health` | 存活探針，免限流 | 無 |

### auth

| 方法 | 路徑 | 用途 | 認證 |
|---|---|---|:--:|
| POST | `/v1/auth/google` | 用 Google code 換 guru-core 的 JWT | 無 |
| GET | `/v1/me` | 確認 token 有效並取得使用者身分 | JWT |

### profile

| 方法 | 路徑 | 用途 | 認證 |
|---|---|---|:--:|
| GET | `/v1/profile` | 讀問卷答案與時區 | JWT |
| PUT | `/v1/profile` | 整份覆寫問卷答案與時區 | JWT |

### imports

| 方法 | 路徑 | 用途 | 認證 |
|---|---|---|:--:|
| POST | `/v1/imports/presign` | 上傳第 1 步：宣告檔案，取得 `upload_url` | JWT |
| POST | `/v1/imports/{import_id}/complete` | 上傳第 3 步：確認落地，排入解析 | JWT |
| GET | `/v1/imports` | 匯入清單與狀態（輪詢用） | JWT |
| POST | `/v1/imports/google-calendar` | 同步拉取未來的 Google Calendar 行程 | JWT |

### files（presigned）

| 方法 | 路徑 | 用途 | 認證 |
|---|---|---|:--:|
| PUT | `/v1/files/{key}` | 上傳第 2 步：把原始 bytes PUT 到 `upload_url` | 簽章 |
| GET | `/v1/files/{key}` | 從 presigned 連結下載物件 | 簽章 |

### integrations

| 方法 | 路徑 | 用途 | 認證 |
|---|---|---|:--:|
| GET | `/v1/integrations` | 查各 provider 的連線狀態 | JWT |
| GET | `/v1/integrations/{provider}/authorize` | OAuth 第 1 段：取得同意頁 URL | JWT |
| POST | `/v1/integrations/{provider}/callback` | OAuth 第 2 段：用 code 換 token 存起來 | JWT |
| DELETE | `/v1/integrations/{provider}` | 解除連線並向上游撤銷 | JWT |

### plan-sessions

| 方法 | 路徑 | 用途 | 認證 |
|---|---|---|:--:|
| POST | `/v1/plan-sessions` | 從目標開始生成計畫（`202`） | JWT |
| GET | `/v1/plan-sessions/{session_id}` | 輪詢狀態、追問題目或三份計畫 | JWT |
| POST | `/v1/plan-sessions/{session_id}/answers` | 回答一輪追問並續跑（`202`） | JWT |

### plans

| 方法 | 路徑 | 用途 | 認證 |
|---|---|---|:--:|
| GET | `/v1/plans` | 計畫列表，`status` 可過濾（預設隱藏封存） | JWT |
| GET | `/v1/plans/{plan_id}` | 計畫詳情、階段、進度、匯出狀態 | JWT |
| PATCH | `/v1/plans/{plan_id}` | 改名，或改變 `draft`/`active`/`archived` | JWT |
| DELETE | `/v1/plans/{plan_id}` | 永久刪除計畫與外部日曆 | JWT |
| POST | `/v1/plans/{plan_id}/archive` | 封存 | JWT |
| GET | `/v1/plans/{plan_id}/tasks` | 依日期區間列出排定的任務 | JWT |
| PATCH | `/v1/plans/{plan_id}/tasks/{task_id}` | 勾選、改時間、寫 missed 原因 | JWT |
| POST | `/v1/plans/{plan_id}/checkins` | 送出一天的 check-in | JWT |
| GET | `/v1/plans/{plan_id}/checkins` | check-in 歷史與每日達成率曲線 | JWT |
| POST | `/v1/plans/{plan_id}/export` | 匯出（markdown 同步、其餘 `202` 式排隊） | JWT |
| GET | `/v1/plans/{plan_id}/export` | 各 target 的匯出狀態（輪詢用） | JWT |
| DELETE | `/v1/plans/{plan_id}/export/{target}` | 解除匯出並刪除外部日曆 | JWT |
| POST | `/v1/plans/{plan_id}/revisions` | 發起修訂提案（`202`） | JWT |
| GET | `/v1/plans/{plan_id}/revisions` | 修訂歷史 | JWT |
| GET | `/v1/plans/{plan_id}/revisions/{revision_id}` | 單筆修訂與其 diff（輪詢用） | JWT |
| POST | `/v1/plans/{plan_id}/revisions/{revision_id}/accept` | 接受提案，重寫今天之後的排程 | JWT |
| POST | `/v1/plans/{plan_id}/revisions/{revision_id}/reject` | 拒絕提案，計畫維持原狀 | JWT |

### jobs

| 方法 | 路徑 | 用途 | 認證 |
|---|---|---|:--:|
| GET | `/v1/jobs/{job_id}` | 佇列工作的粗略狀態（僅供進度提示） | JWT |

### role-models

| 方法 | 路徑 | 用途 | 認證 |
|---|---|---|:--:|
| GET | `/v1/role-models` | 瀏覽目錄，可依 `kind` / `tags` 過濾 | JWT |
| POST | `/v1/role-models` | 建立 role model（團隊工具） | API Key |
| GET | `/v1/role-models/tags` | 可用的 tag 詞彙 | JWT |
| GET | `/v1/role-models/recommend` | 依目標與 profile 推薦 persona | JWT |
| GET | `/v1/role-models/{role_model_id}` | 單一 role model 完整內容 | JWT |
| PUT | `/v1/role-models/{role_model_id}` | 整份取代（團隊工具） | API Key |
| DELETE | `/v1/role-models/{role_model_id}` | 停用（團隊工具） | API Key |

---

## 5. 狀態機附錄

五張表各有自己的狀態欄位，客戶端幾乎所有的 UI 分支都掛在它們上面。
欄位層級的細節見 [`docs/db/schema.md`](../db/schema.md)。

### 5.1 `plan_sessions.status` — 計畫生成

```mermaid
stateDiagram-v2
  [*] --> collecting : POST /v1/plan-sessions
  collecting --> evaluating : 整併 context 完成
  evaluating --> questioning : 資訊不足且 round < 2
  evaluating --> generating : 資訊足夠，或追問輪數用完
  questioning --> evaluating : POST .../answers
  generating --> done : 三份計畫與任務寫入完成
  evaluating --> failed : LLM 重試耗盡
  generating --> failed : LLM 重試耗盡
  done --> [*]
  failed --> [*]
```

終態：`done`、`failed`。`failed` 無法續跑，只能新建 session。
唯一由客戶端觸發的轉移是 `questioning → evaluating`（送答案）；在其他狀態送答案會 `409 conflict`。

### 5.2 `plans.status` — 計畫生命週期

```mermaid
stateDiagram-v2
  [*] --> draft : 一次生成三份
  draft --> active : PATCH {"status":"active"}
  active --> draft : PATCH {"status":"draft"}
  draft --> archived : POST /archive 或 PATCH
  active --> archived : POST /archive 或 PATCH
  archived --> active : PATCH {"status":"active"}
  draft --> [*] : DELETE
  active --> [*] : DELETE
  archived --> [*] : DELETE
```

**`archived` 不能直接回 `draft`**，而且把計畫設成它已經是的狀態也是 `409 illegal_transition`。
把一份設成 `active` 會讓同 session 的其他份自動退回 `draft`。

### 5.3 `plan_revisions.status` — 修訂

```mermaid
stateDiagram-v2
  [*] --> pending : POST /v1/plans/{id}/revisions
  pending --> proposed : 提案計算完成，diff 與 rationale 就緒
  pending --> failed : LLM 重試耗盡
  proposed --> accepted : POST .../accept（重寫今天之後的任務）
  proposed --> rejected : POST .../reject（計畫不變）
  accepted --> [*]
  rejected --> [*]
  failed --> [*]
```

`pending` 與 `proposed` 都算「未決」，**一個計畫同時只能有一筆未決的修訂**。
`accept` / `reject` 只在 `proposed` 時可用，決定之後不可逆。

### 5.4 `imports.status` — 匯入

```mermaid
stateDiagram-v2
  [*] --> pending : POST /v1/imports/presign
  pending --> queued : POST /v1/imports/{import_id}/complete
  queued --> parsed : 解析成功
  queued --> failed : 解析失敗，原因寫在 error
  [*] --> parsed : POST /v1/imports/google-calendar（同步寫入）
  parsed --> [*]
  failed --> [*]
```

`pending` 是「presign 了但檔案還沒確認上傳」。**沒有呼叫 `complete` 的 import 會永遠停在 `pending`**，
不會被解析，但放著也無害。Google Calendar 匯入不經過 `pending` / `queued`，直接就是 `parsed`。
`failed` 不會自動重試。

### 5.5 `plan_exports.status` — 匯出

```mermaid
stateDiagram-v2
  [*] --> queued : POST /v1/plans/{id}/export（非 markdown 的 target）
  queued --> synced : 推送完成
  queued --> failed : 推送失敗，原因寫在 error
  synced --> queued : 任務被編輯／check-in／接受修訂（自動排增量推送）
  failed --> queued : 重新呼叫 POST /v1/plans/{id}/export
  synced --> [*] : DELETE /v1/plans/{id}/export/{target}
  failed --> [*] : DELETE /v1/plans/{id}/export/{target}
```

`markdown` 是同步渲染的，**永遠不會出現在這張表上**。
`error` 的值若是 `reauth_required`，代表推送途中 Google 授權失效，需要重新連線後再匯出。

### 5.6 `plan_tasks.status` — 任務

沒有轉移限制，四個值之間可以自由移動：

| 值 | 意思 | 怎麼設 |
|---|---|---|
| `pending` | 還沒處理（預設） | `PATCH .../tasks/{id}`。設回 `pending` 會清掉 `completed_at` |
| `done` | 完成 | `PATCH` 或 check-in。會自動蓋 `completed_at` |
| `missed` | 錯過 | `PATCH`（可帶 `missed_reason`）或 check-in（`reason`） |
| `skipped` | 主動略過 | `PATCH` 或 check-in |

check-in 只接受 `done` / `missed` / `skipped`，**不接受 `pending`**。
任何狀態改變都會讓 `synced` 變成 `false`，並在已匯出時自動觸發增量推送。
