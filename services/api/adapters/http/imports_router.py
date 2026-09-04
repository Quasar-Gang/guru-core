"""Upload import endpoints: presign, complete, and list."""

from uuid import UUID

from fastapi import APIRouter, Request
from pydantic import BaseModel

from services.api.adapters.http.deps import CurrentUserId, get_container
from services.api.application.import_google_calendar import ImportGoogleCalendar
from services.api.application.list_imports import ImportView
from services.api.application.presign_import import PresignResult

__all__ = ["GoogleCalendarImportRequest", "PresignRequest", "router"]

router = APIRouter(tags=["imports"])


class PresignRequest(BaseModel):
    filename: str
    content_type: str
    size_bytes: int


class GoogleCalendarImportRequest(BaseModel):
    days: int = ImportGoogleCalendar.DEFAULT_WINDOW_DAYS


@router.post("/imports/presign", response_model=PresignResult)
async def presign_import(
    request: Request, user_id: CurrentUserId, body: PresignRequest
) -> PresignResult:
    return await get_container(request).presign_import(
        user_id, body.filename, body.content_type, body.size_bytes
    )


@router.post("/imports/{import_id}/complete", response_model=ImportView)
async def complete_import(request: Request, user_id: CurrentUserId, import_id: UUID) -> ImportView:
    return await get_container(request).complete_import(user_id, import_id)


@router.get("/imports", response_model=list[ImportView])
async def list_imports(request: Request, user_id: CurrentUserId) -> list[ImportView]:
    return await get_container(request).list_imports(user_id)


@router.post("/imports/google-calendar", response_model=ImportView)
async def import_google_calendar(
    request: Request, user_id: CurrentUserId, body: GoogleCalendarImportRequest
) -> ImportView:
    return await get_container(request).import_google_calendar(user_id, body.days)
