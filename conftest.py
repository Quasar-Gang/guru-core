"""Shared pytest fixtures for API tests.

`container` / `client` / `auth_headers` are the entry points every API test builds on:
`container` is a fully faked `ApiContainer`, `client` is an ASGI HTTP client wired to that
same container, and `auth_headers` is a Bearer JWT header for an already-created user.
"""

import sys
from pathlib import Path

# Importing this conftest puts the repo root at `sys.path[0]`, and this repo has a top-level
# `cmd/` package that would then shadow the stdlib `cmd` module (`pdb` needs `cmd.Cmd`).
# Move the repo root to the end of sys.path: `packages` / `services` / `cmd` still import,
# but the stdlib wins. This has to run before any other import.
_ROOT = str(Path(__file__).resolve().parent)
if sys.path and sys.path[0] == _ROOT:
    sys.path.pop(0)
    sys.path.append(_ROOT)

from collections.abc import AsyncIterator  # noqa: E402
from uuid import UUID  # noqa: E402

import httpx  # noqa: E402
import pytest  # noqa: E402

from services.api.container import (  # noqa: E402
    ApiContainer,
    build_test_container,
    create_app,
)


@pytest.fixture
def container() -> ApiContainer:
    return build_test_container()


@pytest.fixture
async def client(container: ApiContainer) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(container)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


@pytest.fixture
async def auth_user_id(container: ApiContainer) -> UUID:
    user = await container.users.create("fixture@example.com", "fixture-sub")
    await container.profiles.upsert(user.id, {}, "UTC")
    return user.id


@pytest.fixture
def auth_headers(container: ApiContainer, auth_user_id: UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {container.tokens.issue(auth_user_id)}"}
