# guru-core 本地 LLM 選型與 PRD 評估

> 研究日期：2026-09-05
> 適用文件：`guru-core-PRD.md` v0.2 Draft
> 目標硬體：MacBook Pro（Apple M4、10-core CPU、10-core GPU、24 GB unified memory）
> 證據範圍：模型開發者的 model card／技術報告、官方文件與原始 repository；模型能力數字均為供應商自評，尚未等同 guru-core 的實測結果。

## 1. 結論

本機 demo 建議採用：

- **Runtime：Ollama（原生 macOS 安裝，不放進 Docker）**
- **主模型：`qwen3.5:9b`（Ollama 版 6.6 GB；本機解析 digest `6488c96fa5fa`）**
- **明確配置：16,384 context、低溫、`reasoning_effort: none`、單一併發**
- **穩定回退：`qwen3:8b`（Ollama Q4_K_M 5.2 GB）**

選擇 `qwen3.5:9b` 的原因不是單一通用 benchmark，而是它最符合本產品的交集：9B 尺寸在 24 GB unified memory 留有充分餘裕、原生 262K context、201 種語言／方言、強 instruction following 與 agent 能力、Apache-2.0 權重、Ollama 官方直接提供 6.6 GB artifact，且 Ollama 的 OpenAI-compatible Chat Completions 已支援 `response_format` JSON Schema 與 reasoning control。[Qwen3.5-9B 官方 model card](https://huggingface.co/Qwen/Qwen3.5-9B)、[Ollama Qwen3.5 library](https://ollama.com/library/qwen3.5)、[Ollama OpenAI compatibility](https://docs.ollama.com/api/openai-compatibility)

這是一個**待完整 guru-core 任務集驗證的工程選擇**，不是品質已獲證明的結論。本次 smoke test 已證明 Metal 100% GPU offload、16,384 context 與 OpenAI-compatible JSON Schema 路徑可用；同時首次輸出出現「JSON 合 schema、業務語意卻錯置」，第二次出現 `ready=true` 但 `missing` 非空，證明 PRD 的 Pydantic 後業務規則檢查與修正重試不可省。PRD 應保留 provider 可切換設計，並以四種實際 schema 的成功率決定是否升級到較大模型或雲端模型。

## 2. 從 PRD 反推的模型需求

PRD 的模型工作並非開放式聊天，而是四種受限、可驗證的轉換：

| 呼叫 | 次數／觸發 | 最大輸出 | 主要難點 |
|---|---:|---:|---|
| `evaluate_readiness` | 每 session 1–3 次 | 1,500 tokens | 從混合 context 判斷缺口；問題數與選項數必須守規格 |
| `generate_plans` | 每 session 1 次 | 4,000 tokens | 產生巢狀 `PlanTemplate`；遵守 pacing 與相對排程規則 |
| `revise_plan` | 每次修訂 1 次 | 3,000 tokens | 在策略與既有 template 約束內修改，不破壞 key 對齊 |
| `recommend_role_model` | 用戶查詢時 1 次 | 800 tokens | 從有限候選選 ≤3 筆，ID 必須完全來自候選集合 |

因此優先順序應為：

1. **Schema-constrained JSON 與指令遵循穩定度**，而非純知識問答分數。
2. **繁體中文與中英混合 context**；guru-core 的介面與 role model 內容很可能以中文為主。
3. **16K 實際 context 能在 24 GB 記憶體穩定執行**，同時保留 4K 輸出與 application／OS 空間。
4. **低延遲、可關閉長思考**；四個呼叫多數是抽取、排序與受限生成，不值得為每次請求支付長 CoT。
5. **OpenAI-compatible API**，避免改動既定 `OpenAICompatLLM` 邊界。
6. **可重現 artifact 與可接受授權**，方便 demo、CI fixture 與日後商用評估。

PRD 已做對小模型非常有利的切割：只讓 LLM 產一份基準 template，三種難度、日期排程、diff、粗篩、計分與 Markdown rendering 均由 deterministic code 負責。這比直接換更大的模型更能提高可靠性。

## 3. 「開源」與「開放權重」不能混用

OSI 的 Open Source AI Definition 1.0 要求使用、研究、修改、分享四項自由，且可修改的首選形式需包含足夠的訓練資料資訊、完整訓練／資料處理／推理程式碼，以及參數。單純能下載權重，甚至權重套用 Apache-2.0／MIT，仍不自動證明整個模型符合 OSAID。[OSI OSAID 1.0](https://opensource.org/ai/open-source-ai-definition)、[OSI FAQ](https://opensource.org/ai/faq)

本文採以下標記：

- **Fully open／OSAID 路線**：官方公開從資料、訓練程式碼、recipe、checkpoints 到評測的完整 model flow；仍應在法務使用前核對實際 artifact 授權。
- **Permissively licensed open weights**：權重是 Apache-2.0／MIT，商用與衍生通常較容易，但未證明整個 model flow 符合 OSAID。
- **Community／custom terms open weights**：可下載權重，但有 use policy、分發、命名、規模或用途限制；不是 OSI open source。

| 模型 | 權重／使用條款 | 本文分類 | 判斷 |
|---|---|---|---|
| Qwen3／Qwen3.5 | Apache-2.0 | Permissively licensed open weights | 權重條款寬鬆；官方 model card 並未在本文查證範圍內提供可重建等價系統所需的完整資料與訓練 code |
| Mistral Small 3.1 | Apache-2.0 | Permissively licensed open weights | 同上；Mistral 稱其 open source，但本文不把供應商用語當作 OSAID 認證 |
| DeepSeek-R1 Distill Qwen | MIT，底模 Qwen2.5 Apache-2.0 | Permissively licensed open weights | repo 公開技術報告與權重；800K 蒸餾樣本的完整可重建資料流未在本文查證為全公開 |
| gpt-oss | Apache-2.0，另有 usage policy | Permissively licensed open weights | OpenAI 官方也明確稱其 **open-weight**，不是 fully open model flow |
| Llama 3.x | Llama Community License + Acceptable Use Policy | Custom-license open weights；**非 OSI** | 有用途政策、700M MAU 額外條件、分發／命名義務；OSI 亦明確判定 Llama 3.x 不是 open source |
| Gemma 3 | Gemma Terms + Prohibited Use Policy | Custom-terms open weights；**非 OSI** | 使用與分發受禁止用途及 notice 等條款約束，不是 OSI-approved license |
| Olmo 3 | Apache-2.0；公開資料、code、recipes、checkpoints | Fully open 路線 | Ai2 公開完整 model flow；最適合作為「真正開源」對照與備選 |

主要條款的一手來源：[Qwen3-8B](https://huggingface.co/Qwen/Qwen3-8B)、[Qwen3.5-9B LICENSE](https://huggingface.co/Qwen/Qwen3.5-9B/blob/main/LICENSE)、[Mistral Small 3.1](https://huggingface.co/mistralai/Mistral-Small-3.1-24B-Instruct-2503)、[DeepSeek-R1 LICENSE 說明](https://github.com/deepseek-ai/DeepSeek-R1#7-license)、[gpt-oss model card](https://openai.com/index/gpt-oss-model-card/)、[Llama 3.1 license](https://github.com/meta-llama/llama-models/blob/main/models/llama3_1/LICENSE)、[Gemma Terms](https://ai.google.dev/gemma/terms)、[Olmo 3 model flow](https://allenai.org/blog/olmo3)。OSI 對 Llama 3.x 的結論見 [Meta’s LLaMa license is still not Open Source](https://opensource.org/blog/metas-llama-license-is-still-not-open-source)。

對 PRD 的直接建議：第 6、7 節的「本地開源模型」應在後續修訂時改為「本地部署模型（優先採寬鬆授權的 open-weight 模型）」，另設一個 `model_license_reviewed_at` 或 release checklist，而不是讓 runtime 選型代替模型授權審查。Ollama／llama.cpp 的 MIT 授權不會覆蓋其下載的模型權重。[Ollama LICENSE](https://github.com/ollama/ollama/blob/main/LICENSE)、[llama.cpp LICENSE](https://github.com/ggml-org/llama.cpp/blob/master/LICENSE)

## 4. 候選模型比較

### 4.1 快速比較

檔案大小取自 Ollama 官方 library 的預設 artifact；它是磁碟上的權重大小，不等於執行時總記憶體。執行還需要 KV cache、運算 buffers 與 runtime，context 越大用量越高。

| 候選 | 參數／架構 | 官方 context | Ollama artifact | 中文／多語 | 授權分類 | 24 GB M4 判斷 |
|---|---|---:|---:|---|---|---|
| **Qwen3.5 9B** | 9B dense hybrid attention | 262K native | **6.6 GB** | 201 languages／dialects | Apache-2.0 open weights | **首選；16K 有充足餘裕** |
| Qwen3 8B | 8.2B dense | 32K native；YaRN 131K | 5.2 GB Q4_K_M | 100+ languages／dialects | Apache-2.0 open weights | **穩定回退** |
| Gemma 3 12B IT | 12B dense, multimodal | 128K；output 8K | 8.1 GB Q4_K_M | 140+ languages | Gemma custom terms | 可跑；條款與中文優勢不如 Qwen |
| Llama 3.1 8B Instruct | 8B dense | 128K | 4.9 GB | 官方列 8 languages | Llama custom license | 可跑；中文與授權皆不優先 |
| Mistral Small 3.1 24B | 24B dense, multimodal | 128K | — | 24 languages | Apache-2.0 open weights | **不選；官方門檻為量化後 32 GB Mac** |
| DeepSeek-R1 Distill Qwen 7B | Qwen2.5-Math 7B distill | Ollama 標示 128K | 4.7 GB Q4_K_M | reasoning／中文評測佳 | MIT + 底模 Apache-2.0 open weights | 可跑；不適合預設的短受限生成 |
| gpt-oss 20B | 21B total／3.6B active MoE | 128K | 14 GB MXFP4 | 官方稱 mostly English | Apache-2.0 open weights | 可跑但餘裕小；第二階段實驗 |
| Olmo 3 7B Instruct | 7B dense | 64K | 4.5 GB Q4_K_M | 主要競爭力不是中文 | Fully open model flow | 真開源備選；需以中文任務集驗證 |

來源：[Qwen3.5 官方 model card](https://huggingface.co/Qwen/Qwen3.5-9B)、[Qwen3.5 Ollama tags](https://ollama.com/library/qwen3.5)、[Qwen3-8B 官方 model card](https://huggingface.co/Qwen/Qwen3-8B)、[Qwen3 Ollama tags](https://ollama.com/library/qwen3/tags)、[Gemma 3 model card](https://ai.google.dev/gemma/docs/core/model_card_3)、[Gemma 3 Ollama tags](https://ollama.com/library/gemma3/tags)、[Meta Llama models table](https://github.com/meta-llama/llama-models#llama-models)、[Llama 3.1 Ollama](https://ollama.com/library/llama3.1)、[Mistral Small 3.1 官方 model card](https://huggingface.co/mistralai/Mistral-Small-3.1-24B-Instruct-2503)、[DeepSeek-R1 repo](https://github.com/deepseek-ai/DeepSeek-R1)、[DeepSeek-R1 Ollama tags](https://ollama.com/library/deepseek-r1/tags)、[gpt-oss 官方介紹](https://openai.com/index/introducing-gpt-oss/)、[gpt-oss Ollama](https://ollama.com/library/gpt-oss)、[Olmo 3 官方 model card](https://huggingface.co/allenai/Olmo-3-7B-Instruct)、[Olmo 3 Ollama](https://ollama.com/library/olmo-3)。

### 4.2 Qwen3.5 9B：推薦

Qwen3.5-9B 的官方卡列出 9B、32 層、混合 Gated DeltaNet／full attention、262,144 native context，並聲稱支援 201 種語言與方言。官方自評的 IFEval 88.9、IFBench 69.0 與多語基準是值得進入 shortlist 的訊號，但不能替代本產品 schema eval。[Qwen3.5-9B model overview 與官方 eval](https://huggingface.co/Qwen/Qwen3.5-9B#model-overview)

優點：

- 在 24 GB 機器上，6.6 GB artifact 比 14–24 GB 級候選保留更多 KV cache 與 application 空間。
- 中英文、多語、instruction following 與 agent 能力都直接對準本產品。
- 16K 只占模型原生 context 的小部分，無需 RoPE extension。
- Ollama 官方 model 可直接下載，不依賴未審核的第三方 GGUF。
- Apache-2.0 權重比 Llama／Gemma custom terms 更易納入產品，但仍不應標成已驗證的 OSAID model。

風險：

- Qwen3.5 預設會 thinking，且不像 Qwen3 使用 `/think`／`/nothink` soft switch；官方 API 範例以 `enable_thinking: false` 關閉。[Qwen3.5 non-thinking 說明](https://huggingface.co/Qwen/Qwen3.5-9B#instruct-or-non-thinking-mode)
- 因此 guru-core 透過 Ollama OpenAI-compatible API 時，應送 `reasoning_effort: "none"`，並驗證 response 中不會把 reasoning 混入 JSON。Ollama 官方列此欄位為支援項。[Ollama OpenAI compatibility](https://docs.ollama.com/api/openai-compatibility)
- 新架構比 Qwen3 更年輕；demo 要 pin Ollama 版本與 model digest，不能只 pin mutable tag。

### 4.3 Qwen3 8B：保守回退

Qwen3-8B 是 8.2B dense model，原生 32,768 context，可用 YaRN 延伸至 131,072；支援 thinking／non-thinking 切換、100+ 語言與 agent／tool use。對 PRD 的 16K 不需啟用 YaRN，官方也警告 static YaRN 可能降低短 context 表現。[Qwen3-8B 官方 model card](https://huggingface.co/Qwen/Qwen3-8B)、[Qwen3 官方發布](https://qwenlm.github.io/blog/qwen3/)

它較推薦模型舊，但 runtime 支援成熟、5.2 GB Q4_K_M 很輕，適合作為「Qwen3.5 schema eval 未達標」時的無痛回退，而不是 DeepSeek reasoning distill。

### 4.4 Gemma 3 12B IT

Gemma 3 有 1B／4B／12B／27B；4B、12B、27B 為 128K input context，輸出上限 8,192，支援 140+ 語言與 image input。Ollama 的 12B Q4_K_M 為 8.1 GB，記憶體上適合這台 Mac。[Gemma 3 官方 model card](https://ai.google.dev/gemma/docs/core/model_card_3)、[Gemma 3 Ollama tags](https://ollama.com/library/gemma3/tags)

不列首選的原因是：guru-core MVP 不需要 vision；Gemma Terms 帶有 Prohibited Use Policy 與分發義務；官方多語覆蓋雖佳，但 Qwen 對中文產品更直接，且 artifact 更小。它可作為第二個非 reasoning baseline。

### 4.5 Llama 3.x

能合理放進此硬體的主力是 Llama 3.1 8B Instruct（128K、Ollama 4.9 GB），不是 70B／405B；Llama 3.2 1B／3B 更省資源，但對巢狀計畫生成品質風險更高。Meta 官方表列 Llama 3.1 支援 8B／70B／405B 與 128K context。[Meta llama-models table](https://github.com/meta-llama/llama-models#llama-models)、[Llama 3.1 Ollama](https://ollama.com/library/llama3.1)

它的生態成熟且可跑，但 Llama 3.1 Community License 包含 Acceptable Use Policy、700M MAU 條件、`Built with Llama`／衍生模型命名等要求，不是 OSI license；而官方發布只列八種支援語言，對繁體中文產品沒有選 Qwen 的理由。[Llama 3.1 license](https://github.com/meta-llama/llama-models/blob/main/models/llama3_1/LICENSE)、[Meta Llama 3.1 官方發布](https://ai.meta.com/blog/meta-llama-3-1/)

### 4.6 Mistral Small 3.x

Mistral Small 3.1 是 24B、128K、24-language、Apache-2.0 model，官方定位包含 function calling、長文件與本地敏感資料用途。然而官方明寫量化後適合「單 RTX 4090 或 **32 GB RAM MacBook**」，因此不能把它列為這台 24 GB Mac 的可靠 demo 模型。[Mistral Small 3.1 官方發布](https://mistral.ai/news/mistral-small-3-1/)、[官方 model card](https://huggingface.co/mistralai/Mistral-Small-3.1-24B-Instruct-2503)

截至研究日，Mistral 官方已將 3.1 標為 retired、建議新 integration 使用 Small 4；但 Small 4 為 119B total／約 6B active，官方最低部署基礎設施是多張 H100/H200 或 B200，顯然不適合本機 24 GB demo。[Mistral Small 3.1 model lifecycle](https://docs.mistral.ai/models/mistral-small-3-1-25-03)、[Mistral Small 4 官方發布](https://mistral.ai/news/mistral-small-4/)

### 4.7 DeepSeek-R1 distilled

可行版本是 `DeepSeek-R1-Distill-Qwen-7B`（Ollama 4.7 GB），不是 671B 原模型。它由 Qwen2.5-Math-7B 以 800K DeepSeek-R1 樣本 fine-tune，MIT 發布；官方評測顯示 7B distill 的優勢集中在數學、程式與長 reasoning。[DeepSeek-R1 repo](https://github.com/deepseek-ai/DeepSeek-R1)、[DeepSeek-R1 technical report](https://arxiv.org/abs/2501.12948)、[Ollama artifact](https://ollama.com/library/deepseek-r1/tags)

它不適合作為 guru-core 預設：官方建議避免 system prompt、溫度 0.5–0.7，並可能產生長 CoT；這與 PRD 的 system/prompt abstraction、低溫 JSON schema、800–4,000 output token budget 有張力。它可以留作「策略可行性或複雜修訂 reasoning」實驗，不應因 reasoning benchmark 高就取代一般 instruct model。[DeepSeek 官方 usage recommendations](https://github.com/deepseek-ai/DeepSeek-R1#usage-recommendations)

### 4.8 gpt-oss 20B

gpt-oss-20b 是 21B total／3.6B active MoE，128K context、原生 MXFP4，官方稱 16 GB memory 可執行，並明列 function calling、Structured Outputs 與可調 reasoning effort。Ollama artifact 為 14 GB。[OpenAI 官方介紹](https://openai.com/index/introducing-gpt-oss/)、[gpt-oss-20b model card](https://huggingface.co/openai/gpt-oss-20b)、[Ollama gpt-oss](https://ollama.com/library/gpt-oss)

它是 schema 能力很有吸引力的第二階段候選，但不是首選：14 GB 權重在 24 GB unified memory 加上 16K KV cache、Ollama、Postgres、Redis 與 API services 後餘裕有限；官方也明確說預訓練資料「mostly English」。此外它必須使用 Harmony format，雖然 Ollama 已代為處理，仍增加 provider-specific 行為。[gpt-oss architecture/data](https://openai.com/index/introducing-gpt-oss/)、[Harmony format requirement](https://huggingface.co/openai/gpt-oss-20b)

### 4.9 Olmo 3 7B Instruct：真正開放的備選

Ai2 公開 Olmo 3 的 pretraining／midtraining／long-context／post-training 資料、訓練 scripts、recipes、checkpoints 與評測。7B Instruct 是 Apache-2.0，Ollama artifact 4.5 GB、64K context，且官方宣稱具 instruction following 與 function calling 能力。[Olmo 3 官方發布](https://allenai.org/blog/olmo3)、[官方訓練 scripts 與 data manifests](https://github.com/allenai/OLMo-core/tree/main/src/scripts/official/OLMo3)、[Olmo 3 model card](https://huggingface.co/allenai/Olmo-3-7B-Instruct)、[Ollama Olmo 3](https://ollama.com/library/olmo-3)

若產品對「真正 fully open」有硬性要求，它應優先進入 eval；但目前官方強項與 benchmark 主要不足以證明繁體中文計畫生成，所以不能僅靠 openness 取代中文任務實測。

## 5. Runtime 比較

| Runtime | Apple M4 | OpenAI-compatible | Schema 約束 | 維護成本 | guru-core 適合度 |
|---|---|---|---|---|---|
| **Ollama** | 原生 Apple GPU／Metal | Chat、Completions、Models、Embeddings、Responses 的部分相容 | `response_format` JSON Schema；native API 用 `format` | 最低；下載／管理／服務整合 | **demo 首選** |
| llama.cpp | Apple Silicon 是 first-class；Metal | `llama-server` 提供 Chat／Responses 等，但不承諾完整規格 | JSON Schema → GBNF；可全局 grammar | 中高；自行管理 GGUF、參數、模板 | 精細控制／可重現 benchmark 首選 |
| MLX-LM | Apple Silicon 原生 | 簡易、類 OpenAI server | 未把 schema enforcement 當主要 server contract | 中；Python／HF 模型管理 | 模型研究與 LoRA；不建議當目前 provider server |
| vLLM | 2026 已有 experimental macOS CPU 與 community `vLLM-Metal` plugin | 完整部署生態強 | guided／structured output 強 | 本機最高；需 build／plugin | Linux GPU production 候選，不是最快 demo 路徑 |

### 為何選 Ollama

Ollama 原生支援 macOS／Apple M 系列 GPU、CLI、模型管理、REST API 和 OpenAI-compatible endpoint；structured outputs 可直接接 Pydantic `model_json_schema()`，官方建議低 temperature，且可在 OpenAI path 使用 `response_format`。[Ollama macOS](https://docs.ollama.com/macos)、[Structured Outputs](https://docs.ollama.com/capabilities/structured-outputs)、[OpenAI compatibility](https://docs.ollama.com/api/openai-compatibility)

Mac 上不要把 Ollama server 放進 Docker。Ollama 官方 FAQ 明確指出 Docker Desktop for macOS 不支援 GPU passthrough；容器化只會失去 Apple GPU 加速。應讓 Ollama 原生跑在 host，guru-core services 再連 `host.docker.internal:11434`（若 services 在 Docker）或 `localhost:11434`（若 services 在 host）。[Ollama Docker](https://docs.ollama.com/docker)、[Ollama FAQ](https://docs.ollama.com/faq)

### llama.cpp 的位置

llama.cpp 支援 Metal、GGUF、多種量化、CPU/GPU hybrid offload，以及 `llama-server` OpenAI-compatible API。其 schema-constrained JSON 可把 JSON Schema 轉成 GBNF，適合做嚴格 benchmark 與追查 grammar 行為。[llama.cpp README](https://github.com/ggml-org/llama.cpp)、[llama-server API](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md)、[JSON Schema grammar](https://github.com/ggml-org/llama.cpp/blob/master/grammars/README.md)

代價是 guru-core 必須自行 pin GGUF、chat template、context、batch、Metal offload 與 server flags；作為一鍵 demo 的第一版沒有必要。

### MLX-LM 與 vLLM

MLX-LM 專為 Apple Silicon 的生成、quantization 與 fine-tuning 設計，但官方 server 只稱「intended to be similar」於 OpenAI API，並明確不建議 production。它更適合模型實驗，不適合拿來驗證 PRD 已定義的通用 provider contract。[MLX-LM README](https://github.com/ml-explore/mlx-lm)、[MLX-LM server](https://github.com/ml-explore/mlx-lm/blob/main/mlx_lm/SERVER.md)

vLLM 對 Linux GPU production 很合理；但在 Apple Silicon 上，官方 CPU 支援仍是 experimental，GPU 需 community-maintained vLLM-Metal plugin。對這次「最快本地 demo」沒有勝過 Ollama。[vLLM Apple Silicon installation](https://docs.vllm.ai/en/latest/getting_started/installation/cpu/?device=apple)

## 6. 24 GB M4 的容量判斷

已實機確認：Apple M4、10 CPU cores、10 GPU cores、24 GB unified memory，Metal 3；磁碟尚有約 597 GiB，因此瓶頸是 shared memory 與 context，不是下載容量。

### 建議安全帶

- 以 **6–9 GB 級 Q4 artifact** 作 demo 主力；權重、16K KV cache、runtime 與 application services 後仍有合理 headroom。
- 14 GB `gpt-oss:20b` 可測，但不要同時把多個大模型常駐。
- 17–20 GB artifact（Gemma 3 27B、Qwen3 30B-A3B、DeepSeek 32B）雖可能「勉強載入」，不代表 16K context、4K generation 與完整 stack 能穩定運行；不列 demo 預設。
- Mistral Small 3.1 官方明列 32 GB Mac，是明確排除證據。
- demo 初期將 LLM worker 併發設為 **1**；完成單請求 correctness 與記憶體量測後再測 2。

### 必須顯式設定 context

Ollama 會依可用 VRAM 自動選 context：官方預設在 `<24 GiB` 為 4K、`24–48 GiB` 為 32K，而且 context 越大越耗記憶體。24 GB unified memory 恰在邊界，不能依賴自動判斷；PRD 要求 16K，啟動時應顯式設 `OLLAMA_CONTEXT_LENGTH=16384`，再以 `ollama ps` 確認配置與 offload。[Ollama context length](https://docs.ollama.com/context-length)

模型支援 128K／256K 不代表本機應開滿。PRD 的 input + output 必須共同落在 allocated context 內；在 16,384 上，`generate` 若保留 4,000 output，組裝後 prompt 的硬上限應約 12K，還需預留 chat template tokens。超過時應先 deterministic truncation／summarization，而不是讓 runtime 默默截斷。

### 本機 demo 實測

2026-09-05 以 Ollama 0.33.2、`qwen3.5:9b` digest `6488c96fa5fa`、`OLLAMA_CONTEXT_LENGTH=16384`、`reasoning_effort: none`，透過 OpenAI-compatible `/v1/chat/completions` 發送繁中 readiness JSON Schema：

| 項目 | 結果 |
|---|---|
| 模型載入 | `ollama ps`：5.9 GB、100% GPU、context 16,384 |
| 冷啟／首輪總耗時 | 25.40 秒（96 input + 272 output tokens） |
| 加強 prompt 與 invariant 後暖機耗時 | 17.08 秒、14.01 秒 |
| 最後一輪 decode | 約 15.9 tokens/s（Ollama server timing） |
| Transport / JSON Schema | 三輪皆可解析並符合欄位型別／數量 schema |
| 業務規則 | 首輪把題目文字錯放進 `missing[]`；第二輪出現 `ready=true` 但仍有缺項；加入明確 invariant 後第三輪通過 |

這個樣本只能證明本機路徑可跑，以及 reveal 出 validator 必要性；單一 prompt、暖機 cache 與短 input 不能外推 production latency 或品質。完整結論仍以第 9 節的固定 eval set 為準。

## 7. 對 PRD LLM 章節的評估

### 已做對的部分

- `LLMPort` 隔離 use case 與供應商 SDK，且 model／temperature／token 上限留在 adapter 設定。
- 本地與雲端共用 OpenAI-compatible adapter，切換面積小。
- provider schema 約束後仍做 Pydantic 與業務規則驗證，失敗回灌、有限重試、最後保守降級；這是正確的 defense in depth。
- deterministic scheduler、難度推導、diff、role model 粗篩不交給 LLM，大幅降低小模型負擔。
- prompt/version/model/token/latency/retry/fallback 觀測足以支援後續實證選型。

### 需要補齊的決策

1. **選定 demo baseline**：`qwen3.5:9b` + Ollama；pin Ollama version、model tag 與 digest。不要只寫「模型之後再定」。
2. **顯式 context**：啟動環境設 `OLLAMA_CONTEXT_LENGTH=16384`；啟動後檢查 `/v1/models`、`ollama ps` 與一次 16K prefill。
3. **關閉非必要 reasoning**：`evaluate`、`generate`、`revise`、`recommend` 預設都送 `reasoning_effort: none`；若日後只對 revise 開 reasoning，應成為 purpose-level provider param。
4. **精確定義 schema payload**：Ollama OpenAI path 使用 `response_format: {type: "json_schema", json_schema: ...}`，而不是把 `json_schema` 當抽象字串結束；adapter contract test 應確認實際 wire payload。
5. **輸出 token mapping**：PRD 的 `max_output_tokens` 是內部名稱；Chat Completions 對 Ollama 的實際欄位是 `max_tokens`。adapter 應明確 mapping 並測試。
6. **prompt 截斷策略**：定義 profile、document、calendar、role model、schema、output reserve 的硬預算與截斷順序。`budgets` 目前只管 role model，不足以保證總 prompt ≤ context。
7. **併發／backpressure**：本機 demo 預設 LLM concurrency=1；超時 180 秒與 queue retry 要避免同一 model 同時堆積多次 generation。
8. **真實 smoke test**：`check_llm.py` 不應只測「能回答」；至少逐一送四種 production schema，驗證 JSON、Pydantic、業務規則、候選 ID 約束與 retry telemetry。
9. **runtime 相容不是模型相容**：每個新模型需驗證 chat template、reasoning 分離、schema、繁中與 context；不能因 `/v1/chat/completions` 可用就宣告可替換。
10. **授權語言**：把「本地開源模型」改成精確分類，並在 release checklist 記錄權重 license、use policy、notice／attribution 與衍生模型條件。

## 8. Demo 配置基線與快速架設腳本

Repo 已提供 `scripts/local-llm.sh` 與 `scripts/llm_smoke_test.py`；使用方式見 `docs/local-llm-quickstart.md`。腳本與後續應用實作共同固定以下 contract：

```text
Runtime:              Ollama, native macOS
Model:                qwen3.5:9b
Model artifact:       pin resolved digest after pull
LLM_BASE_URL:         http://localhost:11434/v1
LLM_API_KEY:          ollama (required by client, ignored by Ollama)
LLM_MODEL:            qwen3.5:9b
LLM_MAX_CONTEXT:      16384
OLLAMA_CONTEXT_LENGTH:16384
structured_output:    json_schema
reasoning_effort:     none
concurrency:          1
```

若 guru-core services 跑在 Docker，`LLM_BASE_URL` 應改成 `http://host.docker.internal:11434/v1`，Ollama 仍留在 macOS host。

建議一鍵腳本依序做：

1. 檢查 Apple Silicon、macOS 版本、可用記憶體與磁碟。
2. 檢查／安裝 Ollama；啟動 host service 並等待 health endpoint。
3. `ollama pull qwen3.5:9b`，解析並記錄 digest。
4. 以 16K context 啟動／重啟 service。
5. 檢查 `/v1/models` 與 `ollama ps`。
6. 發出一個帶嚴格 JSON Schema、繁體中文內容、`reasoning_effort: none` 的 smoke request。
7. 用 Pydantic 驗證 response；失敗時顯示 server log 與退出非零碼。
8. 匯出 guru-core 所需環境變數後才啟動 application stack。

## 9. 上線前的模型驗收矩陣

不要以 MMLU／Arena 直接決定產品模型。建立固定、去識別的 guru-core eval set，每種 prompt 至少 30–50 筆，包含繁中、英文、混合語言、長文件、Calendar 衝突、缺資訊與惡意文件內容。

| 指標 | 建議 demo gate | 測法 |
|---|---:|---|
| JSON parse success | ≥ 99%（含最多 3 次重試） | 四個 schema 各自統計，不只總平均 |
| Pydantic schema success | ≥ 98% 首次；≥ 99% 重試後 | 記錄欄位缺失、型別錯、extra field |
| 業務規則 success | ≥ 95% 首次；≥ 99% 重試／fallback 後 | pacing、題數、候選 ID、template keys |
| 繁中可讀性 | 人評 ≥ 4/5 | 台灣用語、無簡繁混亂、任務具體可做 |
| 不忠實引用輸入 | 0 個非法 candidate ID | role model recommendation 做 set membership |
| 16K context 穩定 | 100% 無 OOM／截斷 | 最長 prompt + 4K output reserve，連續至少 20 次 |
| 延遲 | 先量 baseline，再設產品 SLO | 分 prefill、time-to-first-token、decode、總耗時 |
| fallback rate | < 1% | 按 prompt_name 與模型版本切分 |

至少比較 `qwen3.5:9b`、`qwen3:8b`、`olmo-3:7b-instruct`；若記憶體量測仍有餘裕，再加入 `gpt-oss:20b`。只有當 Qwen3.5 未通過 gate，才以證據換模型或切雲端，避免用供應商 benchmark 代替產品決策。

## 10. 引用來源索引

### 模型與授權

- Qwen：[Qwen3 發布](https://qwenlm.github.io/blog/qwen3/)、[Qwen3-8B model card](https://huggingface.co/Qwen/Qwen3-8B)、[Qwen3.5-9B model card](https://huggingface.co/Qwen/Qwen3.5-9B)、[Qwen3.5 LICENSE](https://huggingface.co/Qwen/Qwen3.5-9B/blob/main/LICENSE)
- Google：[Gemma 3 model card](https://ai.google.dev/gemma/docs/core/model_card_3)、[Gemma Terms](https://ai.google.dev/gemma/terms)、[Gemma Prohibited Use Policy](https://ai.google.dev/gemma/prohibited_use_policy)
- Meta：[Llama model table](https://github.com/meta-llama/llama-models#llama-models)、[Llama 3.1 發布](https://ai.meta.com/blog/meta-llama-3-1/)、[Llama 3.1 license](https://github.com/meta-llama/llama-models/blob/main/models/llama3_1/LICENSE)
- Mistral：[Mistral Small 3.1 發布](https://mistral.ai/news/mistral-small-3-1/)、[Mistral Small 3.1 model card](https://huggingface.co/mistralai/Mistral-Small-3.1-24B-Instruct-2503)、[Mistral Small 4 發布](https://mistral.ai/news/mistral-small-4/)
- DeepSeek：[DeepSeek-R1 repository](https://github.com/deepseek-ai/DeepSeek-R1)、[DeepSeek-R1 paper](https://arxiv.org/abs/2501.12948)
- OpenAI：[gpt-oss 發布](https://openai.com/index/introducing-gpt-oss/)、[gpt-oss model card](https://openai.com/index/gpt-oss-model-card/)、[gpt-oss-20b weights card](https://huggingface.co/openai/gpt-oss-20b)
- Ai2：[Olmo 3 發布與 model flow](https://allenai.org/blog/olmo3)、[Olmo 3 training source](https://github.com/allenai/OLMo-core/tree/main/src/scripts/official/OLMo3)、[Olmo 3 7B Instruct card](https://huggingface.co/allenai/Olmo-3-7B-Instruct)
- OSI：[Open Source AI Definition 1.0](https://opensource.org/ai/open-source-ai-definition)、[OSAID FAQ](https://opensource.org/ai/faq)、[Llama 3.x license 評估](https://opensource.org/blog/metas-llama-license-is-still-not-open-source)

### Runtime

- Ollama：[repository](https://github.com/ollama/ollama)、[macOS](https://docs.ollama.com/macos)、[OpenAI compatibility](https://docs.ollama.com/api/openai-compatibility)、[Structured Outputs](https://docs.ollama.com/capabilities/structured-outputs)、[context length](https://docs.ollama.com/context-length)、[Docker](https://docs.ollama.com/docker)、[model import](https://docs.ollama.com/import)
- llama.cpp：[repository](https://github.com/ggml-org/llama.cpp)、[server](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md)、[grammars／JSON Schema](https://github.com/ggml-org/llama.cpp/blob/master/grammars/README.md)、[Metal build](https://github.com/ggml-org/llama.cpp/blob/master/docs/build.md#metal-build)
- MLX-LM：[repository](https://github.com/ml-explore/mlx-lm)、[server](https://github.com/ml-explore/mlx-lm/blob/main/mlx_lm/SERVER.md)
- vLLM：[Apple Silicon installation](https://docs.vllm.ai/en/latest/getting_started/installation/cpu/?device=apple)
