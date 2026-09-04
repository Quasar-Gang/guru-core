"""InMemoryOAuthConnectionRepo — in-memory implementation for tests."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from uuid import UUID

from packages.repo.entities import OAuthConnection


class InMemoryOAuthConnectionRepo:
    """Keeps oauth_connections in memory, keyed uniquely by (user_id, provider)."""

    def __init__(self) -> None:
        self._connections: dict[tuple[UUID, str], OAuthConnection] = {}

    async def get(self, user_id: UUID, provider: str) -> OAuthConnection | None:
        return self._connections.get((user_id, provider))

    async def list_for_user(self, user_id: UUID) -> list[OAuthConnection]:
        return [c for c in self._connections.values() if c.user_id == user_id]

    async def upsert(
        self,
        user_id: UUID,
        provider: str,
        encrypted_refresh_token: bytes,
        scopes: str,
        expires_at: datetime | None,
    ) -> OAuthConnection:
        existing = self._connections.get((user_id, provider))
        conn = OAuthConnection(
            id=existing.id if existing else uuid.uuid4(),
            user_id=user_id,
            provider=provider,
            encrypted_refresh_token=encrypted_refresh_token,
            scopes=scopes,
            expires_at=expires_at,
            revoked_at=None,
            created_at=existing.created_at if existing else datetime.now(UTC),
        )
        self._connections[(user_id, provider)] = conn
        return conn

    async def mark_revoked(self, user_id: UUID, provider: str, at: datetime) -> None:
        existing = self._connections.get((user_id, provider))
        if existing is not None:
            self._connections[(user_id, provider)] = existing.model_copy(update={"revoked_at": at})
