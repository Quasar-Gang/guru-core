"""Ask the Role Model Service to recommend persona role models for the current user.

The API service owns no recommendation logic: it only turns the caller's identity into the
profile the Role Model Service needs (PRD 3.9).
"""

from typing import Any, Protocol
from uuid import UUID

from pydantic import BaseModel

from packages.repo import ProfileRepo

__all__ = ["RecommendRoleModels", "RecommendationView", "RoleModelServicePort"]


class RecommendationView(BaseModel):
    """One recommendation as returned to the app."""

    role_model_id: UUID
    name: str
    reason: str


class RoleModelServicePort(Protocol):
    """The recommendation call on the Role Model Service."""

    async def recommend(self, payload: dict[str, Any]) -> list[dict[str, Any]]: ...


class RecommendRoleModels:
    def __init__(self, profiles: ProfileRepo, role_model_service: RoleModelServicePort) -> None:
        self._profiles = profiles
        self._role_model_service = role_model_service

    async def __call__(
        self,
        user_id: UUID,
        goal: str,
        domains: list[str] | None = None,
        excluded_constraints: list[str] | None = None,
    ) -> list[RecommendationView]:
        profile = await self._profiles.get(user_id)
        payload = {
            "goal": goal,
            "intake": {},
            "profile_answers": dict(profile.answers) if profile is not None else {},
            "domains": list(domains or []),
            "excluded_constraints": list(excluded_constraints or []),
        }
        recommendations = await self._role_model_service.recommend(payload)
        return [RecommendationView.model_validate(item) for item in recommendations]
