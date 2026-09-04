# services/api — API Service

## What it owns

The single app-facing HTTP entrypoint (`/v1`), plus the consumers for the `import.parse` and
`export.push` workers. Implemented so far:

- `POST /v1/auth/google` — log in with a Google authorization code, return a JWT we issue.
- `GET /v1/me` — resolve the current user from a Bearer JWT.
- `GET /health` — liveness check, no auth required.

Layering: `domain/` (plain-Python error types) → `application/` (use cases + port Protocols)
→ `adapters/` (FastAPI, httpx, JWT, clock) → `container.py` (the single composition root).

## The ports it exposes

`application/ports.py` defines the ports this service owns; the implementations live in
`adapters/`:

| Port | Production impl | Test impl |
|---|---|---|
| `GoogleOidcPort` | `adapters/google/oidc.py:GoogleOidc` | `FakeGoogleOidc` |
| `TokenIssuerPort` | `adapters/jwt_issuer.py:HmacTokenIssuer` | the same class, paired with `FakeClock` |
| `ClockPort` | `adapters/clock.py:SystemClock` | `FakeClock` (supports `advance(seconds=...)`) |

Every other port comes from `packages/`: the 14 `XxxRepo` types in `packages.repo`,
`StoragePort` from `packages.storage`, `QueuePort` from `packages.queue`, and `CachePort`
from `packages.cache`.

## What it does not do

- It does not generate or revise plans (that is the Plan Engine) and does not store role
  model content (that is the Role Model Service).
- It does not call an LLM directly.
- It never constructs an adapter itself: everything comes from `ApiContainer`.

## Running it

```bash
uv run python -m cmd.api_server        # uvicorn, reads .env
uv run pytest tests/unit/api tests/application/api
```

## Writing tests

The repo-root `conftest.py` provides three fixtures:

- `container` — `build_test_container()`, fully faked (in-memory repos / storage / queue,
  `DictCache`, `FakeClock`, `HmacTokenIssuer`, `FakeGoogleOidc`).
- `client` — `httpx.AsyncClient` over `httpx.ASGITransport`, wired to `create_app(container)`.
- `auth_headers` — `{"Authorization": "Bearer ..."}` for an already-created user; that user's
  id is available separately as the `auth_user_id` fixture.

To swap a component, use `build_test_container(**overrides)`; the replacement really is passed
to the use cases that depend on it.
