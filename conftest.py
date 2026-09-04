"""Shared pytest fixtures for API tests.

`container` / `client` / `auth_headers` 是後續所有 API task 的測試入口：
`container` 是全 Fake 的 `ApiContainer`，`client` 是打在同一個 container 上的
ASGI HTTP client，`auth_headers` 是一個已存在使用者的 Bearer JWT header。
"""

import sys
from pathlib import Path

# pytest 匯入這個 conftest 時會把 repo root 插到 `sys.path[0]`，而本 repo 有一個
# 頂層 `cmd/` package，會蓋掉標準函式庫的 `cmd`（`pdb` 需要 `cmd.Cmd`）。
# 把 repo root 移到 sys.path 尾端：`packages` / `services` / `cmd` 仍可 import，
# 但標準函式庫優先。這段必須在任何其他 import 之前執行。
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
