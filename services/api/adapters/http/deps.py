"""FastAPI 依賴：從 request 取出 container，從 Bearer JWT 解出 user_id。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated
from uuid import UUID

from fastapi import Depends, Request

from services.api.domain.errors import Unauthorized

if TYPE_CHECKING:  # pragma: no cover - 只為型別；避免 container ↔ adapters 循環 import
    from services.api.container import ApiContainer

__all__ = ["CurrentUserId", "current_user_id", "get_container"]

_BEARER_PREFIX = "bearer "


def get_container(request: Request) -> ApiContainer:
    """取得 `create_app` 掛在 `app.state` 上的 container。"""
    container: ApiContainer = request.app.state.container
    return container


async def current_user_id(request: Request) -> UUID:
    """解析 `Authorization: Bearer <jwt>`；缺 header 或無效一律 401。"""
    header = request.headers.get("Authorization")
    if header is None or not header.lower().startswith(_BEARER_PREFIX):
        raise Unauthorized("missing bearer token")
    token = header[len(_BEARER_PREFIX) :].strip()
    if not token:
        raise Unauthorized("missing bearer token")
    return get_container(request).tokens.verify(token)


CurrentUserId = Annotated[UUID, Depends(current_user_id)]
