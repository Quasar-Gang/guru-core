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
uv run python -m cmd.engine_worker         # profile.build / direction.run / plan.generate / reconcile.run
uv run python -m cmd.catalog_server        # Catalog Service HTTP (8001)
uv run python -m cmd.seed_role_models      # load the six shapes from seeds/
uv run python -m cmd.check_llm             # one smoke call against the configured provider
```

## Language

The codebase is **English-only**, without exception: identifiers, comments, docstrings, log and exception messages, test names, prompts, seed content, Markdown docs and YAML comments. Localisation belongs to the client, which is where it can be done properly — a backend that hard-codes one language into its prompts and its seeds has quietly decided who the product is for.

One file carries deliberately non-ASCII content and is not a violation: `tests/fixtures/importers/sample.*` simulates user uploads, and the point of it is that encoding bugs surface in the parser suite rather than in production.

## Engineering discipline

CI enforces every rule below that a tool can check. The rest are held to in review.

### Boundaries — enforced by tooling, not by discipline

1. Dependencies may only point `adapters -> application -> domain`. A reverse import fails CI (`import-linter` layers contract).
2. Services must not import each other. They communicate only through `packages/` or the queue; `from services.api import ...` inside `services/engine` is a violation. This is why the API Service reads `role_models` directly rather than calling the Catalog Service over HTTP: the table has one writer, and a read that is identical for every user does not deserve a network hop.
2b. `cmd/` may only import each service's `container.py` and runtime helpers from `packages/`, never a use case or a domain module; any business branching inside `cmd/` is a violation.
3. Each shared package exports only what its `__init__.py` lists in `__all__`; everything else is private.
4. Exactly one service may write to a given table; the rest read only. The owner is recorded in the first line of the model's docstring.

### Abstraction — every store and every external system is a port

5. The following are always defined as a `Protocol`, with implementations under `adapters`: `LLMPort`, `StoragePort`, `QueuePort`, `CachePort`, one repo per aggregate, `SourcePort` / `ParserPort`, `CalendarPort`, `GoogleOAuthPort`, `GoogleOidcPort`, `TokenIssuerPort`, `TokenCipherPort`, `ClockPort`. The scheduler, the quota, the diff and the verdict rules are pure domain functions, not ports — they have no external dependency and must be testable on their own.
6. Every port has at least two implementations: the real one plus an `InMemory` / `Fake`. The point of the fake is that the unit and application suites need no Docker — that is how you know the abstraction is right.
7. Port interfaces use domain types only, never vendor types. `StoragePort.put(key, bytes)` is fine, `put(boto3_object)` is not; `LLMPort.complete()` returns a Pydantic model, not an SDK response.
8. Swapping a vendor touches only the assembly point: one `container.py` per service, with environment variables choosing the implementation. The strings `boto3`, `anthropic`, `openai` and `redis` appear nowhere else.

### Readability

9. One use case per class, named after a verb: `StartDirectionRun`, `CreateHypothesis`, `SubmitCheckin`. Modules group the use cases of one station, because they share their view models; a use case that fits nowhere gets its own file.
10. Domain state machines use an enum plus an explicit transition table, never `if status == "questioning"` scattered around.
11. Fixed naming: ports are `XxxPort`, implementations are technology + role (`PgPlanTreeRepo`, `R2Storage`, `OpenAICompatLLM`), use cases are verbs.
12. `mypy --strict` passes. Pydantic owns every piece of data crossing a boundary (HTTP, queue payloads, LLM output).
13. Every service and package root carries a `README.md` answering only three questions: what it owns, which ports it exposes, what it does not do.

### Change discipline

14. Adding an external integration means adding an adapter and editing a container — not editing a use case. If a use case has to change, the port was designed wrong; fix the port first.
15. DB schema changes go through Alembic migrations only, in the same PR as the feature.
16. Queue payloads are versioned Pydantic models. Adding a field is fine; changing a meaning needs a new version.
17. PostgreSQL is the source of truth for job state; Redis is only a cache. Flushing Redis must never lose a run, a plan or a review.
18. Anything countable is computed in code. A model classifies, judges and narrates; it never returns a number the system then trusts. Placing tasks on dates, applying the quota, diffing two schedules and counting what was done are arithmetic, and arithmetic does not belong in a prompt.
19. A domain invariant is enforced where it cannot be bypassed — a database constraint, a repository that offers no update method, or an LLM business rule that fails the call. A rule that lives only in a docstring is a rule that will be broken.

### CI must pass

`ruff` -> `mypy --strict` -> `import-linter` (including the `cmd/` contract) -> `pytest` (unit + application, no Docker) -> `alembic check` -> `pytest -m integration` against a real PostgreSQL
