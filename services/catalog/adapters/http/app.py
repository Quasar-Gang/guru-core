"""FastAPI app assembly and error mapping for the Catalog Service."""

from typing import TYPE_CHECKING

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from services.catalog.adapters.http.deps import Unauthorized
from services.catalog.adapters.http.router import build_router
from services.catalog.domain.errors import InvalidTag, InvalidTemplate, TemplateNotFound

if TYPE_CHECKING:  # pragma: no cover - type-only, avoids a container <-> adapters import cycle
    from services.catalog.container import CatalogContainer

__all__ = ["create_app"]

_STATUS: dict[type[Exception], int] = {
    Unauthorized: 401,
    TemplateNotFound: 404,
    InvalidTag: 422,
    InvalidTemplate: 422,
}
_CODE: dict[type[Exception], str] = {
    Unauthorized: "unauthorized",
    TemplateNotFound: "not_found",
    InvalidTag: "invalid_input",
    InvalidTemplate: "invalid_input",
}


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message}})


def create_app(container: "CatalogContainer") -> FastAPI:
    app = FastAPI(
        title="guru-core catalog",
        version="1.0.0",
        description=(
            "The Role Model catalogue: borrowed life shapes, each stating its cost. "
            "Reads are open, writes authenticate with `X-API-Key`."
        ),
    )
    app.include_router(build_router(container))

    @app.get("/health", tags=["ops"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    async def handle_domain_error(_: Request, exc: Exception) -> JSONResponse:
        return _error(_STATUS[type(exc)], _CODE[type(exc)], str(exc))

    async def handle_validation_error(_: Request, exc: Exception) -> JSONResponse:
        return _error(422, "invalid_input", str(exc))

    for error_type in _STATUS:
        app.add_exception_handler(error_type, handle_domain_error)
    app.add_exception_handler(RequestValidationError, handle_validation_error)
    return app
