"""Replace the current user's profile answers and timezone."""

from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from packages.repo import ProfileRepo
from services.api.application.get_profile import DEFAULT_TIMEZONE, ProfileView
from services.api.domain.errors import InvalidInput

__all__ = ["UpdateProfile"]


def _validated_answers(answers: dict[str, Any]) -> dict[str, Any]:
    """MVP keeps the answer schema open: it only has to be a dict keyed by strings."""
    if not isinstance(answers, dict):
        raise InvalidInput("answers must be an object")
    if any(not isinstance(key, str) for key in answers):
        raise InvalidInput("answers keys must be strings")
    return dict(answers)


def _validated_timezone(timezone: str) -> str:
    try:
        ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise InvalidInput(f"unknown timezone: {timezone}") from exc
    return timezone


class UpdateProfile:
    """`timezone=None` keeps whatever the user already had (or the default on first write)."""

    def __init__(self, profiles: ProfileRepo) -> None:
        self._profiles = profiles

    async def __call__(
        self, user_id: UUID, answers: dict[str, Any], timezone: str | None
    ) -> ProfileView:
        checked_answers = _validated_answers(answers)
        if timezone is None:
            current = await self._profiles.get(user_id)
            resolved = current.timezone if current is not None else DEFAULT_TIMEZONE
        else:
            resolved = _validated_timezone(timezone)
        profile = await self._profiles.upsert(user_id, checked_answers, resolved)
        return ProfileView(
            user_id=profile.user_id,
            answers=profile.answers,
            timezone=profile.timezone,
            updated_at=profile.updated_at,
        )
