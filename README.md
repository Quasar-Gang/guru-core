# guru-core

The backend for coach.ai. A user states a goal; the system merges whatever context it has, asks follow-up questions when something essential is missing, and produces three difficulty variants of an executable plan. Plans export to Google Calendar or Markdown, tasks are checked off day by day, and a plan can be revised when the user falls behind.

Specification: [`guru-core-PRD.md`](guru-core-PRD.md). Implementation plan: [`docs/superpowers/plans/`](docs/superpowers/plans/). Engineering rules: [`CONTRIBUTING.md`](CONTRIBUTING.md).

## Architecture

Three independently deployable services share six packages, one PostgreSQL and one Redis. Services never call each other over HTTP — they communicate through the queue and the shared database.

| Service | Shape | Owns |
|---|---|---|
| API Service | HTTP + worker | Auth, OAuth, every app-facing endpoint, import parsing, export push, job enqueueing |
| Plan Engine | Worker only | Context assembly, readiness evaluation, follow-up questions, plan generation, revisions and diffs |
| Role Model Service | HTTP only | Role model queries, team writes, LLM-backed recommendation |

Every external dependency sits behind a Protocol port (`LLMPort`, `StoragePort`, `QueuePort`, `CachePort`, one `XxxRepo` per table, `SourcePort` / `ParserPort`). Each port has a real implementation and a fake, so **unit and application tests need no Docker**.

## Entry points

One image, six roles — the entrypoint decides which.

```bash
uv run python -m cmd.api_server          # API Service HTTP (8000)
uv run python -m cmd.api_worker          # import.parse / export.push worker
uv run python -m cmd.plan_engine_worker  # plan.generate / continue / revise worker
uv run python -m cmd.role_model_server   # Role Model Service HTTP (8001)
uv run python -m cmd.seed_role_models    # load seeds/role_models/*.yaml
uv run python -m cmd.check_llm           # one smoke call against the configured provider
```

## Getting started

Requires Python 3.12 and [uv](https://docs.astral.sh/uv/). The local PostgreSQL (5432) and Redis (6379) are used directly.

```bash
uv sync
cp .env.example .env                  # adjust as needed
uv run alembic upgrade head           # create the schema
uv run python -m cmd.seed_role_models # load the 12 role models
make check                            # ruff -> mypy --strict -> import-linter -> pytest
make integration                      # integration tests against the local PostgreSQL
```

`docker-compose.yml` brings up an isolated stack; its postgres and redis publish on 5433 / 6380 so they do not collide with the services already running locally.

## Configuration

Everything lives in `config/` and environment variables. Swapping a vendor never touches application code.

| File | Contents |
|---|---|
| `config/llm.yaml` | LLM provider, per-purpose parameters, role model context budgets, retry count |
| `config/readiness_metrics.yaml` | Follow-up metrics (required / domain_probe / helpful) |
| `config/scheduler.yaml` | Minimum gap between tasks, conflict shift limit, slot order |
| `config/difficulty_coefficients.yaml` | Coefficients for the three difficulty variants |
| `config/tag_vocab.yaml` | Role model tag namespaces and controlled values |
| `config/calendar_colors.yaml` | Google Calendar colorId mapping |

### Switching LLM provider

Environment variables only; no code changes:

| Setup | `LLM_ADAPTER` | `LLM_BASE_URL` | `structured_output` |
|---|---|---|---|
| Tests and development | `fake` | — | — |
| Local vLLM | `openai_compat` | `http://localhost:8000/v1` | `guided_json` |
| Local Ollama | `openai_compat` | `http://localhost:11434/v1` | `json_schema` |
| Claude | `anthropic` | — | `tool_use` |

### Switching object storage

The MVP writes to the local filesystem (`LocalFileStorage`). Moving to Cloudflare R2 is a configuration change:

```
STORAGE_BACKEND=r2
R2_ACCOUNT_ID=...
R2_ACCESS_KEY_ID=...
R2_SECRET_ACCESS_KEY=...
R2_BUCKET=...
```

`container.py` is the only assembly point, so no use case changes.

## Language

The codebase is English-only. Files that carry content rather than code — LLM prompts, readiness metrics, role model seeds, LLM fixtures — keep their original language. See [`CONTRIBUTING.md`](CONTRIBUTING.md#language).
