"""PostgreSQL repos for identity: `users` and `oauth_connections`."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import Select, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from packages.repo import models
from packages.repo.entities import OAuthConnection, User

__all__ = ["PgOAuthConnectionRepo", "PgUserRepo"]


def _user(row: models.User) -> User:
    return User(id=row.id, email=row.email, google_sub=row.google_sub, created_at=row.created_at)


def _connection(row: models.OAuthConnection) -> OAuthConnection:
    return OAuthConnection(
        id=row.id,
        user_id=row.user_id,
        provider=row.provider,
        encrypted_refresh_token=row.encrypted_refresh_token,
        scopes=row.scopes,
        expires_at=row.expires_at,
        revoked_at=row.revoked_at,
        created_at=row.created_at,
    )


class _Repo:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory


class PgUserRepo(_Repo):
    async def get_by_google_sub(self, google_sub: str) -> User | None:
        async with self._session_factory() as session:
            row = await session.scalar(
                select(models.User).where(models.User.google_sub == google_sub)
            )
            return _user(row) if row is not None else None

    async def get(self, user_id: UUID) -> User | None:
        async with self._session_factory() as session:
            row = await session.get(models.User, user_id)
            return _user(row) if row is not None else None

    async def create(self, email: str, google_sub: str) -> User:
        async with self._session_factory() as session:
            row = models.User(email=email, google_sub=google_sub)
            session.add(row)
            await session.flush()
            await session.refresh(row)
            entity = _user(row)
            await session.commit()
            return entity


class PgOAuthConnectionRepo(_Repo):
    async def get(self, user_id: UUID, provider: str) -> OAuthConnection | None:
        async with self._session_factory() as session:
            row = await session.scalar(_by_provider(user_id, provider))
            return _connection(row) if row is not None else None

    async def list_for_user(self, user_id: UUID) -> list[OAuthConnection]:
        async with self._session_factory() as session:
            rows = await session.scalars(
                select(models.OAuthConnection)
                .where(models.OAuthConnection.user_id == user_id)
                .order_by(models.OAuthConnection.provider)
            )
            return [_connection(row) for row in rows]

    async def upsert(
        self,
        user_id: UUID,
        provider: str,
        encrypted_refresh_token: bytes,
        scopes: str,
        expires_at: datetime | None,
    ) -> OAuthConnection:
        async with self._session_factory() as session:
            row = await session.scalar(_by_provider(user_id, provider))
            if row is None:
                row = models.OAuthConnection(user_id=user_id, provider=provider)
                session.add(row)
            row.encrypted_refresh_token = encrypted_refresh_token
            row.scopes = scopes
            row.expires_at = expires_at
            row.revoked_at = None
            await session.flush()
            await session.refresh(row)
            entity = _connection(row)
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


def _by_provider(user_id: UUID, provider: str) -> Select[tuple[models.OAuthConnection]]:
    return select(models.OAuthConnection).where(
        models.OAuthConnection.user_id == user_id,
        models.OAuthConnection.provider == provider,
    )
