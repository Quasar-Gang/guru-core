"""Background job polling endpoint."""

from fastapi import APIRouter, Request

from services.api.adapters.http.deps import CurrentUserId, get_container
from services.api.adapters.http.schemas import ErrorResponse
from services.api.application.get_job import JobView

__all__ = ["router"]

router = APIRouter(tags=["jobs"])


@router.get(
    "/jobs/{job_id}",
    response_model=JobView,
    summary="Check the state of one queued job",
    response_description=(
        "The job id echoed back, plus `status`: `queued`, `running`, `done`, `failed`, or "
        "`unknown` when no record of the job survives."
    ),
    responses={
        401: {
            "model": ErrorResponse,
            "description": (
                "`unauthorized` — the `Authorization: Bearer <jwt>` header is missing or "
                "malformed, or the token has expired."
            ),
        },
        429: {
            "model": ErrorResponse,
            "description": (
                "`rate_limited` — too many requests from this caller in the last minute. The "
                "response carries `Retry-After`."
            ),
        },
    },
)
async def get_job(request: Request, user_id: CurrentUserId, job_id: str) -> JobView:
    """A progress indicator for the `job_id` returned by any `202` endpoint.

    Where the ids come from: `POST /v1/plan-sessions`, `POST /v1/plan-sessions/{id}/answers`,
    `POST /v1/plans/{id}/revisions`, `POST /v1/plans/{id}/export` for a queued target, and the
    import endpoints.

    `status` is one of `queued`, `running`, `done`, `failed`, or `unknown`. **`unknown` is not an
    error**: job records are short-lived (Redis is only a cache here), so a job that finished a
    while ago reports `unknown` rather than `done`.

    Because of that, this endpoint is a hint, never the answer. The durable state lives on the
    resource itself, and that is what the UI should render:

    - plan generation → `GET /v1/plan-sessions/{session_id}` (`status`, `error`)
    - a revision → `GET /v1/plans/{plan_id}/revisions/{revision_id}` (`status`, `diff`)
    - a calendar export → `GET /v1/plans/{plan_id}/export` (`status`, `error`)

    Never 404s — a missing job is reported as `unknown` in a `200`. Job rows carry no user id, so
    this endpoint only requires a valid login and does not check ownership of the underlying work;
    treat a `job_id` as a secret and do not display one job's status on another user's screen.
    """
    return await get_container(request).get_job(job_id)
