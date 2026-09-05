"""Login and current-user endpoints."""

from fastapi import APIRouter, Request

from services.api.adapters.http.deps import CurrentUserId, get_container
from services.api.adapters.http.schemas import (
    ErrorResponse,
    GoogleLoginRequest,
    LoginResponse,
    MeResponse,
)
from services.api.domain.errors import NotFound

__all__ = ["router"]

router = APIRouter(tags=["auth"])


@router.post(
    "/auth/google",
    response_model=LoginResponse,
    summary="Exchange a Google authorization code for an API token",
    response_description="The API JWT plus the identity behind it, and whether this is a signup.",
    responses={
        401: {
            "model": ErrorResponse,
            "description": (
                "`unauthorized` — Google refused the exchange: the `code` is wrong, already "
                "spent or expired, the `redirect_uri` does not match the one the code was "
                "issued for, or the returned `id_token` is malformed. Restart the consent "
                "flow to obtain a fresh code."
            ),
        },
        422: {
            "model": ErrorResponse,
            "description": "`invalid_input` — `code` or `redirect_uri` is missing from the body.",
        },
        429: {
            "model": ErrorResponse,
            "description": "`rate_limited` — too many requests from this client address.",
        },
    },
)
async def login_with_google(request: Request, body: GoogleLoginRequest) -> LoginResponse:
    """The entry point of the whole API: the only endpoint that needs no bearer token.

    The client runs the Google sign-in flow itself, then posts the one-time `code` here
    together with the exact `redirect_uri` it used. The service verifies the code with
    Google, finds or creates the user behind that Google account, and returns **our own**
    JWT — a Google token never reaches the client.

    Send the returned `access_token` as `Authorization: Bearer <token>` on every other
    endpoint. It expires after `JWT_TTL_SECONDS`; when it does, run this flow again.

    `is_new_user` is `true` only on the very first login of an account, which is created
    with an empty profile and the `UTC` timezone. Use it to decide whether to send the
    user through onboarding (`PUT /v1/profile`) or straight into the app.

    Signing in does **not** grant calendar or spreadsheet access. That is a second,
    separate consent handled by `GET /v1/integrations/google/authorize`.
    """
    result = await get_container(request).login_with_google(body.code, body.redirect_uri)
    return LoginResponse(
        access_token=result.access_token,
        user_id=result.user_id,
        email=result.email,
        is_new_user=result.is_new_user,
    )


@router.get(
    "/me",
    response_model=MeResponse,
    summary="Identify the caller behind the bearer token",
    response_description="The id and email of the user the token belongs to.",
    responses={
        401: {
            "model": ErrorResponse,
            "description": (
                "`unauthorized` — the `Authorization` header is missing, is not a Bearer "
                "token, or the JWT is invalid or expired. Sign in again."
            ),
        },
        404: {
            "model": ErrorResponse,
            "description": (
                "`not_found` — the token is valid but the user it points at no longer "
                "exists (the account was deleted). Treat it like a signed-out session."
            ),
        },
        429: {
            "model": ErrorResponse,
            "description": "`rate_limited` — too many requests for this user.",
        },
    },
)
async def me(request: Request, user_id: CurrentUserId) -> MeResponse:
    """Resolve the stored token to a user, without needing to decode the JWT client-side.

    Useful on app start to decide between "signed in" and "signed out": a `200` means the
    token is still good, a `401` means it must be replaced via `POST /v1/auth/google`.
    This is identity only — the questionnaire answers and timezone live on
    `GET /v1/profile`.
    """
    user = await get_container(request).users.get(user_id)
    if user is None:
        raise NotFound("user not found")
    return MeResponse(user_id=user.id, email=user.email)
