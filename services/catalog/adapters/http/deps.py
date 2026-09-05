"""HTTP dependencies: the `X-API-Key` guard on catalogue writes."""

import secrets
from collections.abc import Callable
from typing import Annotated

from fastapi import Header

from services.catalog.domain.errors import CatalogError

__all__ = ["Unauthorized", "api_key_guard"]


class Unauthorized(CatalogError):
    """The write was not authenticated."""


def api_key_guard(expected: str) -> Callable[[str | None], None]:
    """A FastAPI dependency that checks the `X-API-Key` header in constant time."""

    def guard(x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None) -> None:
        if x_api_key is None or not secrets.compare_digest(x_api_key, expected):
            raise Unauthorized("missing or invalid X-API-Key")

    return guard
