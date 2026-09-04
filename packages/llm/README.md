# packages/llm

## 負責什麼

把「呼叫大型語言模型」收斂成一個介面：呼叫端只給 prompt 名稱、context dict、輸出的 Pydantic schema 與用途（`Purpose`），拿回一個已驗證的 model 實例。目前這個 package 提供三件事：

- **設定**：`config/llm.yaml` 的 Pydantic model（`LLMConfig`）與載入函式 `load_llm_config()`。設定裡是**一份 provider**，不是 provider 清單；換模型或換服務只改環境變數（`LLM_ADAPTER`、`LLM_BASE_URL`、`LLM_MODEL`、`LLM_API_KEY`、`LLM_MAX_CONTEXT`）。每種用途的 `temperature` / `max_output_tokens` 與 role model context 預算（`budgets`）也在同一份設定，用 `params_for(purpose)` 與 `budget_for(purpose)` 取用。
- **Prompt registry**：`PromptRegistry(directory)` 從目錄讀 `.md` 模板。模板格式是 YAML frontmatter（至少要有 `version`）後接 `# SYSTEM` 與 `# USER` 兩段，兩段各自以 jinja2（`StrictUndefined`）渲染 context，回傳 `RenderedPrompt`。`version(name)` 可單獨取模板版本，供觀測與快取 key 使用。
- **`FakeLLM`**：開發與測試預設使用的實作。依 `fixtures_dir/{prompt_name}.json` 回傳固定回應，`overrides[prompt_name]` 優先；找不到就 `LLMError("no fixture for ...")`。所有呼叫記在 `calls: list[tuple[prompt_name, Purpose, context]]`，測試可直接斷言。

## 對外 port 有哪些

`packages.llm.__all__` 明列的介面：

- `LLMPort`（Protocol）：`async complete(prompt_name, context, output_schema, purpose) -> OutputT`
- `Purpose`（StrEnum）：`evaluate` / `generate` / `revise` / `recommend`
- 錯誤型別：`LLMError`（基底）、`LLMSchemaError`（回應無法通過 Pydantic 驗證）、`LLMTransportError`（網路 / HTTP 層）
- 設定：`LLMConfig`、`ProviderConfig`、`PurposeParams`、`RetryConfig`、`load_llm_config`
- Prompt：`PromptRegistry`、`RenderedPrompt`
- 實作：`FakeLLM`

其餘模組（`ports.py`、`config.py`、`prompts.py`、`fake.py`）視為 private，請一律 `from packages.llm import ...`。

## 不負責什麼

- 不負責真正的 provider 呼叫。`OpenAICompatLLM`、`AnthropicLLM` 與工廠函式 `build_llm` 是後續 task。
- 不負責「驗證 → 錯誤回灌重試 → 降級預設」這條可靠性鏈與觀測記錄（PRD 7.5 / 7.8），那是後續 task 的 `validation.py` / `observability.py`；`RetryConfig` 這裡只是設定值，沒有重試邏輯。
- 不負責業務規則檢查（Scheduler 的 `pacing` 上限、修訂策略約束等）——這裡只驗 schema，內容是否合理由 domain 決定。
- 不負責 prompt 的內容設計。本 package 只放一支最小範例 `prompts/smoke.md`；四支正式 prompt（`evaluate_readiness`、`generate_plans`、`revise_plan`、`recommend_role_models`）由對應的 task 建立。
- 不負責 token 計數、成本統計、快取或限流。
- 不負責決定要組哪些 context（role model 渲染、session 摘要），呼叫端把 dict 準備好再進來。
