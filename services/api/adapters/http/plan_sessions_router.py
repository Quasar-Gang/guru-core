"""Plan session endpoints: open a session, poll it, answer its follow-up questions."""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Request, status
from pydantic import BaseModel

from services.api.adapters.http.deps import CurrentUserId, get_container
from services.api.application.create_plan_session import CreateSessionResult
from services.api.application.get_plan_session import PlanSessionView
from services.api.application.submit_answers import AnswerInput

__all__ = ["CreatePlanSessionRequest", "SubmitAnswersRequest", "router"]

router = APIRouter(tags=["plan-sessions"])


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
)
async def create_plan_session(
    request: Request, user_id: CurrentUserId, body: CreatePlanSessionRequest
) -> CreateSessionResult:
    return await get_container(request).create_plan_session(
        user_id,
        body.goal,
        body.intake,
        body.import_ids,
        body.trait_role_model_id,
        body.persona_role_model_id,
    )


@router.get("/plan-sessions/{session_id}", response_model=PlanSessionView)
async def get_plan_session(
    request: Request, user_id: CurrentUserId, session_id: UUID
) -> PlanSessionView:
    return await get_container(request).get_plan_session(user_id, session_id)


@router.post(
    "/plan-sessions/{session_id}/answers",
    response_model=CreateSessionResult,
    status_code=status.HTTP_202_ACCEPTED,
)
async def submit_answers(
    request: Request, user_id: CurrentUserId, session_id: UUID, body: SubmitAnswersRequest
) -> CreateSessionResult:
    return await get_container(request).submit_answers(user_id, session_id, body.answers)
