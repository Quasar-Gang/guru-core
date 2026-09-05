"""Plan session endpoints: open a session, poll it, answer its follow-up questions."""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Request, status
from pydantic import BaseModel

from services.api.adapters.http.deps import CurrentUserId, get_container
from services.api.adapters.http.schemas import ErrorResponse
from services.api.application.create_plan_session import CreateSessionResult
from services.api.application.get_plan_session import PlanSessionView
from services.api.application.submit_answers import AnswerInput

__all__ = ["CreatePlanSessionRequest", "SubmitAnswersRequest", "router"]

router = APIRouter(tags=["plan-sessions"])

_UNAUTHORIZED = (
    "`unauthorized` — the `Authorization: Bearer <jwt>` header is missing or malformed, or the "
    "token has expired."
)
_RATE_LIMITED = (
    "`rate_limited` — too many requests from this caller in the last minute. The response "
    "carries `Retry-After`."
)
_SESSION_NOT_FOUND = (
    "`not_found` — no session with this id belongs to the caller. Another user's session is "
    "indistinguishable from one that never existed."
)


def _errors(*entries: tuple[int, str]) -> dict[int | str, dict[str, Any]]:
    """Document one status per entry; every one of them uses the `{"error": ...}` envelope."""
    return {code: {"model": ErrorResponse, "description": text} for code, text in entries}


class CreatePlanSessionRequest(BaseModel):
    goal: str
    intake: dict[str, Any] = {}
    import_ids: list[UUID] = []
    trait_role_model_id: UUID | None = None
    persona_role_model_id: UUID | None = None


class SubmitAnswersRequest(BaseModel):
    answers: list[AnswerInput] = []


@router.post(
    "/plan-sessions",
    response_model=CreateSessionResult,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Start plan generation from a goal",
    response_description=(
        "Accepted. `session_id` is the resource to poll; `job_id` identifies the queued "
        "`plan.generate` job."
    ),
    responses=_errors(
        (
            422,
            "`invalid_input` — `goal` is empty or whitespace only, one of `import_ids` does not "
            "belong to the caller, or an import has not finished parsing (its `status` is not "
            "`parsed`). Body validation failures use the same code.",
        ),
        (401, _UNAUTHORIZED),
        (429, _RATE_LIMITED),
    ),
)
async def create_plan_session(
    request: Request, user_id: CurrentUserId, body: CreatePlanSessionRequest
) -> CreateSessionResult:
    """Where plan generation begins. **Only `goal` is required**; everything else is context.

    - `intake` — free-form answers about schedule, level and constraints. Whatever is missing
      is what the service will ask about in the follow-up round.
    - `import_ids` — ids from `GET /v1/imports`. Each must belong to the caller and already be
      `parsed`; anything else is rejected with 422 rather than silently ignored.
    - `trait_role_model_id` / `persona_role_model_id` — optional picks from `/v1/role-models`.
    - A live Google Calendar connection is picked up automatically, so the generated schedule
      avoids the user's existing events. No field controls this.

    The response is `202`, never a plan: generation runs on the queue. Poll
    `GET /v1/plan-sessions/{session_id}` and drive the UI off `status`:

    | status | what the client does |
    | --- | --- |
    | `collecting` | keep polling — context is being gathered |
    | `evaluating` | keep polling — the service is deciding whether it knows enough |
    | `questioning` | render `questions`, answer via `POST /v1/plan-sessions/{id}/answers` |
    | `generating` | keep polling — the three plans are being written |
    | `done` | `plans` holds three difficulty variants; let the user pick one |
    | `failed` | show `error`; the session is terminal and cannot be resumed |

    `GET /v1/jobs/{job_id}` reports the queue's own view of the same work, but the session row
    is the source of truth — a job record can expire while the session stays readable.
    """
    return await get_container(request).create_plan_session(
        user_id,
        body.goal,
        body.intake,
        body.import_ids,
        body.trait_role_model_id,
        body.persona_role_model_id,
    )


@router.get(
    "/plan-sessions/{session_id}",
    response_model=PlanSessionView,
    summary="Poll a plan session for questions or the finished plans",
    response_description=(
        "The session's current `status` and `round`, plus `questions` while `questioning` and "
        "`plans` once `done`."
    ),
    responses=_errors(
        (404, _SESSION_NOT_FOUND),
        (401, _UNAUTHORIZED),
        (429, _RATE_LIMITED),
    ),
)
async def get_plan_session(
    request: Request, user_id: CurrentUserId, session_id: UUID
) -> PlanSessionView:
    """The one endpoint to poll after `POST /v1/plan-sessions` or a round of answers.

    Which fields are populated depends entirely on `status`:

    - `questions` is non-empty **only** while `status` is `questioning`. Each question carries
      its `options`, and whether a free-text answer (`allow_custom`) or a skip (`allow_skip`) is
      accepted. `round` counts the follow-up rounds already asked; the service asks at most a
      small fixed number and then generates with what it has.
    - `plans` is filled **only** once `status` is `done`, with the three difficulty variants —
      each summarised with its weekly load (`sessions_per_week`, `total_minutes_per_week`) and
      dates. All three start as `draft`; the user picks one by activating it with
      `PATCH /v1/plans/{plan_id}` (`{"status": "active"}`).
    - `error` is set only when `status` is `failed`, which is terminal — start a new session.

    Polling is cheap but counts against the rate limit; a few seconds between calls is plenty.
    """
    return await get_container(request).get_plan_session(user_id, session_id)


@router.post(
    "/plan-sessions/{session_id}/answers",
    response_model=CreateSessionResult,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Answer a follow-up round and resume generation",
    response_description=(
        "Accepted. The same `session_id`, plus the `job_id` of the queued `plan.continue` job."
    ),
    responses=_errors(
        (404, _SESSION_NOT_FOUND),
        (
            409,
            "`conflict` — the session is not waiting for answers: its `status` is something "
            "other than `questioning` (already `generating`, `done` or `failed`, so the answers "
            "arrived too late), or it has no follow-up round on record. Re-read the session with "
            "`GET /v1/plan-sessions/{session_id}` before retrying.",
        ),
        (401, _UNAUTHORIZED),
        (429, _RATE_LIMITED),
    ),
)
async def submit_answers(
    request: Request, user_id: CurrentUserId, session_id: UUID, body: SubmitAnswersRequest
) -> CreateSessionResult:
    """Submit the answers to the questions currently returned by `GET /v1/plan-sessions/{id}`.

    Accepted **only while the session is `questioning`** — any other status is a 409. Each answer
    references a `question_id` from the current round and carries exactly one of: `choice` (a
    listed option), `custom` (free text, when `allow_custom`), or `skipped: true` (when
    `allow_skip`). Unanswered questions may simply be left out.

    This is `202`, not the plan: the session moves back to `evaluating`, and from there either to
    `questioning` again (one more round) or to `generating`. Keep polling
    `GET /v1/plan-sessions/{session_id}` exactly as after the initial create.
    """
    return await get_container(request).submit_answers(user_id, session_id, body.answers)
