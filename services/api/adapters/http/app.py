"""FastAPI app 組裝：路由掛在 `/v1`，DomainError 對應成 HTTP status。"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from services.api.adapters.http.auth_router import router as auth_router
from services.api.domain.errors import (
    Conflict,
    DomainError,
    Forbidden,
    InvalidInput,
    NotFound,
    ReauthRequired,
    Unauthorized,
)

if TYPE_CHECKING:  # pragma: no cover - 只為型別；避免 container ↔ adapters 循環 import
    from services.api.container import ApiContainer

__all__ = ["API_PREFIX", "STATUS_BY_ERROR", "create_app", "error_code"]

API_PREFIX = "/v1"

STATUS_BY_ERROR: dict[type[DomainError], int] = {
    InvalidInput: 422,
    Unauthorized: 401,
    Forbidden: 403,
    NotFound: 404,
    ReauthRequired: 409,
    Conflict: 409,
    DomainError: 500,
}

_CAMEL_BOUNDARY = re.compile(r"(?<!^)(?=[A-Z])")


def error_code(exc: DomainError) -> str:
    """類名轉 snake_case：`ReauthRequired` -> `reauth_required`。"""
    return _CAMEL_BOUNDARY.sub("_", type(exc).__name__).lower()


def _status_for(exc: DomainError) -> int:
    for klass in type(exc).__mro__:
        if klass in STATUS_BY_ERROR:
            return STATUS_BY_ERROR[klass]
    return 500


def _error_response(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message}})


async def _domain_error_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, DomainError)
    return _error_response(_status_for(exc), error_code(exc), str(exc))


async def _validation_error_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    return _error_response(422, "invalid_input", str(exc.errors()))


def create_app(container: ApiContainer) -> FastAPI:
    """組出 API Service 的 FastAPI app；所有依賴都從 `container` 取。"""
    app = FastAPI(title="guru-core API", version="0.1.0")
    app.state.container = container

    app.add_exception_handler(DomainError, _domain_error_handler)
    app.add_exception_handler(RequestValidationError, _validation_error_handler)

    @app.get("/health", tags=["ops"])
    async def health() -> dict[str, str]:
        """不需認證，後續限流也排除它。"""
        return {"status": "ok"}

    app.include_router(auth_router, prefix=API_PREFIX)
    return app
