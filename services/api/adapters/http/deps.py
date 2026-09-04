"""FastAPI dependencies: pull the container off the request, resolve user_id from a Bearer JWT."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated
from uuid import UUID

from fastapi import Depends, Request

from services.api.domain.errors import Unauthorized

if TYPE_CHECKING:  # pragma: no cover - typing only; avoids a container <-> adapters import cycle
    from services.api.container import ApiContainer

__all__ = ["CurrentUserId", "current_user_id", "get_container"]

_BEARER_PREFIX = "bearer "


def get_container(request: Request) -> ApiContainer:
    """Return the container that `create_app` stored on `app.state`."""
    container: ApiContainer = request.app.state.container
    return container


async def current_user_id(request: Request) -> UUID:
    """Parse `Authorization: Bearer <jwt>`; a missing or invalid header always yields 401."""
    header = request.headers.get("Authorization")
    if header is None or not header.lower().startswith(_BEARER_PREFIX):
        raise Unauthorized("missing bearer token")
    token = header[len(_BEARER_PREFIX) :].strip()
    if not token:
        raise Unauthorized("missing bearer token")
    return get_container(request).tokens.verify(token)


CurrentUserId = Annotated[UUID, Depends(current_user_id)]
