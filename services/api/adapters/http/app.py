"""FastAPI app wiring: routes are mounted under `/v1` and DomainErrors map to HTTP statuses."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

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

__all__ = [
    "API_DESCRIPTION",
    "ErrorBody",
    "ErrorResponse",
    "API_PREFIX",
    "OPENAPI_TAGS",
    "STATUS_BY_ERROR",
    "create_app",
    "error_code",
]

#: Shown at the top of /docs and carried in the exported OpenAPI document.
API_DESCRIPTION = """
The single endpoint the app talks to. A user states a goal; the service collects
whatever context exists, asks follow-up questions when something essential is missing,
and produces three difficulty variants of a scheduled plan.

**Authentication.** Every endpoint except `POST /v1/auth/google`, `GET /health` and the
presigned `/v1/files/*` routes needs `Authorization: Bearer <jwt>`. Get the token from
`POST /v1/auth/google`; it carries the user id and expires after `JWT_TTL_SECONDS`.
The team-facing `role-models` writes authenticate with `X-API-Key` instead.

**Long-running work.** Plan generation, import parsing and calendar export run on a
queue, so the endpoints that start them return `202` with an id. Poll the resource
(`GET /v1/plan-sessions/{id}`, `GET /v1/imports`) rather than expecting a synchronous
result — PostgreSQL is the source of truth for job state, Redis only caches it.

**Errors.** Every failure returns the same envelope:
`{"error": {"code": "not_found", "message": "..."}}`. The code is the snake_case name of
the domain error: `invalid_input` (422), `unauthorized` (401), `forbidden` (403),
`not_found` (404), `conflict` (409), `reauth_required` (409), `rate_limited` (429).
"""

#: One entry per tag, in the order they should appear in the docs.
OPENAPI_TAGS = [
    {"name": "ops", "description": "Liveness. Unauthenticated and exempt from rate limiting."},
    {"name": "auth", "description": "Google sign-in. Exchanges an OAuth code for our own JWT."},
    {"name": "profile", "description": "The user's timezone and questionnaire answers."},
    {
        "name": "imports",
        "description": (
            "Bringing context in. Files go up through a presigned URL and are parsed on "
            "the queue; a connected Google Calendar can be pulled directly."
        ),
    },
    {
        "name": "integrations",
        "description": (
            "OAuth connections. Sign-in and calendar access are separate grants — the app "
            "never sees a Google token, only our JWT."
        ),
    },
    {
        "name": "files",
        "description": (
            "Presigned upload and download for the local storage backend. Authorised by the "
            "signature in the URL, not by a JWT."
        ),
    },
    {
        "name": "plan-sessions",
        "description": (
            "Turning a goal into plans: create a session, answer at most two rounds of "
            "follow-up questions, receive three difficulty variants."
        ),
    },
    {
        "name": "plans",
        "description": (
            "Everything after generation: lifecycle, the built-in todo, daily check-ins, "
            "revisions, and export to Google Calendar or Markdown."
        ),
    },
    {"name": "jobs", "description": "Status of queued work."},
    {
        "name": "role-models",
        "description": (
            "Trait and persona role models. Reads are open to signed-in users; writes are "
            "team-only and authenticate with `X-API-Key`."
        ),
    },
]


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


class ErrorBody(BaseModel):
    """The `error` object carried by every non-2xx response."""

    code: str = Field(examples=["invalid_input"], description="Machine-readable; branch on this.")
    message: str = Field(
        examples=["timezone 'GMT+8' is not an IANA name"],
        description="For developers. Do not show it to end users or match on it.",
    )


class ErrorResponse(BaseModel):
    """Every failure looks like this, including validation errors."""

    error: ErrorBody


def _replace_default_validation_schema(app: FastAPI) -> None:
    """Point every 422 at `ErrorResponse`.

    FastAPI advertises its own `HTTPValidationError` shape, but `_validation_error_handler`
    rewrites the body into our envelope, so the published schema would send a generated
    client looking for a `detail` array that never arrives.
    """
    envelope = {
        "description": "Validation failed",
        "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ErrorResponse"}}},
    }
    original = app.openapi

    def openapi() -> dict[str, Any]:
        spec = original()
        schemas = spec.setdefault("components", {}).setdefault("schemas", {})
        schemas.setdefault("ErrorResponse", ErrorResponse.model_json_schema())
        schemas.setdefault("ErrorBody", ErrorBody.model_json_schema())
        for operations in spec["paths"].values():
            for operation in operations.values():
                response = operation.get("responses", {}).get("422")
                if response is None:
                    continue
                if "HTTPValidationError" in str(response.get("content", "")):
                    operation["responses"]["422"] = {
                        **envelope,
                        "description": response.get("description") or envelope["description"],
                    }
        app.openapi_schema = spec
        return spec

    app.openapi = openapi  # type: ignore[method-assign]


def create_app(container: ApiContainer) -> FastAPI:
    """Build the API service FastAPI app; every dependency comes from `container`."""
    app = FastAPI(
        title="guru-core API",
        version="0.1.0",
        description=API_DESCRIPTION,
        openapi_tags=OPENAPI_TAGS,
        contact={"name": "Quasar-Gang", "url": "https://github.com/Quasar-Gang/guru-core"},
        license_info={"name": "Proprietary — all rights reserved"},
    )
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
    _replace_default_validation_schema(app)
    return app
