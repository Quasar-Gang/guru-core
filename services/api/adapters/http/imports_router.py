"""Upload import endpoints: presign, complete, and list."""

from uuid import UUID

from fastapi import APIRouter, Request
from pydantic import BaseModel

from services.api.adapters.http.deps import CurrentUserId, get_container
from services.api.adapters.http.schemas import ErrorResponse
from services.api.application.import_google_calendar import ImportGoogleCalendar
from services.api.application.list_imports import ImportView
from services.api.application.presign_import import PresignResult

__all__ = ["GoogleCalendarImportRequest", "PresignRequest", "router"]

router = APIRouter(tags=["imports"])

_UNAUTHORIZED = {
    "model": ErrorResponse,
    "description": "`unauthorized` — missing, invalid or expired bearer token.",
}
_RATE_LIMITED = {
    "model": ErrorResponse,
    "description": "`rate_limited` — too many requests for this user.",
}


class PresignRequest(BaseModel):
    filename: str
    content_type: str
    size_bytes: int


class GoogleCalendarImportRequest(BaseModel):
    days: int = ImportGoogleCalendar.DEFAULT_WINDOW_DAYS


@router.post(
    "/imports/presign",
    response_model=PresignResult,
    summary="Step 1 of a file upload: reserve an import and get a direct-upload URL",
    response_description=(
        "The new `import_id`, the URL to PUT the bytes to, the storage key, and the "
        "lifetime of that URL in seconds (900)."
    ),
    responses={
        401: _UNAUTHORIZED,
        422: {
            "model": ErrorResponse,
            "description": (
                "`invalid_input` — `size_bytes` exceeds the 20 MB limit (20971520 bytes), "
                "`filename` is empty once stripped of path segments, or neither the "
                "extension nor `content_type` maps to a supported format."
            ),
        },
        429: _RATE_LIMITED,
    },
)
async def presign_import(
    request: Request, user_id: CurrentUserId, body: PresignRequest
) -> PresignResult:
    """First of the three calls that bring a file into the system.

    Declare the file up front — name, MIME type and size — and this creates an import row
    in status `pending` and returns a presigned `upload_url`. Nothing is stored yet; the
    bytes never pass through this endpoint.

    The full upload flow:

    1. `POST /v1/imports/presign` → `import_id` + `upload_url`.
    2. `PUT` the raw bytes to `upload_url` **as-is** (query string included), with the
       same `Content-Type` you declared. Send no `Authorization` header: the URL carries
       its own signature.
    3. `POST /v1/imports/{import_id}/complete` to queue the file for parsing.

    Limits and validation, all enforced here so a rejected file never gets uploaded:

    - **Maximum 20 MB** (`20971520` bytes). `size_bytes` is trusted at this step, so the
      client must send the real size.
    - **`upload_url` is valid for 900 seconds (15 minutes)** — the returned `expires_in`.
      Once it lapses the URL returns `403`; call presign again for a fresh one.
    - The format is decided now, from the file extension first and `content_type` only as
      a fallback. Supported: `csv`, `xlsx`, `md`, `html`, `pdf`, `docx`, `ics`.
    - `filename` is reduced to a single path segment, so directories and `..` in the name
      are stripped rather than rejected.

    An import that is presigned but never completed simply stays `pending` and is never
    parsed; it is harmless to abandon.
    """
    return await get_container(request).presign_import(
        user_id, body.filename, body.content_type, body.size_bytes
    )


@router.post(
    "/imports/{import_id}/complete",
    response_model=ImportView,
    summary="Step 3 of a file upload: confirm the bytes landed and queue parsing",
    response_description="The import, now in status `queued`. Counts are still zero.",
    responses={
        401: _UNAUTHORIZED,
        404: {
            "model": ErrorResponse,
            "description": (
                "`not_found` — no import with this id belongs to the caller. Imports are "
                "scoped per user, so another user's id looks the same as a missing one."
            ),
        },
        422: {
            "model": ErrorResponse,
            "description": (
                "`invalid_input` — nothing was found at the storage key for this import: "
                "the `PUT` to `upload_url` never happened, failed, or the URL had already "
                "expired. Presign again and re-upload."
            ),
        },
        429: _RATE_LIMITED,
    },
)
async def complete_import(request: Request, user_id: CurrentUserId, import_id: UUID) -> ImportView:
    """Call this once the `PUT` to the presigned URL has returned `200`.

    It verifies the object really exists in storage, moves the import from `pending` to
    `queued`, and enqueues an `import.parse` job. **Parsing is asynchronous** — this
    returns immediately, well before the file has been read.

    Poll `GET /v1/imports` until the row leaves `queued`:

    - `parsed` — success. `event_count` and `chunk_count` are now filled in and the
      content is available to plan generation.
    - `failed` — the file could not be read; `error` carries the reason. The upload is
      not retried automatically; presign and upload a corrected file.

    Skipping this call leaves a perfectly uploaded file stuck in `pending` forever.
    """
    return await get_container(request).complete_import(user_id, import_id)


@router.get(
    "/imports",
    response_model=list[ImportView],
    summary="List every import belonging to the signed-in user",
    response_description="All imports, newest first, with their status and parsed counts.",
    responses={401: _UNAUTHORIZED, 429: _RATE_LIMITED},
)
async def list_imports(request: Request, user_id: CurrentUserId) -> list[ImportView]:
    """The polling endpoint for both import routes, and the source for an "imports" screen.

    One row per import, whatever its origin: `source` is `upload` for a presigned file and
    `google_calendar` for a calendar pull.

    `status` moves `pending` → `queued` → `parsed` | `failed` for uploads; a calendar
    import is written synchronously and appears as `parsed` right away. `error` is set
    only in `failed`. `event_count` and `chunk_count` stay `0` until a document has been
    written, so they are a reliable signal of how much the parser actually extracted.

    There is no per-import GET; poll this list after `complete`.
    """
    return await get_container(request).list_imports(user_id)


@router.post(
    "/imports/google-calendar",
    response_model=ImportView,
    summary="Import upcoming Google Calendar events as context",
    response_description="The finished import, already in status `parsed`, with its event count.",
    responses={
        401: _UNAUTHORIZED,
        409: {
            "model": ErrorResponse,
            "description": (
                "`reauth_required` — Google is not connected for this user, the connection "
                "was disconnected, or the stored refresh token was rejected. Send the user "
                "through `GET /v1/integrations/google/authorize` again."
            ),
        },
        422: {
            "model": ErrorResponse,
            "description": "`invalid_input` — `days` is outside the range 1–365.",
        },
        429: _RATE_LIMITED,
    },
)
async def import_google_calendar(
    request: Request, user_id: CurrentUserId, body: GoogleCalendarImportRequest
) -> ImportView:
    """Pull the user's existing commitments straight from Google, with no file involved.

    **Prerequisite:** the user must already have connected Google through
    `GET /v1/integrations/google/authorize` and `POST /v1/integrations/google/callback`.
    Signing in with Google is not enough — calendar access is a separate consent. Without
    it this returns `409 reauth_required`.

    Unlike an upload this is **synchronous**: the events are fetched and stored within the
    request, and the returned import is already `parsed` with `event_count` filled in.
    There is nothing to poll and no presign/complete pair.

    `days` is a forward-looking window starting now — default `90`, maximum `365`. Past
    events are never imported. Re-running creates a new, independent import rather than
    updating the previous one, so plan generation sees the newest pull alongside the old.
    """
    return await get_container(request).import_google_calendar(user_id, body.days)
