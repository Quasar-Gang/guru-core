"""The Direction Hypothesis: append-only, and the door into Station 2."""

from uuid import UUID

from fastapi import APIRouter, Request
from pydantic import BaseModel

from services.api.adapters.http.deps import CurrentUserId, get_container
from services.api.adapters.http.schemas import ErrorResponse
from services.api.application.hypotheses import HypothesisView

__all__ = ["CreateHypothesisRequest", "router"]

router = APIRouter(tags=["hypotheses"])

_UNAUTHORIZED = {
    "model": ErrorResponse,
    "description": "`unauthorized` — missing, invalid or expired bearer token.",
}


class CreateHypothesisRequest(BaseModel):
    """Which Fit Verdict you are settling on. The shape comes with it."""

    fit_verdict_id: UUID


@router.post(
    "/hypotheses",
    response_model=HypothesisView,
    status_code=201,
    summary="Settle on one shape, and start the plan that tests it",
    response_description="The new version, and the id of the plan now generating.",
    responses={
        401: _UNAUTHORIZED,
        404: {
            "model": ErrorResponse,
            "description": "`not_found` — no such verdict for this user.",
        },
        422: {
            "model": ErrorResponse,
            "description": "`invalid_input` — the verdict points at a shape that no longer exists.",
        },
    },
)
async def create_hypothesis(
    request: Request, user_id: CurrentUserId, body: CreateHypothesisRequest
) -> HypothesisView:
    """Write `v0`, and queue the plan.

    This is not a vision, and choosing is not committing. It is a borrowed shape, stamped
    with its date and its source, that gives the next quarter something to compare against —
    without a baseline there is no diagnosis, and without a diagnosis you stay at "it's
    fine, I guess" forever.

    **Never overwritten is the point.** There is no update route here, and no repository
    method behind one: a hypothesis you could quietly edit could never be falsified, because
    you would rewrite it to match whatever you ended up doing and learn nothing. A revision
    writes `v1` with its own date; `v0` stays readable forever as the thing that was
    predicted.

    Creating one also creates its Plan, in status `generating`. Poll
    `GET /v1/plans/{plan_id}`.
    """
    return await get_container(request).create_hypothesis(user_id, body.fit_verdict_id)


@router.get(
    "/hypotheses",
    response_model=list[HypothesisView],
    summary="Every version, oldest first",
    responses={401: _UNAUTHORIZED},
)
async def list_hypotheses(request: Request, user_id: CurrentUserId) -> list[HypothesisView]:
    """The whole append-only history. `v0` is still there, saying exactly what it said."""
    return await get_container(request).list_hypotheses(user_id)


@router.get(
    "/hypotheses/{hypothesis_id}",
    response_model=HypothesisView,
    summary="One version",
    responses={
        401: _UNAUTHORIZED,
        404: {"model": ErrorResponse, "description": "`not_found` — no such hypothesis."},
    },
)
async def get_hypothesis(
    request: Request, user_id: CurrentUserId, hypothesis_id: UUID
) -> HypothesisView:
    """`evidence_snapshot` is a copy, not a reference.

    A verdict can be re-run and a report can be rewritten; what this hypothesis was built on
    has to stay readable exactly as it was, or the review a quarter later has nothing solid
    to argue with.
    """
    return await get_container(request).get_hypothesis(user_id, hypothesis_id)
