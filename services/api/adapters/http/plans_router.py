"""Station 2 over HTTP: the plan, its tree, its tasks, check-ins and calendar export."""

from datetime import date, datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Query, Request, Response
from pydantic import BaseModel

from services.api.adapters.http.deps import CurrentUserId, get_container
from services.api.adapters.http.schemas import ErrorResponse
from services.api.application.checkins import CheckinHistory, CheckinResultInput, CheckinView
from services.api.application.exports import ExportRequestResult, ExportStatusView
from services.api.application.plans import PlanDetail, PlanSummary, TaskView

__all__ = ["CheckinRequest", "ExportRequest", "PlanStatusRequest", "TaskStatusRequest", "router"]

router = APIRouter(tags=["plans"])

_UNAUTHORIZED = {
    "model": ErrorResponse,
    "description": "`unauthorized` — missing, invalid or expired bearer token.",
}
#: Optional window bounds for the task list; declared once so the default stays a singleton.
_StartFrom = Annotated[datetime | None, Query(description="Only tasks starting at or after this.")]
_StartTo = Annotated[datetime | None, Query(description="Only tasks starting before this.")]

_PLAN_NOT_FOUND = {
    "model": ErrorResponse,
    "description": (
        "`not_found` — no plan with this id belongs to the caller. Plans are scoped per "
        "user, so another user's id looks the same as a missing one."
    ),
}


class PlanStatusRequest(BaseModel):
    status: Literal["active", "archived"]


class TaskStatusRequest(BaseModel):
    status: Literal["pending", "done", "missed", "skipped"]


class CheckinRequest(BaseModel):
    checkin_date: date
    results: list[CheckinResultInput]
    note: str | None = None


class ExportRequest(BaseModel):
    target: Literal["google_calendar"] = "google_calendar"


@router.get(
    "/plans",
    response_model=list[PlanSummary],
    summary="Every plan, newest first",
    responses={401: _UNAUTHORIZED},
)
async def list_plans(
    request: Request, user_id: CurrentUserId, status: str | None = None
) -> list[PlanSummary]:
    """One plan per hypothesis, and no difficulty variants: the shape has been chosen."""
    return await get_container(request).list_plans(user_id, status)


@router.get(
    "/plans/{plan_id}",
    response_model=PlanDetail,
    summary="One plan, with its milestone tree",
    response_description=(
        "The plan, `milestones` as a nested tree, and `structure` carrying the success "
        "criteria, the assumptions, the quota, and anything trimmed or unplaced."
    ),
    responses={401: _UNAUTHORIZED, 404: _PLAN_NOT_FOUND},
)
async def get_plan(request: Request, user_id: CurrentUserId, plan_id: UUID) -> PlanDetail:
    """Milestones nest; tasks do not.

    Decomposition goes into the tree, so completion never becomes a weighted-average
    argument. `status` starts at `generating` and becomes `draft` when the engine finishes,
    or `failed` with an `error` if it could not.

    Read `structure.assumptions` before showing anything: it says what the plan had to
    assume, what the quota cut, and what fit no free window. A plan that hides those is
    lying about the week it just proposed.
    """
    return await get_container(request).get_plan(user_id, plan_id)


@router.put(
    "/plans/{plan_id}/status",
    response_model=PlanSummary,
    summary="Start a plan, or put it away",
    responses={
        401: _UNAUTHORIZED,
        404: _PLAN_NOT_FOUND,
        409: {
            "model": ErrorResponse,
            "description": "`conflict` — that move is not allowed from the plan's current status.",
        },
    },
)
async def set_plan_status(
    request: Request, user_id: CurrentUserId, plan_id: UUID, body: PlanStatusRequest
) -> PlanSummary:
    """A plan is started or archived; it is never edited into something else.

    Wanting a different plan means wanting a different hypothesis, and that is a new
    version rather than a rewrite of this one.
    """
    return await get_container(request).set_plan_status(user_id, plan_id, body.status)


@router.get(
    "/plans/{plan_id}/tasks",
    response_model=list[TaskView],
    summary="The flat task list, with where each one landed",
    responses={401: _UNAUTHORIZED, 404: _PLAN_NOT_FOUND},
)
async def list_plan_tasks(
    request: Request,
    user_id: CurrentUserId,
    plan_id: UUID,
    start_from: _StartFrom = None,
    start_to: _StartTo = None,
) -> list[TaskView]:
    """Every task, in schedule order, windowed by `start_from` / `start_to` for a day or week view.

    Times come from the schedule slot, not the task: the task says what the work is, the
    slot says when it was placed. Same inputs, same placement — which is what lets a review
    a quarter later compare against something rather than against noise.
    """
    return await get_container(request).list_plan_tasks(user_id, plan_id, start_from, start_to)


