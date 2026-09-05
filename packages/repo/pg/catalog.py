"""PostgreSQL repo for the Role Model catalogue."""

from __future__ import annotations

import builtins
from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from packages.repo import models
from packages.repo.entities import NewRoleModel, RoleModel

__all__ = ["PgRoleModelRepo"]


def _role_model(row: models.RoleModel) -> RoleModel:
    return RoleModel(
        id=row.id,
        code=row.code,
        name=row.name,
        vision=row.vision,
        five_year_path=row.five_year_path,
        must_accumulate=row.must_accumulate,
        cost=row.cost,
        tags=row.tags,
        author=row.author,
        author_user_id=row.author_user_id,
        active=row.active,
        version=row.version,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class PgRoleModelRepo:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def get(self, role_model_id: UUID) -> RoleModel | None:
        async with self._session_factory() as session:
            row = await session.get(models.RoleModel, role_model_id)
            return _role_model(row) if row is not None else None

    async def get_by_code(self, code: str) -> RoleModel | None:
        async with self._session_factory() as session:
            row = await session.scalar(
                select(models.RoleModel).where(models.RoleModel.code == code)
            )
            return _role_model(row) if row is not None else None

    async def list(
        self,
        author_user_id: UUID | None = None,
        tags_any: Sequence[str] | None = None,
        active_only: bool = True,
        limit: int = 50,
    ) -> builtins.list[RoleModel]:
        """The shipped shapes, plus the templates this user authored.

        `author_user_id` widens the result rather than narrowing it: a user always sees the
        system catalogue, and never sees another user's private templates.
        """
        stmt = select(models.RoleModel)
        if active_only:
            stmt = stmt.where(models.RoleModel.active.is_(True))
        if author_user_id is None:
            stmt = stmt.where(models.RoleModel.author == "system")
        else:
            stmt = stmt.where(
                (models.RoleModel.author == "system")
                | (models.RoleModel.author_user_id == author_user_id)
            )
        if tags_any:
            stmt = stmt.where(models.RoleModel.tags.overlap(list(tags_any)))
        stmt = stmt.order_by(models.RoleModel.code).limit(limit)
        async with self._session_factory() as session:
            rows = await session.scalars(stmt)
            return [_role_model(row) for row in rows]

    async def list_tags(self) -> builtins.list[str]:
        async with self._session_factory() as session:
            rows = await session.scalars(
                select(models.RoleModel.tags).where(models.RoleModel.active.is_(True))
            )
            return sorted({tag for tags in rows for tag in tags})

    async def upsert(self, role_model: NewRoleModel) -> RoleModel:
        """Insert by `code`, or replace the fields of the template already carrying it."""
        async with self._session_factory() as session:
            row = await session.scalar(
                select(models.RoleModel).where(models.RoleModel.code == role_model.code)
            )
            if row is None:
                row = models.RoleModel(code=role_model.code)
                session.add(row)
            else:
                row.version += 1
            for field, value in role_model.model_dump(exclude={"code"}).items():
                setattr(row, field, value)
            row.active = True
            await session.flush()
            await session.refresh(row)
            entity = _role_model(row)
            await session.commit()
            return entity

    async def deactivate(self, role_model_id: UUID) -> None:
        async with self._session_factory() as session:
            await session.execute(
                update(models.RoleModel)
                .where(models.RoleModel.id == role_model_id)
                .values(active=False)
            )
            await session.commit()
