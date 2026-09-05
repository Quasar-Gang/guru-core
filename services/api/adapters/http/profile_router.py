"""Profile read and write endpoints."""

from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel

from services.api.adapters.http.deps import CurrentUserId, get_container
from services.api.adapters.http.schemas import ErrorResponse
from services.api.application.get_profile import ProfileView

__all__ = ["UpdateProfileRequest", "router"]

router = APIRouter(tags=["profile"])

_UNAUTHORIZED = {
    "model": ErrorResponse,
    "description": "`unauthorized` — missing, invalid or expired bearer token.",
}
_RATE_LIMITED = {
    "model": ErrorResponse,
    "description": "`rate_limited` — too many requests for this user.",
}


class UpdateProfileRequest(BaseModel):
    answers: dict[str, Any] = {}
    timezone: str | None = None


@router.get(
    "/profile",
    response_model=ProfileView,
    summary="Read the signed-in user's profile",
    response_description=(
        "The stored answers and timezone, or the defaults when nothing has been saved yet."
    ),
    responses={401: _UNAUTHORIZED, 429: _RATE_LIMITED},
)
async def get_profile(request: Request, user_id: CurrentUserId) -> ProfileView:
    """The standing context every plan is generated against: who the user is and where.

    `answers` holds the onboarding questionnaire as a free-form JSON object, and
    `timezone` is the IANA zone every scheduled task is placed in. The plan engine reads
    this on each generation, so keeping it current directly improves plan quality.

    A user who has never written a profile is **not** an error: this returns
    `answers: {}`, `timezone: "UTC"` and the current time as `updated_at`. There is no
    `404` here — use `is_new_user` from login, or an empty `answers`, to decide whether to
    show onboarding.
    """
    return await get_container(request).get_profile(user_id)


@router.put(
    "/profile",
    response_model=ProfileView,
    summary="Replace the signed-in user's profile",
    response_description="The profile as stored, including the resolved timezone.",
    responses={
        401: _UNAUTHORIZED,
        422: {
            "model": ErrorResponse,
            "description": (
                "`invalid_input` — `answers` is not a JSON object, one of its keys is not a "
                "string, or `timezone` is not a name the IANA database knows "
                "(e.g. `Asia/Taipei`, not `GMT+8`)."
            ),
        },
        429: _RATE_LIMITED,
    },
)
async def update_profile(
    request: Request, user_id: CurrentUserId, body: UpdateProfileRequest
) -> ProfileView:
    """Write the onboarding answers, and later any edit the user makes to them.

    This is a genuine `PUT`: `answers` **replaces** the stored object wholesale, it is not
    merged key by key. To change one answer, read `GET /v1/profile`, edit the object
    client-side, and send the whole thing back. Omitting `answers` entirely stores `{}`
    and wipes what was there.

    `timezone` is the exception: omit it or send `null` to keep the zone the user already
    has (or `UTC` on a first write). When present it must be an IANA zone name; it is
    validated against the system tz database before anything is saved, so a bad value
    changes nothing.

    Typically called right after a login that returned `is_new_user: true`, and again
    whenever the user revisits their settings. Later plan generations pick the new values
    up automatically; plans already generated are not rewritten.
    """
    return await get_container(request).update_profile(user_id, body.answers, body.timezone)
