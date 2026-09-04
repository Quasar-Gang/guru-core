"""Plan endpoints: lifecycle (PRD 5), the built-in calendar / todo, and the daily check-in."""

from datetime import date, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Request, Response, status
from pydantic import BaseModel

from services.api.adapters.http.deps import CurrentUserId, get_container
from services.api.application.get_plan import PlanDetail
from services.api.application.get_plan_session import PlanSummary
from services.api.application.list_checkins import CheckinHistory
from services.api.application.list_plan_tasks import PlanTaskList, PlanTaskView
from services.api.application.submit_checkin import CheckinResultInput, CheckinView

__all__ = ["SubmitCheckinRequest", "UpdatePlanRequest", "UpdatePlanTaskRequest", "router"]

router = APIRouter(tags=["plans"])


class UpdatePlanRequest(BaseModel):
    title: str | None = None
    status: str | None = None


@router.get("/plans", response_model=list[PlanSummary])
async def list_plans(
    request: Request, user_id: CurrentUserId, status: str | None = None
) -> list[PlanSummary]:
    return await get_container(request).list_plans(user_id, status)


@router.get("/plans/{plan_id}", response_model=PlanDetail)
async def get_plan(request: Request, user_id: CurrentUserId, plan_id: UUID) -> PlanDetail:
    return await get_container(request).get_plan(user_id, plan_id)


@router.patch("/plans/{plan_id}", response_model=PlanDetail)
async def update_plan(
    request: Request, user_id: CurrentUserId, plan_id: UUID, body: UpdatePlanRequest
) -> PlanDetail:
    return await get_container(request).update_plan(
        user_id, plan_id, title=body.title, status=body.status
    )


@router.post("/plans/{plan_id}/archive", response_model=PlanDetail)
async def archive_plan(request: Request, user_id: CurrentUserId, plan_id: UUID) -> PlanDetail:
    return await get_container(request).archive_plan(user_id, plan_id)


@router.delete("/plans/{plan_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_plan(request: Request, user_id: CurrentUserId, plan_id: UUID) -> Response:
    await get_container(request).delete_plan(user_id, plan_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


class UpdatePlanTaskRequest(BaseModel):
    status: str | None = None
    start_at: datetime | None = None
    end_at: datetime | None = None
    missed_reason: str | None = None


class SubmitCheckinRequest(BaseModel):
    checkin_date: date
    results: list[CheckinResultInput] = []
    note: str | None = None


@router.get("/plans/{plan_id}/tasks", response_model=PlanTaskList)
async def list_plan_tasks(
    request: Request,
    user_id: CurrentUserId,
    plan_id: UUID,
    from_: Annotated[date | None, Query(alias="from")] = None,
    to: date | None = None,
) -> PlanTaskList:
    return await get_container(request).list_plan_tasks(user_id, plan_id, from_, to)


@router.patch("/plans/{plan_id}/tasks/{task_id}", response_model=PlanTaskView)
async def update_plan_task(
    request: Request,
    user_id: CurrentUserId,
    plan_id: UUID,
    task_id: UUID,
    body: UpdatePlanTaskRequest,
) -> PlanTaskView:
    return await get_container(request).update_plan_task(
        user_id,
        plan_id,
        task_id,
        status=body.status,
        start_at=body.start_at,
        end_at=body.end_at,
        missed_reason=body.missed_reason,
    )


@router.post("/plans/{plan_id}/checkins", response_model=CheckinView)
async def submit_checkin(
    request: Request, user_id: CurrentUserId, plan_id: UUID, body: SubmitCheckinRequest
) -> CheckinView:
    return await get_container(request).submit_checkin(
        user_id, plan_id, body.checkin_date, body.results, body.note
    )


@router.get("/plans/{plan_id}/checkins", response_model=CheckinHistory)
async def list_checkins(request: Request, user_id: CurrentUserId, plan_id: UUID) -> CheckinHistory:
    return await get_container(request).list_checkins(user_id, plan_id)
