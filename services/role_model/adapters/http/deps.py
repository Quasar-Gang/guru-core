"""HTTP dependencies: the X-API-Key guard."""

import secrets
from collections.abc import Callable
from typing import Annotated

from fastapi import Header

from services.role_model.application import Unauthorized


def api_key_guard(expected: str) -> Callable[[str | None], None]:
    """Return a FastAPI dependency that checks the `X-API-Key` header."""

    def guard(x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None) -> None:
        if x_api_key is None or not secrets.compare_digest(x_api_key, expected):
            raise Unauthorized("missing or invalid X-API-Key")

    return guard
