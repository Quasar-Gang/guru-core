"""Role Model Service 的 FastAPI app 組裝與錯誤對應。"""

from typing import TYPE_CHECKING

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from services.role_model.adapters.http.router import build_router
from services.role_model.application import InvalidInput, NotFound, Unauthorized

if TYPE_CHECKING:  # pragma: no cover - 只為型別，避免 container ↔ adapters 迴圈 import
    from services.role_model.container import RoleModelContainer

_STATUS: dict[type[Exception], int] = {Unauthorized: 401, NotFound: 404, InvalidInput: 422}
_CODE: dict[type[Exception], str] = {
    Unauthorized: "unauthorized",
    NotFound: "not_found",
    InvalidInput: "invalid_input",
}


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message}})


def create_app(container: "RoleModelContainer") -> FastAPI:
    app = FastAPI(title="guru-core role model service")
    app.include_router(build_router(container))

    async def handle_domain_error(_: Request, exc: Exception) -> JSONResponse:
        return _error(_STATUS[type(exc)], _CODE[type(exc)], str(exc))

    async def handle_validation_error(_: Request, exc: Exception) -> JSONResponse:
        return _error(422, "invalid_input", str(exc))

    for error_type in _STATUS:
        app.add_exception_handler(error_type, handle_domain_error)
    app.add_exception_handler(RequestValidationError, handle_validation_error)
    return app
