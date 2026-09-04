"""HTTP 相依：X-API-Key 保護。"""

import secrets
from collections.abc import Callable
from typing import Annotated

from fastapi import Header

from services.role_model.application import Unauthorized


def api_key_guard(expected: str) -> Callable[[str | None], None]:
    """回傳一個檢查 `X-API-Key` 的 FastAPI dependency。"""

    def guard(x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None) -> None:
        if x_api_key is None or not secrets.compare_digest(x_api_key, expected):
            raise Unauthorized("missing or invalid X-API-Key")

    return guard
