"""Profile read and write endpoints."""

from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel

from services.api.adapters.http.deps import CurrentUserId, get_container
from services.api.application.get_profile import ProfileView

__all__ = ["UpdateProfileRequest", "router"]

router = APIRouter(tags=["profile"])


class UpdateProfileRequest(BaseModel):
    answers: dict[str, Any] = {}
    timezone: str | None = None


@router.get("/profile", response_model=ProfileView)
async def get_profile(request: Request, user_id: CurrentUserId) -> ProfileView:
    return await get_container(request).get_profile(user_id)


@router.put("/profile", response_model=ProfileView)
async def update_profile(
    request: Request, user_id: CurrentUserId, body: UpdateProfileRequest
) -> ProfileView:
    return await get_container(request).update_profile(user_id, body.answers, body.timezone)
