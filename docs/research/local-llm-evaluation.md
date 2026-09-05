# Local model selection for guru-core

> Researched 2026-09-05, revised 2026-09-06 for the three-station design.
> Target hardware: MacBook Pro (Apple M4, 10-core CPU, 10-core GPU, 24 GB unified memory).
> Evidence: model cards, technical reports, official documentation and source repositories.
> Capability numbers are vendor self-reported and are **not** the same as guru-core results.

## 1 · Conclusion

For a local demo:

- **Runtime: Ollama**, natively on macOS, not in Docker
- **Model: `qwen3.5:9b`** (6.6 GB on Ollama; digest `6488c96fa5fa` when resolved here)
- **Explicit configuration:** 16,384 context, low temperature, `reasoning_effort: none`,
  concurrency 1
- **Fallback: `qwen3:8b`** (Ollama Q4_K_M, 5.2 GB)

`qwen3.5:9b` is chosen not on one general benchmark but on the intersection this product
needs: a 9B model leaves real headroom in 24 GB of unified memory, native 262K context, 201
languages and dialects, strong instruction following, Apache-2.0 weights, an official 6.6 GB
Ollama artifact, and an OpenAI-compatible endpoint that already supports `response_format`
JSON Schema and reasoning control.
[Qwen3.5-9B model card](https://huggingface.co/Qwen/Qwen3.5-9B) ·
[Ollama Qwen3.5](https://ollama.com/library/qwen3.5) ·
[Ollama OpenAI compatibility](https://docs.ollama.com/api/openai-compatibility)

This is **an engineering choice pending a full guru-core evaluation set**, not a proven
quality result. The smoke test established that 100% Metal GPU offload, a 16,384 context and
the OpenAI-compatible JSON-Schema path all work. It also produced, on the first attempt, an
answer that satisfied the schema and misplaced the semantics — and on the second, one that
broke an invariant while remaining well-formed. That is the whole argument for validating
twice and retrying with the violation fed back.

## 2 · What the model actually has to do

The model work here is not open-ended chat. It is five constrained, checkable
transformations under three purposes:

| Call | Purpose | Frequency | Max output | The hard part |
|---|---|---|---:|---|
| `build_profile` | `analyze` | once per upload batch | 4,000 | Classify every event into a dimension and hand back the reference it was given |
| `create_reports` | `analyze` | once per run | 4,000 | Say what the numbers mean without contradicting or restating them |
| `score_role_models` | `verdict` | once per run | 6,000 | Every shape scored, exactly five cited evidence items each, at least one for and one against |
| `build_plan` | `generate` | once per hypothesis | 4,000 | A nested milestone tree with relative week ranges, and no dates at all |
| `narrate_reconciliation` | `analyze` | once per review | 4,000 | Put a computed comparison into words and end on a question |

So the priorities are, in order:

1. **Schema-constrained JSON and instruction-following stability**, not knowledge scores.
2. **Long, mixed-language context** — uploaded documents are whatever the user's are.
3. **16K of real context stable in 24 GB**, with 4K reserved for output and room left for
   the application and the OS.
4. **Low latency with reasoning that can be turned off.** Four of the five calls are
   extraction, classification and constrained generation; a long chain of thought on every
   request is not worth paying for.
5. **An OpenAI-compatible API**, so `OpenAICompatLLM` stays as it is.
6. **A reproducible artifact and an acceptable licence.**

The architecture is already generous to a small model: it never asks for arithmetic. Placing
tasks on dates, applying the quota, diffing schedules and counting what was done are all
deterministic code. That buys more reliability than a larger model would.

## 3 · "Open source" and "open weights" are not the same thing

The OSI's Open Source AI Definition 1.0 requires four freedoms — use, study, modify, share —
and the preferred form for modification has to include enough information about the training
data, the complete training, data-processing and inference code, and the parameters.
Downloadable weights, even Apache-2.0 ones, do not by themselves make a model OSAID
compliant. [OSAID 1.0](https://opensource.org/ai/open-source-ai-definition) ·
[OSI FAQ](https://opensource.org/ai/faq)

This document uses three labels:

- **Fully open / OSAID track** — the whole model flow is published: data, training code,
  recipes, checkpoints, evaluations.
- **Permissively licensed open weights** — weights under Apache-2.0 or MIT; commercial use
  and derivatives are usually easy, but the full model flow is not established.
- **Community / custom terms open weights** — downloadable, with use policies, distribution,
  naming or scale conditions. Not OSI open source.

| Model | Weights / terms | Label | Note |
|---|---|---|---|
| Qwen3 / Qwen3.5 | Apache-2.0 | Permissive open weights | Permissive terms; the card does not publish everything needed to rebuild an equivalent system |
| Mistral Small 3.1 | Apache-2.0 | Permissive open weights | Mistral calls it open source; vendor wording is not an OSAID certification |
| DeepSeek-R1 Distill Qwen | MIT, base Qwen2.5 Apache-2.0 | Permissive open weights | Report and weights are public; the 800K distillation set is not fully reconstructible |
| gpt-oss | Apache-2.0 plus a usage policy | Permissive open weights | OpenAI itself calls it **open-weight**, not a fully open model flow |
| Llama 3.x | Community License + AUP | Custom-licence open weights; **not OSI** | Use policy, a 700M MAU condition, distribution and naming obligations |
| Gemma 3 | Gemma Terms + Prohibited Use Policy | Custom terms; **not OSI** | Use and distribution constrained by prohibited-use and notice clauses |
| Olmo 3 | Apache-2.0; public data, code, recipes, checkpoints | Fully open track | Ai2 publishes the whole model flow — the best "genuinely open" comparison |

Sources: [Qwen3-8B](https://huggingface.co/Qwen/Qwen3-8B) ·
[Qwen3.5-9B LICENSE](https://huggingface.co/Qwen/Qwen3.5-9B/blob/main/LICENSE) ·
[Mistral Small 3.1](https://huggingface.co/mistralai/Mistral-Small-3.1-24B-Instruct-2503) ·
[DeepSeek-R1 licence](https://github.com/deepseek-ai/DeepSeek-R1#7-license) ·
[gpt-oss model card](https://openai.com/index/gpt-oss-model-card/) ·
[Llama 3.1 licence](https://github.com/meta-llama/llama-models/blob/main/models/llama3_1/LICENSE) ·
[Gemma Terms](https://ai.google.dev/gemma/terms) ·
[Olmo 3 model flow](https://allenai.org/blog/olmo3) ·
[OSI on Llama 3.x](https://opensource.org/blog/metas-llama-license-is-still-not-open-source)

The practical consequence: say "locally deployed model, preferring permissively licensed
open weights" rather than "local open source model", and record the weight licence, use
policy and attribution obligations on a release checklist. A runtime's own licence covers
nothing about the weights it downloads —
[Ollama](https://github.com/ollama/ollama/blob/main/LICENSE) and
[llama.cpp](https://github.com/ggml-org/llama.cpp/blob/master/LICENSE) are both MIT, and
that says nothing about the model.

## 4 · The candidates

File sizes are Ollama's default artifact — weights on disk, not runtime memory. Running also
needs the KV cache, compute buffers and the runtime itself, and a larger context costs more.

| Candidate | Parameters | Context | Ollama artifact | Languages | Licence | On a 24 GB M4 |
|---|---|---:|---:|---|---|---|
| **Qwen3.5 9B** | 9B dense hybrid attention | 262K native | **6.6 GB** | 201 | Apache-2.0 | **First choice; 16K leaves real headroom** |
| Qwen3 8B | 8.2B dense | 32K native, 131K with YaRN | 5.2 GB | 100+ | Apache-2.0 | **Conservative fallback** |
| Gemma 3 12B IT | 12B dense, multimodal | 128K, 8K output | 8.1 GB | 140+ | Gemma custom | Runs; terms are worse and vision is unused |
| Llama 3.1 8B Instruct | 8B dense | 128K | 4.9 GB | 8 listed | Llama custom | Runs; neither language coverage nor licence favours it |
| Mistral Small 3.1 24B | 24B dense | 128K | — | 24 | Apache-2.0 | **Excluded; the vendor states 32 GB Macs** |
| DeepSeek-R1 Distill Qwen 7B | Qwen2.5-Math 7B distill | 128K | 4.7 GB | strong reasoning | MIT | Runs; wrong shape for short constrained generation |
| gpt-oss 20B | 21B total / 3.6B active MoE | 128K | 14 GB | mostly English | Apache-2.0 | Runs, little headroom; a second-round experiment |
| Olmo 3 7B Instruct | 7B dense | 64K | 4.5 GB | English-leaning | Fully open | The genuinely open alternative; must be evaluated on the real task set |

### Qwen3.5 9B — recommended

Nine billion parameters, 32 layers, hybrid Gated DeltaNet and full attention, 262,144 native
context, 201 languages claimed. The vendor's IFEval 88.9 and IFBench 69.0 are a reason to
shortlist it, not a substitute for a product evaluation.
[Model overview](https://huggingface.co/Qwen/Qwen3.5-9B#model-overview)

In its favour: a 6.6 GB artifact leaves far more KV cache and application room than a
14-24 GB candidate; instruction following and agent behaviour are exactly what the five
prompts need; 16K is a small fraction of native context, so no RoPE extension is involved;
and the artifact is official rather than an unvetted third-party GGUF.

Against it: Qwen3.5 reasons by default, and unlike Qwen3 there is no `/think` soft switch —
the official examples disable it with `enable_thinking: false`.
[Non-thinking mode](https://huggingface.co/Qwen/Qwen3.5-9B#instruct-or-non-thinking-mode)
Through Ollama's OpenAI path that means sending `reasoning_effort: "none"` and verifying the
reasoning does not leak into the JSON. The architecture is also newer than Qwen3's, so pin
the Ollama version and the model digest rather than a mutable tag.

### Qwen3 8B — the fallback

8.2B dense, 32,768 native context, extensible to 131,072 with YaRN, an explicit
thinking/non-thinking switch, 100+ languages. 16K needs no YaRN, and the vendor warns that
static YaRN can hurt short-context behaviour.
[Model card](https://huggingface.co/Qwen/Qwen3-8B) ·
[Qwen3 release](https://qwenlm.github.io/blog/qwen3/)

Older, but with mature runtime support and a very light 5.2 GB artifact. It is the painless
fallback if Qwen3.5 misses a gate — not a reasoning distill.

### Gemma 3 12B IT

128K input, 8,192 output, 140+ languages, image input, 8.1 GB at Q4_K_M.
[Model card](https://ai.google.dev/gemma/docs/core/model_card_3) ·
[Ollama tags](https://ollama.com/library/gemma3/tags)

Not first choice: the MVP needs no vision, the Gemma Terms carry a prohibited-use policy and
distribution obligations, and the artifact is larger. A reasonable second non-reasoning
baseline.

### Llama 3.x

The candidate that fits this hardware is Llama 3.1 8B Instruct (128K, 4.9 GB), not 70B or
405B. [Meta's model table](https://github.com/meta-llama/llama-models#llama-models)

Mature ecosystem, but the Community License carries an acceptable-use policy, a 700M MAU
condition and `Built with Llama` naming obligations, and the release lists eight supported
languages. Neither the licence nor the coverage argues for it over Qwen.
[Licence](https://github.com/meta-llama/llama-models/blob/main/models/llama3_1/LICENSE)

### Mistral Small 3.x

24B, 128K, 24 languages, Apache-2.0, positioned for function calling and local sensitive
data. The vendor explicitly states a quantised deployment suits a single RTX 4090 or a
**32 GB RAM MacBook**, which is decisive evidence against it here.
[Release](https://mistral.ai/news/mistral-small-3-1/) ·
[Model card](https://huggingface.co/mistralai/Mistral-Small-3.1-24B-Instruct-2503)

3.1 is now retired in favour of Small 4, which is 119B total / ~6B active and needs multiple
H100/H200 or B200 cards — plainly not a local demo.
[Lifecycle](https://docs.mistral.ai/models/mistral-small-3-1-25-03) ·
[Small 4](https://mistral.ai/news/mistral-small-4/)

### DeepSeek-R1 distilled

The runnable version is `DeepSeek-R1-Distill-Qwen-7B` (4.7 GB), fine-tuned from
Qwen2.5-Math-7B on 800K R1 samples and released under MIT. Its advantages concentrate in
maths, code and long reasoning.
[Repository](https://github.com/deepseek-ai/DeepSeek-R1) ·
[Technical report](https://arxiv.org/abs/2501.12948)

Wrong default here: the vendor recommends avoiding a system prompt and a temperature of
0.5-0.7, and it tends toward long chains of thought — all in tension with a prompt registry,
low-temperature JSON schema work and a 4,000-token output budget. Keep it as an experiment
for the harder judgement calls, not as the general instruct model.
[Usage recommendations](https://github.com/deepseek-ai/DeepSeek-R1#usage-recommendations)

### gpt-oss 20B

21B total / 3.6B active MoE, 128K context, native MXFP4, said to run in 16 GB, with function
calling, structured outputs and adjustable reasoning effort. The Ollama artifact is 14 GB.
[Introduction](https://openai.com/index/introducing-gpt-oss/) ·
[Model card](https://huggingface.co/openai/gpt-oss-20b)

An attractive second-round candidate on schema ability, but 14 GB of weights plus a 16K KV
cache, Ollama, PostgreSQL, Redis and the services leaves little room, the pretraining data is
described as mostly English, and it requires the Harmony format — which Ollama handles, at
the price of provider-specific behaviour.

### Olmo 3 7B Instruct — the genuinely open option

Ai2 publishes the pretraining, midtraining, long-context and post-training data, the
training scripts, the recipes, the checkpoints and the evaluations. 7B Instruct is
Apache-2.0, 4.5 GB, 64K context, with instruction following and function calling.
[Release](https://allenai.org/blog/olmo3) ·
[Training source](https://github.com/allenai/OLMo-core/tree/main/src/scripts/official/OLMo3) ·
[Model card](https://huggingface.co/allenai/Olmo-3-7B-Instruct)

If "genuinely fully open" is a hard requirement, evaluate it first. Openness is not a
substitute for passing the task set, though.

## 5 · Runtimes

| Runtime | Apple M4 | OpenAI-compatible | Schema constraint | Maintenance | Fit |
|---|---|---|---|---|---|
| **Ollama** | Native Metal | Chat, Completions, Models, Embeddings | `response_format` JSON Schema | Lowest | **Demo choice** |
| llama.cpp | First-class Apple Silicon | `llama-server`, no full-spec promise | JSON Schema → GBNF | Medium-high | Best for reproducible benchmarks |
| MLX-LM | Native Apple Silicon | "Intended to be similar" | Not a server contract | Medium | Model research and LoRA |
| vLLM | Experimental macOS CPU, community Metal plugin | Strong | Strong guided output | Highest locally | Linux GPU production |

### Why Ollama

Native macOS and Apple GPU support, model management, a REST API and an OpenAI-compatible
endpoint; structured outputs take a Pydantic `model_json_schema()` directly, and the vendor
recommends a low temperature. [macOS](https://docs.ollama.com/macos) ·
[Structured outputs](https://docs.ollama.com/capabilities/structured-outputs) ·
[OpenAI compatibility](https://docs.ollama.com/api/openai-compatibility)

**Do not put the Ollama server in Docker on a Mac.** Docker Desktop for macOS has no GPU
passthrough, so containerising it only loses Apple GPU acceleration. Run it on the host and
point the services at `host.docker.internal:11434`.
[Docker](https://docs.ollama.com/docker) · [FAQ](https://docs.ollama.com/faq)

### Where llama.cpp fits

Metal, GGUF, many quantisations, hybrid CPU/GPU offload and an OpenAI-compatible
`llama-server`. Its schema constraint compiles JSON Schema into a GBNF grammar, which makes
it the right tool for a strict benchmark and for chasing grammar behaviour.
[README](https://github.com/ggml-org/llama.cpp) ·
[Server](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md) ·
[Grammars](https://github.com/ggml-org/llama.cpp/blob/master/grammars/README.md)

The price is pinning the GGUF, chat template, context, batch size, Metal offload and server
flags yourself — unnecessary for a first one-command demo.

### MLX-LM and vLLM

MLX-LM is built for Apple Silicon generation, quantisation and fine-tuning, but its server
is only "intended to be similar" to the OpenAI API and is explicitly not recommended for
production. [README](https://github.com/ml-explore/mlx-lm) ·
[Server](https://github.com/ml-explore/mlx-lm/blob/main/mlx_lm/SERVER.md)

vLLM is a sound Linux GPU production choice, but on Apple Silicon its CPU support is
experimental and GPU needs a community Metal plugin.
[Apple Silicon installation](https://docs.vllm.ai/en/latest/getting_started/installation/cpu/?device=apple)

## 6 · What fits in 24 GB

Measured on the machine: Apple M4, 10 CPU cores, 10 GPU cores, 24 GB unified memory, Metal 3.
The constraint is shared memory and context, not disk.

- Keep the demo model at a **6-9 GB Q4 artifact**. Weights, a 16K KV cache, the runtime and
  the application services then still leave sensible headroom.
- 14 GB `gpt-oss:20b` is testable; do not keep two large models resident.
- 17-20 GB artifacts (Gemma 3 27B, Qwen3 30B-A3B, DeepSeek 32B) may load without running
  stably at 16K context and 4K generation alongside the full stack.
- Mistral Small 3.1's own 32 GB guidance is explicit exclusion evidence.
- Start with LLM concurrency **1**. Measure single-request correctness and memory first.

### Set the context explicitly

Ollama picks a context from available VRAM: 4K below 24 GiB, 32K between 24 and 48 GiB — and
24 GB sits exactly on that boundary, so the automatic choice cannot be trusted. Set
`OLLAMA_CONTEXT_LENGTH=16384` at startup and confirm with `ollama ps`.
[Context length](https://docs.ollama.com/context-length)

A model supporting 128K does not mean opening 128K locally. Input and output share the
allocated context: at 16,384 with 4,000 reserved for output, the assembled prompt has a hard
ceiling around 12K, minus chat-template tokens. Truncate deterministically before that,
rather than letting the runtime silently cut.

### The measured smoke test

2026-09-05, Ollama 0.33.2, `qwen3.5:9b` digest `6488c96fa5fa`,
`OLLAMA_CONTEXT_LENGTH=16384`, `reasoning_effort: none`, over
`/v1/chat/completions`:

| | Result |
|---|---|
| Model load | `ollama ps`: 5.9 GB, 100% GPU, context 16,384 |
| Cold first round | 25.40 s (96 input + 272 output tokens) |
| Warm rounds after tightening the prompt | 17.08 s, 14.01 s |
| Final decode rate | about 15.9 tokens/s |
| Transport and JSON Schema | all three rounds parsed and matched the schema |
| Business rules | round one misplaced a field; round two broke an invariant while staying well-formed; round three passed once the invariant was stated explicitly |

That sample proves the local path works and that the validator is not optional. One prompt,
a warm cache and a short input say nothing about production latency or quality — section 8
is what decides that.

## 7 · Consequences for the code

What the architecture already gets right:

- `LLMPort` isolates use cases from any vendor SDK; model, temperature and token limits stay
  in adapter configuration.
- Local and hosted share one OpenAI-compatible adapter, so switching is small.
- Provider-side schema constraint is followed by Pydantic **and** business-rule validation,
  with violations fed back, bounded retries and a stated fallback. Defence in depth.
- The deterministic core never reaches a model at all, which is the largest single reduction
  in what a small model has to get right.
- Per-call observability — prompt, version, model, tokens, latency, attempts, degraded — is
  enough to make the next selection empirical rather than argued.

What still needs deciding or finishing:

1. **Pin the baseline**: `qwen3.5:9b` on Ollama, with the Ollama version, tag and digest all
   pinned.
2. **Set the context explicitly** and verify it after startup.
3. **Turn reasoning off** for all three purposes by default. If one later warrants it, that
   belongs in `params` per purpose, not in a prompt.
4. **Be exact about the schema payload**: Ollama's OpenAI path wants
   `response_format: {type: "json_schema", json_schema: …}`. An adapter contract test should
   assert the wire payload, not the intent.
5. **Map the output token field**: `max_output_tokens` is our name; Chat Completions calls it
   `max_tokens`.
6. **Define a truncation budget** across profile, documents, calendar, catalogue, schema and
   the output reserve. `budgets` currently caps the catalogue only, which does not guarantee
   the whole prompt fits.
7. **Concurrency and backpressure**: start at 1, and make sure a 240-second timeout plus
   queue retries cannot stack several generations on one set of weights.
8. **A real smoke test**: `cmd/check_llm.py` should not only prove the model answers. Send
   each of the five production schemas and check JSON, Pydantic, the business rules and the
   retry telemetry.
9. **Runtime compatibility is not model compatibility.** Each new model needs its chat
   template, reasoning separation, schema behaviour and context verified. A working
   `/v1/chat/completions` proves none of that.
10. **Licence language**: classify precisely, and record weights licence, use policy,
    attribution and derivative conditions on the release checklist.

## 8 · The acceptance matrix

Do not pick a product model on MMLU or an arena score. Build a fixed, de-identified guru-core
evaluation set — at least 30-50 cases per prompt, covering mixed languages, long documents,
calendar conflicts, missing information and hostile document content.

| Metric | Demo gate | How |
|---|---:|---|
| JSON parse success | ≥ 99% within 3 retries | per schema, not one average |
| Pydantic schema success | ≥ 98% first try; ≥ 99% after retries | record missing fields, wrong types, extra fields |
| Business-rule success | ≥ 95% first try; ≥ 99% after retries or fallback | five evidence items, both stances, citations resolve, milestone keys unique, task weeks in range |
| Citation integrity | **0** items citing a dimension with no report | set membership, checked in `verdict_violations` |
| Readability of the note | human ≥ 4/5 | specific, actionable, no grading language |
| 16K context stability | 100%, no OOM or truncation | longest prompt plus 4K reserve, 20 consecutive runs |
| Latency | measure a baseline, then set an SLO | prefill, time to first token, decode, total |
| Fallback rate | < 1% | split by `prompt_name` and model version |

Compare at least `qwen3.5:9b`, `qwen3:8b` and `olmo-3:7b-instruct`; add `gpt-oss:20b` if the
memory measurements leave room. Change model only when Qwen3.5 misses a gate, and change it
on that evidence rather than on someone else's benchmark.

## 9 · Sources

**Models and licences** —
[Qwen3 release](https://qwenlm.github.io/blog/qwen3/) ·
[Qwen3-8B](https://huggingface.co/Qwen/Qwen3-8B) ·
[Qwen3.5-9B](https://huggingface.co/Qwen/Qwen3.5-9B) ·
[Qwen3.5 LICENSE](https://huggingface.co/Qwen/Qwen3.5-9B/blob/main/LICENSE) ·
[Gemma 3 model card](https://ai.google.dev/gemma/docs/core/model_card_3) ·
[Gemma Terms](https://ai.google.dev/gemma/terms) ·
[Gemma Prohibited Use Policy](https://ai.google.dev/gemma/prohibited_use_policy) ·
[Llama model table](https://github.com/meta-llama/llama-models#llama-models) ·
[Llama 3.1 release](https://ai.meta.com/blog/meta-llama-3-1/) ·
[Llama 3.1 licence](https://github.com/meta-llama/llama-models/blob/main/models/llama3_1/LICENSE) ·
[Mistral Small 3.1](https://mistral.ai/news/mistral-small-3-1/) ·
[Mistral Small 4](https://mistral.ai/news/mistral-small-4/) ·
[DeepSeek-R1](https://github.com/deepseek-ai/DeepSeek-R1) ·
[DeepSeek-R1 paper](https://arxiv.org/abs/2501.12948) ·
[gpt-oss](https://openai.com/index/introducing-gpt-oss/) ·
[gpt-oss model card](https://openai.com/index/gpt-oss-model-card/) ·
[gpt-oss-20b weights](https://huggingface.co/openai/gpt-oss-20b) ·
[Olmo 3](https://allenai.org/blog/olmo3) ·
[Olmo 3 training source](https://github.com/allenai/OLMo-core/tree/main/src/scripts/official/OLMo3) ·
[Olmo 3 7B Instruct](https://huggingface.co/allenai/Olmo-3-7B-Instruct) ·
[OSAID 1.0](https://opensource.org/ai/open-source-ai-definition) ·
[OSAID FAQ](https://opensource.org/ai/faq) ·
[OSI on Llama](https://opensource.org/blog/metas-llama-license-is-still-not-open-source)

**Runtimes** —
[Ollama](https://github.com/ollama/ollama) ·
[macOS](https://docs.ollama.com/macos) ·
[OpenAI compatibility](https://docs.ollama.com/api/openai-compatibility) ·
[Structured outputs](https://docs.ollama.com/capabilities/structured-outputs) ·
[Context length](https://docs.ollama.com/context-length) ·
[Docker](https://docs.ollama.com/docker) ·
[llama.cpp](https://github.com/ggml-org/llama.cpp) ·
[llama-server](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md) ·
[Grammars](https://github.com/ggml-org/llama.cpp/blob/master/grammars/README.md) ·
[MLX-LM](https://github.com/ml-explore/mlx-lm) ·
[MLX-LM server](https://github.com/ml-explore/mlx-lm/blob/main/mlx_lm/SERVER.md) ·
[vLLM on Apple Silicon](https://docs.vllm.ai/en/latest/getting_started/installation/cpu/?device=apple)
