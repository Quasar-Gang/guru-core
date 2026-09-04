"""Read the current user's profile, falling back to defaults when no row exists yet."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel

from packages.repo import ProfileRepo
from services.api.application.ports import ClockPort

__all__ = ["DEFAULT_TIMEZONE", "GetProfile", "ProfileView"]

DEFAULT_TIMEZONE = "UTC"


class ProfileView(BaseModel):
    user_id: UUID
    answers: dict[str, Any]
    timezone: str
    updated_at: datetime


class GetProfile:
    """A user without a profile row is not an error; they simply have the defaults."""

    def __init__(self, profiles: ProfileRepo, clock: ClockPort) -> None:
        self._profiles = profiles
        self._clock = clock

    async def __call__(self, user_id: UUID) -> ProfileView:
        profile = await self._profiles.get(user_id)
        if profile is None:
            return ProfileView(
                user_id=user_id,
                answers={},
                timezone=DEFAULT_TIMEZONE,
                updated_at=self._clock.now(),
            )
        return ProfileView(
            user_id=profile.user_id,
            answers=profile.answers,
            timezone=profile.timezone,
            updated_at=profile.updated_at,
        )
