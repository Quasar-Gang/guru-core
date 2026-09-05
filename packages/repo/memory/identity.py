"""In-memory repos for identity, used by every test that needs no database."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from packages.repo.entities import OAuthConnection, User

__all__ = ["InMemoryOAuthConnectionRepo", "InMemoryUserRepo"]


def now() -> datetime:
    return datetime.now(UTC)


class InMemoryUserRepo:
    def __init__(self) -> None:
        self._rows: dict[UUID, User] = {}

    async def get_by_google_sub(self, google_sub: str) -> User | None:
        return next((row for row in self._rows.values() if row.google_sub == google_sub), None)

    async def get(self, user_id: UUID) -> User | None:
        return self._rows.get(user_id)

    async def create(self, email: str, google_sub: str) -> User:
        user = User(id=uuid4(), email=email, google_sub=google_sub, created_at=now())
        self._rows[user.id] = user
        return user


class InMemoryOAuthConnectionRepo:
    def __init__(self) -> None:
        self._rows: dict[tuple[UUID, str], OAuthConnection] = {}

    async def get(self, user_id: UUID, provider: str) -> OAuthConnection | None:
        return self._rows.get((user_id, provider))

    async def list_for_user(self, user_id: UUID) -> list[OAuthConnection]:
        return sorted(
            (row for key, row in self._rows.items() if key[0] == user_id),
            key=lambda row: row.provider,
        )

    async def upsert(
        self,
        user_id: UUID,
        provider: str,
        encrypted_refresh_token: bytes,
        scopes: str,
        expires_at: datetime | None,
    ) -> OAuthConnection:
        existing = self._rows.get((user_id, provider))
        row = OAuthConnection(
            id=existing.id if existing else uuid4(),
            user_id=user_id,
            provider=provider,
            encrypted_refresh_token=encrypted_refresh_token,
            scopes=scopes,
            expires_at=expires_at,
            revoked_at=None,
            created_at=existing.created_at if existing else now(),
        )
        self._rows[(user_id, provider)] = row
        return row

    async def mark_revoked(self, user_id: UUID, provider: str, at: datetime) -> None:
        row = self._rows.get((user_id, provider))
        if row is not None:
            self._rows[(user_id, provider)] = row.model_copy(update={"revoked_at": at})
