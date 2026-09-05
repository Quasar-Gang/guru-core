# Working on guru-core

Internal engineering handbook. guru-core is proprietary — see [`LICENSE`](LICENSE);
this document is for people already working on it, not an invitation to contribute.

## Local infrastructure

| Component | Address | Notes |
|---|---|---|
| PostgreSQL 15 | `127.0.0.1:5432` | `postgres` / `postgres`, database `guru_core` |
| Redis 7 | `127.0.0.1:6379` | Queue and cache |
| Object storage | `./.data/storage` | `LocalFileStorage` for the MVP; `STORAGE_BACKEND=r2` switches to Cloudflare R2 |
| LLM | `LLM_ADAPTER=fake` | Development and tests read fixtures from `tests/fixtures/llm/` |

## Commands

```bash
uv sync                       # install dependencies
make check                    # ruff -> mypy --strict -> import-linter -> pytest (no Docker)
make fmt                      # format and autofix
make integration              # integration tests against the local PostgreSQL
uv run alembic upgrade head   # apply migrations
uv run alembic check          # verify models and migrations agree
uv run python -m cmd.api_server            # API Service HTTP (8000)
uv run python -m cmd.api_worker            # import.parse / export.push worker
uv run python -m cmd.plan_engine_worker    # plan.generate / continue / revise worker
uv run python -m cmd.role_model_server     # Role Model Service HTTP (8001)
uv run python -m cmd.seed_role_models      # load seeds/role_models/*.yaml
uv run python -m cmd.check_llm             # one smoke call against the configured provider
```

## Language

The codebase is **English-only**: identifiers, comments, docstrings, log and exception messages, test names, Markdown docs and YAML comments. The only exceptions are files that carry *content* rather than code, and they keep their original language:

- `packages/llm/prompts/*.md` — read by the LLM.
- `config/readiness_metrics.yaml` — its text is rendered into the evaluate prompt.
- `seeds/role_models/*.yaml` — role model content is rendered into prompts.
- `tests/fixtures/llm/*.json` — simulated LLM output.
- `tests/fixtures/importers/sample.*` — simulated user uploads, deliberately non-ASCII so encoding bugs surface.
- End-user product strings whose exact format the PRD fixes: the Markdown export headings (PRD 4.3.5) and the trait pacing sentence (PRD 12.6).
- `guru-core-PRD.md` — the source specification, never edited.

## Engineering discipline

The 17 rules below come from PRD section 9. CI enforces the ones a tool can check.

### Boundaries — enforced by tooling, not by discipline

1. Dependencies may only point `adapters -> application -> domain`. A reverse import fails CI (`import-linter` layers contract).
2. Services must not import each other. They communicate only through `packages/` or the queue; `from services.api import ...` inside `services/plan_engine` is a violation.
2b. `cmd/` may only import each service's `container.py` and runtime helpers from `packages/`, never a use case or a domain module; any business branching inside `cmd/` is a violation.
3. Each shared package exports only what its `__init__.py` lists in `__all__`; everything else is private.
4. Exactly one service may write to a given table; the rest read only. The owner is recorded in the model's docstring (see PRD 4.2).

### Abstraction — every store and every external system is a port

5. The following are always defined as a `Protocol`, with implementations under `adapters`: `LLMPort`, `StoragePort`, `QueuePort`, `CachePort`, one `XxxRepo` per table, `SourcePort` / `ParserPort`, `CalendarPort` / `NotionPort`. The scheduler, `RoleModelRenderer` and the difficulty coefficients are pure domain functions, not ports — they have no external dependency and must be testable on their own.
6. Every port has at least two implementations: the real one plus an `InMemory` / `Fake`. The point of the fake is that today's tests need no Docker — that is how you know the abstraction is right.
7. Port interfaces use domain types only, never vendor types. `StoragePort.put(key, bytes)` is fine, `put(boto3_object)` is not; `LLMPort.complete()` returns a Pydantic model, not an SDK response.
8. Swapping a vendor touches only the assembly point: one `container.py` per service, with environment variables choosing the implementation. The strings `boto3`, `anthropic`, `openai` and `redis` appear nowhere else.

### Readability

9. One use case per file, named after a verb: `evaluate_session.py`, `generate_followups.py`.
10. Domain state machines use an enum plus an explicit transition table, never `if status == "questioning"` scattered around.
11. Fixed naming: ports are `XxxPort`, implementations are technology + role (`PgSessionRepo`, `R2Storage`, `OpenAICompatLLM`), use cases are verbs.
12. `mypy --strict` passes. Pydantic owns every piece of data crossing a boundary (HTTP, queue payloads, LLM output).
13. Every service and package root carries a `README.md` answering only three questions: what it owns, which ports it exposes, what it does not do.

### Change discipline

14. Adding an external integration means adding an adapter and editing a container — not editing a use case. If a use case has to change, the port was designed wrong; fix the port first.
15. DB schema changes go through Alembic migrations only, in the same PR as the feature.
16. Queue payloads are versioned Pydantic models. Adding a field is fine; changing a meaning needs a new version.
17. PostgreSQL is the source of truth for job state; Redis is only a cache. Flushing Redis must never lose a session or a job.

### CI must pass

`ruff` -> `mypy --strict` -> `import-linter` (including the `cmd/` contract) -> `pytest` (unit + application, no Docker) -> `alembic check`
