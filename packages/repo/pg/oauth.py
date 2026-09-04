"""PgOAuthConnectionRepo — oauth_connections 表的 PostgreSQL 實作。"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from packages.repo import models
from packages.repo.entities import OAuthConnection


def _to_entity(row: models.OAuthConnection) -> OAuthConnection:
    return OAuthConnection(
        id=row.id,
        user_id=row.user_id,
        provider=row.provider,
        encrypted_refresh_token=bytes(row.encrypted_refresh_token),
        scopes=row.scopes,
        expires_at=row.expires_at,
        revoked_at=row.revoked_at,
        created_at=row.created_at,
    )


class PgOAuthConnectionRepo:
    """OAuthConnectionRepo 的 PostgreSQL 實作，以 (user_id, provider) 為唯一鍵。"""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def get(self, user_id: UUID, provider: str) -> OAuthConnection | None:
        async with self._session_factory() as session:
            row = await self._find(session, user_id, provider)
            return _to_entity(row) if row is not None else None

    async def list_for_user(self, user_id: UUID) -> list[OAuthConnection]:
        async with self._session_factory() as session:
            rows = await session.scalars(
                select(models.OAuthConnection)
                .where(models.OAuthConnection.user_id == user_id)
                .order_by(models.OAuthConnection.created_at, models.OAuthConnection.provider)
            )
            return [_to_entity(row) for row in rows]

    async def upsert(
        self,
        user_id: UUID,
        provider: str,
        encrypted_refresh_token: bytes,
        scopes: str,
        expires_at: datetime | None,
    ) -> OAuthConnection:
        async with self._session_factory() as session:
            row = await self._find(session, user_id, provider)
            if row is None:
                row = models.OAuthConnection(
                    user_id=user_id,
                    provider=provider,
                    encrypted_refresh_token=encrypted_refresh_token,
                    scopes=scopes,
                    expires_at=expires_at,
                )
                session.add(row)
            else:
                row.encrypted_refresh_token = encrypted_refresh_token
                row.scopes = scopes
                row.expires_at = expires_at
                row.revoked_at = None
            await session.flush()
            await session.refresh(row)
            entity = _to_entity(row)
            await session.commit()
            return entity

    async def mark_revoked(self, user_id: UUID, provider: str, at: datetime) -> None:
        async with self._session_factory() as session:
            await session.execute(
                update(models.OAuthConnection)
                .where(
                    models.OAuthConnection.user_id == user_id,
                    models.OAuthConnection.provider == provider,
                )
                .values(revoked_at=at)
            )
            await session.commit()

    async def _find(
        self, session: AsyncSession, user_id: UUID, provider: str
    ) -> models.OAuthConnection | None:
        row: models.OAuthConnection | None = await session.scalar(
            select(models.OAuthConnection).where(
                models.OAuthConnection.user_id == user_id,
                models.OAuthConnection.provider == provider,
            )
        )
        return row
