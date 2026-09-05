<div align="center">

# guru-core

**Turn a goal into a plan you can actually execute.**

State what you want to achieve. The system merges whatever context it has, asks
follow-up questions only where something essential is missing, and produces three
difficulty variants of a scheduled plan — exportable to Google Calendar or Markdown,
checked off day by day, and revisable when you fall behind.

[![CI](https://github.com/Quasar-Gang/guru-core/actions/workflows/ci.yml/badge.svg)](https://github.com/Quasar-Gang/guru-core/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.12-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-async-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-4169E1?logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![Redis](https://img.shields.io/badge/Redis-7-DC382D?logo=redis&logoColor=white)](https://redis.io/)
[![mypy](https://img.shields.io/badge/mypy-strict-2A6DB2)](https://mypy-lang.org/)
[![ruff](https://img.shields.io/badge/lint-ruff-D7FF64?logo=ruff&logoColor=black)](https://docs.astral.sh/ruff/)
[![License](https://img.shields.io/badge/license-proprietary-A31515)](LICENSE)

[Specification](guru-core-PRD.md) · [Engineering rules](CONTRIBUTING.md) · [Quick start](#quick-start)

</div>

---

## How it works

<img src="docs/assets/flow-goal-to-plan.svg" alt="Goal to plan: one required input, three optional ones, then readiness check, plan engine, scheduler, three difficulty variants">

**The design decision that matters:** the LLM never does calendar arithmetic. It produces
one *relative* plan template — "a long run on Saturday morning, 45 minutes" — and a
deterministic scheduler turns that into absolute timestamps that avoid your existing
commitments. The three difficulty variants are derived from that one template by
coefficients, not by three separate model calls. So the model is asked for judgement,
never for arithmetic: cheaper, testable, and stable across runs.

## Architecture

Three independently deployable services share six packages, one PostgreSQL and one Redis.
Services never call each other over HTTP — they communicate through the queue and the
shared database.

<img src="docs/assets/architecture.svg" alt="Architecture: three services over a shared queue and database, every external dependency behind a port">

| Service | Shape | Owns |
|---|---|---|
| **API Service** | HTTP + worker | Auth, OAuth, every app-facing endpoint, import parsing, export push, job enqueueing |
| **Plan Engine** | Worker only | Context assembly, readiness evaluation, follow-up questions, plan generation, revisions |
| **Role Model Service** | HTTP only | Role model queries, team writes, LLM-backed recommendation |

### Hexagonal, enforced by tooling

Dependencies point one way only. `import-linter` fails the build on a reverse import, so
the rule cannot rot.

<img src="docs/assets/hexagonal-layers.svg" alt="Hexagonal layers: cmd to container to adapters to application to domain">

Every port has a real implementation **and** a fake, which is why the unit and
application suites need no Docker, no database and no network:

| Port | Real | Fake |
|---|---|---|
| `LLMPort` | `OpenAICompatLLM`, `AnthropicLLM` | `FakeLLM` (fixtures) |
| `StoragePort` | `LocalFileStorage`, `R2Storage` | `InMemoryStorage` |
| `QueuePort` | `ArqQueue` | `InMemoryQueue` |
| `CachePort` | `RedisCache` | `DictCache` |
| `XxxRepo` ×14 | `PgXxxRepo` ×14 | `InMemoryXxxRepo` ×14 |
| `SourcePort` / `ParserPort` | 7 parsers, Google Calendar | `InMemorySource` |

### From goal to calendar

<img src="docs/assets/sequence-goal-to-calendar.svg" alt="Sequence: creating a plan session, one follow-up round, then three generated plans">

Model output is validated twice — Pydantic for shape, then business rules for
sense — and a failure feeds the specific violation back for a retry. If the retries run
out, the plan degrades to a conservative default and says so in `assumptions[]` rather
than shipping something unschedulable.

## Quick start

Requires Python 3.12, [uv](https://docs.astral.sh/uv/), PostgreSQL and Redis.

```bash
uv sync
cp .env.example .env                  # adjust as needed
uv run alembic upgrade head           # create the schema
uv run python -m cmd.seed_role_models # load the 12 role models
make check                            # ruff → mypy --strict → import-linter → pytest
```

Run it, four processes:

```bash
uv run python -m cmd.api_server          # HTTP, port 8000
uv run python -m cmd.api_worker          # import.parse · export.push
uv run python -m cmd.plan_engine_worker  # plan.generate · continue · revise
uv run python -m cmd.role_model_server   # HTTP, port 8001
```

Or the whole stack in containers — **one image, six roles**, the entrypoint decides which:

```bash
docker compose up -d --build
docker compose exec api python -m alembic upgrade head
docker compose exec api python -m cmd.seed_role_models
bash scripts/smoke.sh                 # end-to-end: sign in → plan → tasks → export
```

Compose publishes postgres and redis on 5433 / 6380 so they do not collide with the
services already running on your machine.

## Configuration

Everything lives in `config/` and environment variables. Swapping a vendor never touches
application code.

| File | Controls |
|---|---|
| `config/llm.yaml` | Provider, per-purpose parameters, context budgets, retry count |
| `config/readiness_metrics.yaml` | What must be known before a plan can be generated |
| `config/scheduler.yaml` | Minimum gap between tasks, conflict shift limit, slot order |
| `config/difficulty_coefficients.yaml` | How the three variants are derived |
| `config/tag_vocab.yaml` | Role model tag namespaces and controlled values |
| `config/calendar_colors.yaml` | Google Calendar colour mapping |

<details>
<summary><b>Switching LLM provider</b> — environment variables only</summary>

<br>

Every field in `config/llm.yaml` is an environment variable with a default, so moving
between a laptop and a hosted API never touches the file or any use case.

| Setup | `LLM_ADAPTER` | `LLM_BASE_URL` | `LLM_STRUCTURED_OUTPUT` | `LLM_CONCURRENCY` | `LLM_REASONING_EFFORT` |
|---|---|---|---|---|---|
| Tests and development | `fake` | — | — | — | — |
| xAI Grok *(default)* | `openai_compat` | `https://api.x.ai/v1` | `json_schema` | `0` | `low` |
| Local Ollama | `openai_compat` | `http://127.0.0.1:11434/v1` | `json_schema` | `1` | `none` |
| Local vLLM | `openai_compat` | `http://localhost:8000/v1` | `guided_json` | `1` | *(blank)* |
| Claude | `anthropic` | *(blank)* | `tool_use` | `0` | *(blank)* |

The default model is `grok-4.6` (`LLM_MODEL`), 500K context, reached with an `xai-…` key
in `LLM_API_KEY`. It always reasons, so `none` is rejected — `low` is the cheapest effort
it accepts, and its reasoning tokens are billed on top of `max_tokens`, which caps the
answer only.

Two fields exist because a local runtime and a hosted API want opposite things:

- **`LLM_CONCURRENCY`** caps simultaneous requests per process. A local runtime holds one
  set of weights and one KV cache, so two generations contend for the same memory; `1`
  keeps a laptop predictable. Set `0` for a hosted provider, which has no such limit.
- **`LLM_REASONING_EFFORT`** is only sent when non-empty, because the accepted values are
  provider-specific and Anthropic has no such field. Leave it blank on a provider that
  does not take it — the Anthropic adapter never sends it regardless.

The whole system makes exactly four kinds of LLM call — evaluate readiness, generate a
plan, revise a plan, recommend a role model. Everything else is deterministic code.
The local model baseline and the acceptance gates a replacement must clear are in
[`docs/research/local-llm-evaluation.md`](docs/research/local-llm-evaluation.md).

</details>

<details>
<summary><b>Switching object storage</b> — local filesystem or Cloudflare R2</summary>

<br>

```bash
STORAGE_BACKEND=r2
R2_ACCOUNT_ID=...
R2_ACCESS_KEY_ID=...
R2_SECRET_ACCESS_KEY=...
R2_BUCKET=...
```

`container.py` is the only assembly point, so no use case changes. All three
implementations run the same contract test suite.

</details>

## Testing

```bash
make check          # ruff → mypy --strict → import-linter → pytest, no Docker
make integration    # integration tests against a live PostgreSQL
bash scripts/smoke.sh
```

| Suite | Needs | Runs in CI |
|---|---|---|
| Unit — domain, packages | nothing | ✅ |
| Application — use cases through fakes | nothing | ✅ |
| Integration — Postgres repos | PostgreSQL | ✅ |
| Smoke — end to end over HTTP | the full stack | manual |

Every push runs lint, `mypy --strict`, the import contracts, both test suites and
`alembic check` against a real PostgreSQL — see [`.github/workflows/ci.yml`](.github/workflows/ci.yml).

The heaviest coverage sits on the deterministic core: the scheduler, difficulty
derivation, the revision diff, and the state machines. That is where regressions would
be invisible and expensive.

## Diagrams

All four diagrams are SVGs with an explicit white canvas, so they look the same in
light and dark mode — mermaid's own output is transparent and would otherwise pick up
the reader's page colour.

The first two — the flow and the architecture — are hand-drawn SVGs, because each
carries a layer of meaning a flowchart cannot: the runway bars encode 15/12/10 weeks so
the trade-off between the three plans is visible, and the port boundary is drawn as a
boundary, with the fakes that make it worth having listed underneath. Edit those files
directly.

The other two are generated from `.mmd` sources in [`docs/diagrams/`](docs/diagrams/):

```bash
uv run python scripts/render_diagrams.py   # opens a browser, writes docs/assets/*.svg
```

The generator only rebuilds SVGs whose name matches a `.mmd`, so it leaves the
hand-drawn pair alone.

## Documentation

| Document | What it covers |
|---|---|
| [`docs/api/README.md`](docs/api/README.md) | API guide — the call sequence behind each feature, with runnable examples |
| [`docs/api/openapi.json`](docs/api/openapi.json) · [`.yaml`](docs/api/openapi.yaml) | OpenAPI 3.1 spec, exported from the running app |
| [`docs/db/schema.md`](docs/db/schema.md) | All 14 tables: columns, constraints, ownership, and why each shape was chosen |
| [`docs/research/local-llm-evaluation.md`](docs/research/local-llm-evaluation.md) | Local model selection, licence analysis, and the gates a replacement must clear |
| [`guru-core-PRD.md`](guru-core-PRD.md) | The specification this was built from |

Swagger UI and ReDoc are served live at `/docs` and `/redoc`. Regenerate the exported
spec after changing a route:

```bash
uv run python scripts/export_openapi.py
```

## Repository layout

```
cmd/            six entry points, ≤30 lines each, zero business logic
packages/       llm · importers · repo · storage · queue · cache · config · logging
services/
  api/          domain · application · adapters · container.py
  plan_engine/  domain · application · adapters · container.py
  role_model/   domain · application · adapters · container.py
config/         yaml the code reads, never hard-coded
seeds/          role model starting samples
migrations/     alembic
docs/           api reference · db schema · research · diagrams
tests/          unit · application · integration · fixtures
```

## License

Proprietary. Copyright (c) 2026 Quasar-Gang, all rights reserved — see
[`LICENSE`](LICENSE). No licence to use, copy, modify or distribute this software
is granted without written permission.
