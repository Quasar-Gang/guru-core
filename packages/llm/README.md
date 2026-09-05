# packages/llm

## What it owns

Collapsing "call a large language model" into a single interface: the caller supplies a prompt name,
a context dict, the Pydantic schema of the output and the purpose (`Purpose`), and gets back a
validated model instance. The package covers:

- **Configuration**: the Pydantic model for `config/llm.yaml` (`LLMConfig`) and its loader
  `load_llm_config()`. The configuration holds **a single provider**, not a list of them; switching
  model or service is a matter of environment variables (`LLM_ADAPTER`, `LLM_BASE_URL`, `LLM_MODEL`,
  `LLM_API_KEY`, `LLM_MAX_CONTEXT`). The per-purpose `temperature` / `max_output_tokens` and the
  role model context budgets (`budgets`) live in the same file, read through `params_for(purpose)`
  and `budget_for(purpose)`.
- **Prompt registry**: `PromptRegistry(directory)` loads `.md` templates from a directory. A template
  is YAML frontmatter (which must at least carry `version`) followed by a `# SYSTEM` and a `# USER`
  section; each section is rendered against the context with jinja2 (`StrictUndefined`), producing a
  `RenderedPrompt`. `version(name)` returns just the template version, for observability and cache keys.
- **Adapters**: `OpenAICompatLLM` for any OpenAI-compatible endpoint (vLLM, Ollama, LM Studio,
  SGLang, TGI) with `guided_json` / `json_schema` / `tool_use` / `prompt` structured-output modes,
  `AnthropicLLM` for the Claude API (schema enforced via tool use), and `FakeLLM` for development
  and tests. `build_llm(config, prompts, observer, fixtures_dir=None)` picks one from the
  configuration.
- **`FakeLLM`**: the default in development and tests. It answers from `fixtures_dir/{prompt_name}.json`,
  with `overrides[prompt_name]` taking precedence, and raises `LLMError("no fixture for ...")` when
  neither exists. Every call is recorded in `calls: list[tuple[prompt_name, Purpose, context]]` for
  tests to assert on.
- **Reliability chain and observability**: `complete_validated(...)` runs the
  business rules over the model output, feeds any violations back into the next attempt, and either
  degrades to a `fallback` or raises `LLMValidationExhausted` once attempts run out. Each adapter
  reports an `LlmCallLog` to an `LlmObserver`; `NullObserver` just writes a structured log line.

## The ports it exposes

The names listed in `packages.llm.__all__`:

- `LLMPort` (Protocol): `async complete(prompt_name, context, output_schema, purpose) -> OutputT`
- `Purpose` (StrEnum): `evaluate` / `generate` / `revise` / `recommend`
- Error types: `LLMError` (base), `LLMSchemaError` (the response failed Pydantic validation),
  `LLMTransportError` (network or HTTP layer), `LLMValidationExhausted` (retries exhausted, no fallback)
- Configuration: `LLMConfig`, `ProviderConfig`, `PurposeParams`, `RetryConfig`, `load_llm_config`
- Prompts: `PromptRegistry`, `RenderedPrompt`
- Validation: `BusinessRule`, `ValidationOutcome`, `complete_validated`
- Observability: `LlmCallLog`, `LlmObserver`, `NullObserver`
- Implementations: `FakeLLM`, `OpenAICompatLLM`, `AnthropicLLM`, `build_llm`

Every other module (`ports.py`, `config.py`, `prompts.py`, `fake.py`, `openai_compat.py`,
`anthropic_llm.py`, `validation.py`, `observability.py`, `factory.py`) is private — always import
from `packages.llm`.

## What it does not do

- It does not define business rules (the Scheduler's `pacing` limits, revision strategy constraints
  and so on). It validates the schema and runs whatever rules the caller passes in; whether the
  content makes sense is a domain decision.
- It does not design prompt content. The templates under `prompts/` are data owned by the product,
  not code this package reasons about.
- It does not count tokens, track cost, cache or rate limit.
- It does not decide which context to assemble (role model rendering, session summaries); callers
  build the dict before calling in.
- It does not persist the `LlmCallLog`; writing it to the database is an observer supplied by the
  service (see `packages/repo`).
