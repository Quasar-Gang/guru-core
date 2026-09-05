# guru-core 本地 LLM 快速架設

本機 demo 的預設組合是 **Ollama + `qwen3.5:9b`（Q4_K_M）**。此 tag 約 6.6 GB，適合目前的 Apple M4／24 GB unified memory；腳本把 context 控制在 16K，為 guru-core、PostgreSQL 與 Redis 保留記憶體。

完整候選比較、授權分類、PRD 缺口與驗收矩陣見 [`research/local-llm-evaluation.md`](research/local-llm-evaluation.md)。

## 一鍵啟動與驗證

在 repo 根目錄執行：

```bash
./scripts/local-llm.sh demo
```

它會依序：

1. 在 macOS 透過 Homebrew 安裝 Ollama（若尚未安裝）。
2. 啟動只監聽 `127.0.0.1:11434` 的本地服務。
3. 下載 `qwen3.5:9b`。
4. 透過 `/v1/chat/completions` 執行繁體中文、JSON Schema smoke test。

第一次約需下載 6.6 GB；後續執行會沿用模型快取。成功時會看到 `PASS: Traditional Chinese structured output is valid`。目前實機解析到的模型 digest 是 `6488c96fa5fa`；正式 demo 前可用 `ollama list` 核對，避免 mutable tag 已漂移。

## guru-core 設定

```bash
export LLM_BASE_URL=http://127.0.0.1:11434/v1
export LLM_API_KEY=ollama
export LLM_MODEL=qwen3.5:9b
export LLM_MAX_CONTEXT=16384
```

`config/llm.yaml` 應使用：

```yaml
provider:
  adapter: openai_compat
  base_url: ${LLM_BASE_URL}
  api_key: ${LLM_API_KEY:-ollama}
  model: ${LLM_MODEL:-qwen3.5:9b}
  structured_output: json_schema
  max_context_tokens: ${LLM_MAX_CONTEXT:-16384}
  timeout_seconds: 240
  concurrency: 1

params:
  evaluate:  {temperature: 0.2, max_output_tokens: 1500, reasoning_effort: none}
  generate:  {temperature: 0.4, max_output_tokens: 4000, reasoning_effort: none}
  revise:    {temperature: 0.3, max_output_tokens: 3000, reasoning_effort: none}
  recommend: {temperature: 0.3, max_output_tokens: 800,  reasoning_effort: none}
```

這裡選 `json_schema`，因為 Ollama 的 OpenAI-compatible `/v1/chat/completions` 已支援 `response_format`；guru-core 仍須保留 Pydantic 驗證、業務規則驗證與重試，不能把 provider 約束當成唯一防線。

## 日常操作

```bash
./scripts/local-llm.sh status   # 服務與已下載模型
./scripts/local-llm.sh smoke    # 重跑 PRD 對應的 schema 測試
./scripts/local-llm.sh logs     # 查看由此腳本啟動的 server log
./scripts/local-llm.sh stop     # 只停止此腳本啟動的 server
```

換用較輕的 4B 模型做快速迭代：

```bash
LLM_MODEL=qwen3.5:4b ./scripts/local-llm.sh demo
```

不建議在這台 24 GB 機器上把 27B Q4 當 guru-core 預設：模型本身約 18 GB，再加 KV cache、Ollama 與應用服務後餘裕太小，容易發生 memory pressure，且首 token 延遲較高。

## 問題排查

- `address already in use`：已有 Ollama 在跑；腳本會優先沿用可回應的既有 server。若該程序異常，先從 Ollama app 結束它。
- smoke test 回 `model not found`：執行 `./scripts/local-llm.sh pull`。
- 記憶體壓力高：把 `LLM_MAX_CONTEXT` 降到 `8192`，或改用 `qwen3.5:4b`。
- schema 驗證偶發失敗：確認沒有使用 Ollama 的 `-mlx` 模型 tag；本 demo 固定使用 GGUF `Q4_K_M`。在應用層保留最多三次修正重試。
- 服務只供本機開發，預設不要把 `OLLAMA_HOST` 設成 `0.0.0.0`；Ollama 本身不替此端點加認證。

## 一手資料

- [Qwen3.5-9B 官方模型卡](https://huggingface.co/Qwen/Qwen3.5-9B)
- [Ollama `qwen3.5:9b` 模型頁](https://ollama.com/library/qwen3.5:9b)
- [Ollama OpenAI compatibility](https://docs.ollama.com/api/openai-compatibility)
- [Ollama structured outputs](https://docs.ollama.com/capabilities/structured-outputs)
- [Ollama macOS 文件](https://docs.ollama.com/macos)
