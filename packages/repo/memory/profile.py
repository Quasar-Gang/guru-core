"""InMemoryProfileRepo — in-memory implementation for tests."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from packages.repo.entities import Profile


class InMemoryProfileRepo:
    """ProfileRepo implementation that keeps profiles in process memory."""

    def __init__(self) -> None:
        self._profiles: dict[UUID, Profile] = {}

    async def get(self, user_id: UUID) -> Profile | None:
        return self._profiles.get(user_id)

    async def upsert(self, user_id: UUID, answers: dict[str, Any], timezone: str) -> Profile:
        profile = Profile(
            user_id=user_id,
            answers=dict(answers),
            timezone=timezone,
            updated_at=datetime.now(UTC),
        )
        self._profiles[user_id] = profile
        return profile
