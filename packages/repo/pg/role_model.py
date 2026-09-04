"""PgRoleModelRepo — PostgreSQL implementation of the role_models table."""

from __future__ import annotations

import builtins
import uuid
from collections.abc import Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import String, func, select, type_coerce
from sqlalchemy.dialects.postgresql import ARRAY as PgARRAY
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from packages.repo import models
from packages.repo.entities import RoleModel

_TAGS = type_coerce(models.RoleModel.tags, PgARRAY(String))


def _to_entity(row: models.RoleModel) -> RoleModel:
    return RoleModel(
        id=row.id,
        kind=row.kind,
        name=row.name,
        tags=list(row.tags),
        content=dict(row.content),
        active=row.active,
        version=row.version,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class PgRoleModelRepo:
    """PostgreSQL RoleModelRepo; role_models are global rather than per-user."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def get(self, role_model_id: UUID) -> RoleModel | None:
        async with self._session_factory() as session:
            row = await session.get(models.RoleModel, role_model_id)
            return _to_entity(row) if row is not None else None

    async def list(
        self,
        kind: str | None,
        tags_any: Sequence[str] | None,
        tags_all: Sequence[str] | None,
        active_only: bool = True,
        limit: int = 50,
    ) -> builtins.list[RoleModel]:
        stmt = select(models.RoleModel)
        if active_only:
            stmt = stmt.where(models.RoleModel.active.is_(True))
        if kind is not None:
            stmt = stmt.where(models.RoleModel.kind == kind)
        if tags_any:
            stmt = stmt.where(_TAGS.overlap(list(tags_any)))
        if tags_all:
            stmt = stmt.where(_TAGS.contains(list(tags_all)))
        stmt = stmt.order_by(models.RoleModel.created_at, models.RoleModel.id).limit(limit)
        async with self._session_factory() as session:
            rows = await session.scalars(stmt)
            return [_to_entity(row) for row in rows]

    async def list_tags(self) -> builtins.list[str]:
        async with self._session_factory() as session:
            rows = await session.scalars(
                select(func.unnest(models.RoleModel.tags))
                .where(models.RoleModel.active.is_(True))
                .distinct()
            )
            return sorted(rows)

    async def upsert(
        self,
        role_model_id: UUID | None,
        kind: str,
        name: str,
        tags: builtins.list[str],
        content: dict[str, Any],
    ) -> RoleModel:
        async with self._session_factory() as session:
            row = (
                await session.get(models.RoleModel, role_model_id)
                if role_model_id is not None
                else None
            )
            if row is None:
                row = models.RoleModel(
                    id=role_model_id or uuid.uuid4(),
                    kind=kind,
                    name=name,
                    tags=list(tags),
                    content=dict(content),
                    active=True,
                    version=1,
                )
                session.add(row)
            else:
                row.kind = kind
                row.name = name
                row.tags = list(tags)
                row.content = dict(content)
                row.version = row.version + 1
            await session.flush()
            await session.refresh(row)
            entity = _to_entity(row)
            await session.commit()
            return entity

    async def deactivate(self, role_model_id: UUID) -> None:
        async with self._session_factory() as session:
            row = await session.get(models.RoleModel, role_model_id)
            if row is not None:
                row.active = False
                await session.commit()
