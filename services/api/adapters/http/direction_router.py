"""Station 1: the Profile, the analysis run, its Reports and its Fit Verdicts."""

from uuid import UUID

from fastapi import APIRouter, Request

from services.api.adapters.http.deps import CurrentUserId, get_container
from services.api.adapters.http.schemas import ErrorResponse
from services.api.application.direction import DirectionRunView, ProfileView

__all__ = ["router"]

router = APIRouter(tags=["direction"])

_UNAUTHORIZED = {
    "model": ErrorResponse,
    "description": "`unauthorized` — missing, invalid or expired bearer token.",
}


@router.get(
    "/profile",
    response_model=ProfileView,
    summary="The system's read of who you are now",
    response_description=(
        "The Profile: `signals` (what the classifier found) and `coverage` (what it was "
        "built from). Both are empty until something has been uploaded."
    ),
    responses={401: _UNAUTHORIZED},
)
async def get_profile(request: Request, user_id: CurrentUserId) -> ProfileView:
    """One Profile per user, revised in place — never a second one.

    It is built by the `profile.build` job, which runs whenever an upload finishes parsing
    or a constraint question is answered. Until then this returns an empty read with a
    timezone, which is an honest answer rather than an error: the system has nothing to say
    about someone whose data it has not seen.
    """
    return await get_container(request).read_profile(user_id)


@router.post(
    "/direction/runs",
    response_model=DirectionRunView,
    status_code=202,
    summary="Read the data and score every shape against it",
    response_description="The new run, in status `pending`. Poll it for the rest.",
    responses={
        401: _UNAUTHORIZED,
        409: {
            "model": ErrorResponse,
            "description": (
                "`conflict` — nothing has been uploaded yet, or a run is already in flight. "
                "Two concurrent runs would produce Reports that the other's verdicts were "
                "never scored against."
            ),
        },
    },
)
async def start_direction_run(request: Request, user_id: CurrentUserId) -> DirectionRunView:
    """Queue steps 3 to 8a: the Analyzer writes the Reports, the Recommender scores the shapes.

    Two model calls, in that order and never merged. Going through Reports first gives the
    Recommender inspectable evidence to reason over instead of one unexplainable leap, and
    it is what makes the citation rule enforceable — every evidence item points at a Report
    that exists.

    Poll `GET /v1/direction/runs/latest`. `status` moves `pending` → `analyzing` →
    `recommending` → `ready`, and the Reports are readable as soon as it reaches
    `recommending`: the data is meant to speak before any shape is proposed.
    """
    return await get_container(request).start_direction_run(user_id)


@router.get(
    "/direction/runs/latest",
    response_model=DirectionRunView,
    summary="The most recent run, with whatever it has produced so far",
    responses={
        401: _UNAUTHORIZED,
        404: {"model": ErrorResponse, "description": "`not_found` — no run has been started."},
    },
)
async def get_latest_direction_run(request: Request, user_id: CurrentUserId) -> DirectionRunView:
    """What the intake screens poll.

    `reports` fills in first, then `verdicts` — six of them, one per shape, each carrying
    exactly five evidence items and one probe. Note what the five items are not: a score.
    Even the best-fitting shape gets items against it, and the worst gets items for it.
    """
    return await get_container(request).get_direction_run(user_id, None)


@router.get(
    "/direction/runs/{run_id}",
    response_model=DirectionRunView,
    summary="One run by id",
    responses={
        401: _UNAUTHORIZED,
        404: {"model": ErrorResponse, "description": "`not_found` — no such run for this user."},
    },
)
async def get_direction_run(
    request: Request, user_id: CurrentUserId, run_id: UUID
) -> DirectionRunView:
    """An earlier run stays readable: its Reports are the baseline Station 3 compares against."""
    return await get_container(request).get_direction_run(user_id, run_id)
