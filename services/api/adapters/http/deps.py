"""FastAPI dependencies: pull the container off the request, resolve user_id from a Bearer JWT."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated
from uuid import UUID

from fastapi import Depends, Request
from fastapi.security import HTTPBearer

from services.api.domain.errors import Unauthorized

if TYPE_CHECKING:  # pragma: no cover - typing only; avoids a container <-> adapters import cycle
    from services.api.container import ApiContainer

__all__ = ["CurrentUserId", "bearer_scheme", "current_user_id", "get_container"]

_BEARER_PREFIX = "bearer "

#: Declared purely so the scheme reaches the OpenAPI document: it gives Swagger UI its
#: Authorize button and marks every endpoint that depends on it as authenticated.
#: `auto_error=False` keeps the 401 coming from `current_user_id`, so the error body
#: stays in our own envelope rather than FastAPI's.
bearer_scheme = HTTPBearer(
    auto_error=False,
    scheme_name="BearerJWT",
    description=(
        "A JWT issued by `POST /v1/auth/google`. Send it as `Authorization: Bearer <token>`."
    ),
)


def get_container(request: Request) -> ApiContainer:
    """Return the container that `create_app` stored on `app.state`."""
    container: ApiContainer = request.app.state.container
    return container


async def current_user_id(
    request: Request,
    _scheme: Annotated[object, Depends(bearer_scheme)] = None,
) -> UUID:
    """Parse `Authorization: Bearer <jwt>`; a missing or invalid header always yields 401."""
    header = request.headers.get("Authorization")
    if header is None or not header.lower().startswith(_BEARER_PREFIX):
        raise Unauthorized("missing bearer token")
    token = header[len(_BEARER_PREFIX) :].strip()
    if not token:
        raise Unauthorized("missing bearer token")
    return get_container(request).tokens.verify(token)


CurrentUserId = Annotated[UUID, Depends(current_user_id)]
