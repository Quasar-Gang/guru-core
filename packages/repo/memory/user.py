"""InMemoryUserRepo — in-memory implementation for tests."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from uuid import UUID

from packages.repo.entities import User


class InMemoryUserRepo:
    """UserRepo implementation that keeps users in process memory."""

    def __init__(self) -> None:
        self._users: dict[UUID, User] = {}

    async def get_by_google_sub(self, google_sub: str) -> User | None:
        return next((u for u in self._users.values() if u.google_sub == google_sub), None)

    async def get(self, user_id: UUID) -> User | None:
        return self._users.get(user_id)

    async def create(self, email: str, google_sub: str) -> User:
        user = User(
            id=uuid.uuid4(),
            email=email,
            google_sub=google_sub,
            created_at=datetime.now(UTC),
        )
        self._users[user.id] = user
        return user
