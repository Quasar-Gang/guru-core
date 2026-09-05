"""Third-party connection endpoints: authorize, callback, list, disconnect."""

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel

from services.api.adapters.http.deps import CurrentUserId, get_container
from services.api.adapters.http.schemas import ErrorResponse
from services.api.application.list_integrations import IntegrationView

__all__ = ["AuthorizeUrlResponse", "CallbackRequest", "router"]

router = APIRouter(tags=["integrations"])

_UNAUTHORIZED = {
    "model": ErrorResponse,
    "description": "`unauthorized` — missing, invalid or expired bearer token.",
}
_RATE_LIMITED = {
    "model": ErrorResponse,
    "description": "`rate_limited` — too many requests for this user.",
}
_UNSUPPORTED_PROVIDER = {
    "model": ErrorResponse,
    "description": "`invalid_input` — `provider` is not `google`, the only provider supported.",
}


class AuthorizeUrlResponse(BaseModel):
    authorize_url: str


class CallbackRequest(BaseModel):
    code: str


@router.get(
    "/integrations",
    response_model=list[IntegrationView],
    summary="List the user's third-party connections",
    response_description="One row per provider the user has ever connected.",
    responses={401: _UNAUTHORIZED, 429: _RATE_LIMITED},
)
async def list_integrations(request: Request, user_id: CurrentUserId) -> list[IntegrationView]:
    """What the app checks before offering anything that needs Google.

    Read `connected` and `needs_reauth` together:

    - not listed at all — never connected; show a "Connect Google" button.
    - `connected: true` — good to go for calendar import and calendar/Sheets export.
    - `connected: false, needs_reauth: true` — the connection was disconnected or revoked
      upstream. The row is deliberately kept so the app can prompt for a reconnect; the
      fix is the same authorize → callback pair as a first connection.

    `scopes` lists what Google actually granted, and `connected_at` is when the row was
    first created. An empty list is normal: signing in with Google creates no integration
    row, because sign-in and calendar access are separate grants.
    """
    return await get_container(request).list_integrations(user_id)


@router.get(
    "/integrations/{provider}/authorize",
    response_model=AuthorizeUrlResponse,
    summary="Step 1 of connecting a provider: get the consent URL",
    response_description="A Google consent URL to send the user to. Nothing is stored yet.",
    responses={401: _UNAUTHORIZED, 422: _UNSUPPORTED_PROVIDER, 429: _RATE_LIMITED},
)
async def authorize_integration(
    request: Request, user_id: CurrentUserId, provider: str
) -> AuthorizeUrlResponse:
    """Begin the second Google grant — the one that gives the backend calendar access.

    `provider` must be `google`; it is the only integration in the MVP.

    Send the user to `authorize_url` (redirect or popup). One consent covers all three
    things the backend does on their behalf: reading the calendar for
    `POST /v1/imports/google-calendar`, writing events for calendar export, and creating
    the spreadsheet for the Sheets export. It is requested with `access_type=offline` and
    `prompt=consent` so Google returns a refresh token; without one the connection cannot
    be completed.

    The URL already carries an unguessable `state` nonce and the server-configured
    redirect URI — pass it through unmodified. Nothing is persisted until step 2,
    `POST /v1/integrations/{provider}/callback`, so an abandoned consent leaves no trace.
    """
    url = await get_container(request).authorize_integration(user_id, provider)
    return AuthorizeUrlResponse(authorize_url=url)


@router.post(
    "/integrations/{provider}/callback",
    response_model=IntegrationView,
    summary="Step 2 of connecting a provider: redeem the consent code",
    response_description="The stored connection, now `connected: true`.",
    responses={
        401: _UNAUTHORIZED,
        422: {
            "model": ErrorResponse,
            "description": (
                "`invalid_input` — `provider` is not `google`, or Google returned no "
                "refresh token (usually a re-consent where the user had already granted "
                "access). Restart at `/authorize`, which forces the consent screen."
            ),
        },
        429: _RATE_LIMITED,
        500: {
            "model": ErrorResponse,
            "description": (
                "The token exchange with Google failed outright — typically a `code` that "
                "is expired, already redeemed, or issued for a different redirect URI. "
                "Restart at `/authorize` for a fresh code."
            ),
        },
    },
)
async def complete_integration(
    request: Request, user_id: CurrentUserId, provider: str, body: CallbackRequest
) -> IntegrationView:
    """Finish the connection with the `code` Google appended to the redirect.

    Note this is **the app's own authenticated endpoint**, not a URL Google calls: the
    client catches the redirect, pulls `code` out of the query string, and posts it here
    with its normal bearer token. That is why the `state` nonce only has to be
    unguessable — the user is identified by the JWT, not by `state`.

    The refresh token is encrypted at rest and never leaves the backend; the client is
    never given a Google token. A repeat connection upserts the same row rather than
    creating a duplicate, so reconnecting after a `needs_reauth` is safe.

    Once this returns, `POST /v1/imports/google-calendar` and the Google export routes
    stop failing with `409 reauth_required`.
    """
    return await get_container(request).complete_integration(user_id, provider, body.code)


@router.delete(
    "/integrations/{provider}",
    status_code=204,
    summary="Disconnect a provider",
    response_description="No content. The connection is revoked and the token cache cleared.",
    responses={
        204: {"description": "Disconnected. Nothing is returned."},
        401: _UNAUTHORIZED,
        404: {
            "model": ErrorResponse,
            "description": "`not_found` — this user has no connection row for that provider.",
        },
        422: _UNSUPPORTED_PROVIDER,
        429: _RATE_LIMITED,
    },
)
async def disconnect_integration(
    request: Request, user_id: CurrentUserId, provider: str
) -> Response:
    """Revoke the grant upstream at Google and stop using it here.

    The stored refresh token is revoked with Google, the row is marked revoked, and the
    cached access token is dropped, so the very next Google call fails with
    `409 reauth_required` rather than using a stale token.

    The row is **not** deleted: `GET /v1/integrations` keeps returning it as
    `connected: false, needs_reauth: true` so the app can offer a reconnect. Calling this
    twice is safe — the second call finds the row already revoked and only re-clears the
    cache. Plans already exported to Google Calendar are left in place; only future
    imports and exports stop working.
    """
    await get_container(request).disconnect_integration(user_id, provider)
    return Response(status_code=204)
