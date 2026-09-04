"""FastAPI app wiring: routes are mounted under `/v1` and DomainErrors map to HTTP statuses."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from services.api.adapters.http.auth_router import router as auth_router
from services.api.adapters.http.files_router import router as files_router
from services.api.adapters.http.imports_router import router as imports_router
from services.api.adapters.http.integrations_router import router as integrations_router
from services.api.adapters.http.jobs_router import router as jobs_router
from services.api.adapters.http.middleware import RateLimitMiddleware
from services.api.adapters.http.plan_sessions_router import router as plan_sessions_router
from services.api.adapters.http.plans_router import router as plans_router
from services.api.adapters.http.profile_router import router as profile_router
from services.api.adapters.http.role_models_router import router as role_models_router
from services.api.domain.errors import (
    Conflict,
    DomainError,
    Forbidden,
    InvalidInput,
    NotFound,
    ReauthRequired,
    Unauthorized,
)

if TYPE_CHECKING:  # pragma: no cover - typing only; avoids a container <-> adapters import cycle
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
    """Convert the class name to snake_case: `ReauthRequired` -> `reauth_required`."""
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
    """Build the API service FastAPI app; every dependency comes from `container`."""
    app = FastAPI(title="guru-core API", version="0.1.0")
    app.state.container = container

    if container.settings.rate_limit_per_minute > 0:
        app.add_middleware(
            RateLimitMiddleware,
            cache=container.cache,
            tokens=container.tokens,
            clock=container.clock,
            limit=container.settings.rate_limit_per_minute,
        )

    app.add_exception_handler(DomainError, _domain_error_handler)
    app.add_exception_handler(RequestValidationError, _validation_error_handler)

    @app.get("/health", tags=["ops"])
    async def health() -> dict[str, str]:
        """Unauthenticated, and exempt from rate limiting."""
        return {"status": "ok"}

    app.include_router(auth_router, prefix=API_PREFIX)
    app.include_router(profile_router, prefix=API_PREFIX)
    app.include_router(imports_router, prefix=API_PREFIX)
    app.include_router(integrations_router, prefix=API_PREFIX)
    app.include_router(files_router, prefix=API_PREFIX)
    app.include_router(plan_sessions_router, prefix=API_PREFIX)
    app.include_router(plans_router, prefix=API_PREFIX)
    app.include_router(jobs_router, prefix=API_PREFIX)
    app.include_router(role_models_router, prefix=API_PREFIX)
    return app