@router.put(
    "/plans/{plan_id}/tasks/{task_id}/status",
    response_model=TaskView,
    summary="Tick one task off",
    responses={401: _UNAUTHORIZED, 404: _PLAN_NOT_FOUND},
)
async def update_task_status(
    request: Request,
    user_id: CurrentUserId,
    plan_id: UUID,
    task_id: UUID,
    body: TaskStatusRequest,
) -> TaskView:
    """Completion lives here; the calendar is only a projection of it.

    Changing a status marks the slot dirty and queues an incremental push wherever the plan
    already has a calendar.
    """
    return await get_container(request).update_task_status(user_id, plan_id, task_id, body.status)


@router.post(
    "/plans/{plan_id}/checkins",
    response_model=CheckinView,
    summary="The daily check-in",
    responses={
        401: _UNAUTHORIZED,
        404: _PLAN_NOT_FOUND,
        422: {
            "model": ErrorResponse,
            "description": "`invalid_input` — one of the tasks does not belong to this plan.",
        },
    },
)
async def submit_checkin(
    request: Request, user_id: CurrentUserId, plan_id: UUID, body: CheckinRequest
) -> CheckinView:
    """One row per plan and day; re-submitting the same day replaces it.

    Statuses are written straight through to the tasks, so there is exactly one place that
    says what happened.
    """
    return await get_container(request).submit_checkin(
        user_id, plan_id, body.checkin_date, body.results, body.note
    )


@router.get(
    "/plans/{plan_id}/checkins",
    response_model=CheckinHistory,
    summary="Check-in history and the completion curve",
    responses={401: _UNAUTHORIZED, 404: _PLAN_NOT_FOUND},
)
async def list_checkins(request: Request, user_id: CurrentUserId, plan_id: UUID) -> CheckinHistory:
    """`daily_rates` is `done / total` over what each day's submission actually covered."""
    return await get_container(request).list_checkins(user_id, plan_id)


@router.post(
    "/plans/{plan_id}/exports",
    response_model=ExportRequestResult,
    status_code=202,
    summary="Push the schedule onto the user's calendar",
    responses={
        401: _UNAUTHORIZED,
        404: _PLAN_NOT_FOUND,
        409: {
            "model": ErrorResponse,
            "description": (
                "`conflict` — the plan is not active. `reauth_required` — Google is not "
                "connected, or the grant expired; reconnect and try again."
            ),
        },
    },
)
async def request_export(
    request: Request, user_id: CurrentUserId, plan_id: UUID, body: ExportRequest
) -> ExportRequestResult:
    """A plan nobody sees is a plan nobody runs, so it goes where the week already lives.

    The first push builds the plan its own secondary calendar (`mode: full`); later ones
    replay only what changed (`mode: incremental`). Deleting that calendar removes the plan
    from view in one click and costs nothing — the database stays authoritative.
    """
    return await get_container(request).request_export(user_id, plan_id, body.target)


@router.get(
    "/plans/{plan_id}/exports",
    response_model=list[ExportStatusView],
    summary="Where each export stands, and how much has changed since",
    responses={401: _UNAUTHORIZED, 404: _PLAN_NOT_FOUND},
)
async def get_export_status(
    request: Request, user_id: CurrentUserId, plan_id: UUID
) -> list[ExportStatusView]:
    """`pending_changes` is the dirty count: exactly what the next push would send."""
    return await get_container(request).get_export_status(user_id, plan_id)


@router.delete(
    "/plans/{plan_id}/exports/{target}",
    status_code=204,
    summary="Take the plan off the calendar",
    responses={401: _UNAUTHORIZED, 404: _PLAN_NOT_FOUND},
)
async def unexport_plan(
    request: Request, user_id: CurrentUserId, plan_id: UUID, target: str
) -> Response:
    """Deletes the calendar and forgets every event id, so a later push starts clean."""
    await get_container(request).unexport_plan(user_id, plan_id, target)
    return Response(status_code=204)
