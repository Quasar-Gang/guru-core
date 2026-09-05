"""Station 3: the quarterly review, and the one question it ends on."""

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Request
from pydantic import BaseModel

from services.api.adapters.http.deps import CurrentUserId, get_container
from services.api.adapters.http.schemas import ErrorResponse
from services.api.application.reconciliations import ReconciliationView

__all__ = ["DecisionRequest", "StartReconciliationRequest", "router"]

router = APIRouter(tags=["reconciliations"])

_UNAUTHORIZED = {
    "model": ErrorResponse,
    "description": "`unauthorized` — missing, invalid or expired bearer token.",
}


class StartReconciliationRequest(BaseModel):
    hypothesis_id: UUID


class DecisionRequest(BaseModel):
    """Your answer, not the system's."""

    outcome: Literal["holds", "revise", "replace"]


@router.post(
    "/reconciliations",
    response_model=ReconciliationView,
    status_code=202,
    summary="Review a quarter against the hypothesis that predicted it",
    responses={
        401: _UNAUTHORIZED,
        404: {"model": ErrorResponse, "description": "`not_found` — no such hypothesis."},
        409: {
            "model": ErrorResponse,
            "description": "`conflict` — a reconciliation for that hypothesis is already running.",
        },
    },
)
async def start_reconciliation(
    request: Request, user_id: CurrentUserId, body: StartReconciliationRequest
) -> ReconciliationView:
    """At the review date, the same Analyzer runs again — but now there is a baseline.

    Everything comparable is computed first and only then narrated. Unclassified time is
    where this earns its keep: in Station 1 it was merely flagged, and here it finally has
    something to be measured against.

    Poll `GET /v1/reconciliations/{id}` until `status` is `done`.
    """
    return await get_container(request).start_reconciliation(user_id, body.hypothesis_id)


@router.get(
    "/reconciliations/{reconciliation_id}",
    response_model=ReconciliationView,
    summary="The comparison, the note, and the question",
    responses={
        401: _UNAUTHORIZED,
        404: {"model": ErrorResponse, "description": "`not_found` — no such reconciliation."},
    },
)
async def get_reconciliation(
    request: Request, user_id: CurrentUserId, reconciliation_id: UUID
) -> ReconciliationView:
    """The output is a question, not a score. Nothing here grades anyone.

    `revision_kind` classifies a changed plan rather than punishing it: scope that moved
    because something was learned is `growth`, scope that shrank at the first resistance is
    `avoidance`. That distinction is what q2 was collected for.

    `outcome` stays null until you answer.
    """
    return await get_container(request).get_reconciliation(user_id, reconciliation_id)


@router.put(
    "/reconciliations/{reconciliation_id}/decision",
    response_model=ReconciliationView,
    summary="Answer: does this shape still count?",
    responses={
        401: _UNAUTHORIZED,
        404: {"model": ErrorResponse, "description": "`not_found` — no such reconciliation."},
        409: {
            "model": ErrorResponse,
            "description": (
                "`conflict` — the review is not finished yet, or it has already been answered."
            ),
        },
    },
)
async def decide_reconciliation(
    request: Request, user_id: CurrentUserId, reconciliation_id: UUID, body: DecisionRequest
) -> ReconciliationView:
    """Three ways forward, and the choice is yours.

    `holds` keeps the shape and asks for a new probe. `revise` appends the next version of
    the hypothesis — `next_hypothesis_id` comes back with it — and leaves the previous
    version untouched, because that is the whole point of writing it down. `replace` means
    starting Station 1 again from the data.
    """
    return await get_container(request).decide_reconciliation(
        user_id, reconciliation_id, body.outcome
    )
