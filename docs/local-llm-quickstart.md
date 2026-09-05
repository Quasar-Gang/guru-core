# Running guru-core against a local model

The local baseline is **Ollama + `qwen3.5:9b` (Q4_K_M)**. The tag is about 6.6 GB, which
suits an Apple M4 with 24 GB of unified memory; the script pins the context at 16K so
guru-core, PostgreSQL and Redis still have room.

The full candidate comparison, licence analysis and acceptance gates are in
[`research/local-llm-evaluation.md`](research/local-llm-evaluation.md).

## One command

From the repository root:

```bash
./scripts/local-llm.sh demo
```

It installs Ollama through Homebrew if it is missing, starts a service bound to
`127.0.0.1:11434` only, pulls `qwen3.5:9b`, and runs a JSON-Schema smoke test through
`/v1/chat/completions`.

The first run downloads 6.6 GB; later runs reuse the cache. On success it prints
`PASS: structured output is valid`. The digest resolved on the machine this was written on
is `6488c96fa5fa` — check it with `ollama list` before a real demo, because a mutable tag
can drift underneath you.

## Pointing guru-core at it

`config/llm.yaml` defaults to the hosted baseline (xAI `grok-4.6`). Switching to local needs
environment variables only; the file does not change:

```bash
export LLM_ADAPTER=openai_compat
export LLM_BASE_URL=http://127.0.0.1:11434/v1
export LLM_API_KEY=ollama          # the client requires one; Ollama ignores it
export LLM_MODEL=qwen3.5:9b
export LLM_MAX_CONTEXT=16384
# One set of weights and one KV cache, so serialised requests stay predictable.
export LLM_CONCURRENCY=1
# Ollama accepts "none"; hosted grok-4.6 always reasons and rejects it, which is why
# the default in config/llm.yaml is "low".
export LLM_REASONING_EFFORT=none
```

`json_schema` is the right structured-output mode here, because Ollama's OpenAI-compatible
`/v1/chat/completions` supports `response_format`. guru-core still runs its own Pydantic
validation, business rules and retries on top: a provider constraint is not a defence in
depth, it is one layer of it.

If the services run in Docker while Ollama stays on the host, use
`http://host.docker.internal:11434/v1`. Do not containerise Ollama on a Mac — Docker Desktop
for macOS has no GPU passthrough, so the container simply loses Apple GPU acceleration.

## Day to day

```bash
./scripts/local-llm.sh status   # the service, and what has been pulled
./scripts/local-llm.sh smoke    # re-run the schema tests
./scripts/local-llm.sh logs     # the log of the server this script started
./scripts/local-llm.sh stop     # stop only the server this script started
```

A lighter model for fast iteration:

```bash
LLM_MODEL=qwen3.5:4b ./scripts/local-llm.sh demo
```

A 27B Q4 model is not a sensible default on a 24 GB machine: about 18 GB of weights, plus
the KV cache, Ollama and the application services, leaves too little headroom, and
time-to-first-token suffers.

## When it goes wrong

| Symptom | Fix |
|---|---|
| `address already in use` | An Ollama server is already running; the script reuses a healthy one. Quit it from the Ollama app if it is wedged. |
| Smoke test says `model not found` | `./scripts/local-llm.sh pull` |
| Memory pressure | Drop `LLM_MAX_CONTEXT` to `8192`, or switch to `qwen3.5:4b`. |
| Schema validation fails intermittently | Check you are not on an `-mlx` tag; this setup pins GGUF `Q4_K_M`. Keep the application's three correction retries. |

The server is for local development. Leave `OLLAMA_HOST` on loopback — Ollama puts no
authentication in front of that endpoint.

## Primary sources

- [Qwen3.5-9B model card](https://huggingface.co/Qwen/Qwen3.5-9B)
- [Ollama `qwen3.5:9b`](https://ollama.com/library/qwen3.5:9b)
- [Ollama OpenAI compatibility](https://docs.ollama.com/api/openai-compatibility)
- [Ollama structured outputs](https://docs.ollama.com/capabilities/structured-outputs)
- [Ollama on macOS](https://docs.ollama.com/macos)
