"""InMemoryRoleModelRepo — 測試用的記憶體實作。"""

from __future__ import annotations

import builtins
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from packages.repo.entities import RoleModel


class InMemoryRoleModelRepo:
    """把 role_models 放在 process 記憶體中的 RoleModelRepo 實作。"""

    def __init__(self) -> None:
        self._role_models: dict[UUID, RoleModel] = {}

    async def get(self, role_model_id: UUID) -> RoleModel | None:
        return self._role_models.get(role_model_id)

    async def list(
        self,
        kind: str | None,
        tags_any: Sequence[str] | None,
        tags_all: Sequence[str] | None,
        active_only: bool = True,
        limit: int = 50,
    ) -> builtins.list[RoleModel]:
        found = list(self._role_models.values())
        if active_only:
            found = [r for r in found if r.active]
        if kind is not None:
            found = [r for r in found if r.kind == kind]
        if tags_any:
            wanted = set(tags_any)
            found = [r for r in found if wanted & set(r.tags)]
        if tags_all:
            required = set(tags_all)
            found = [r for r in found if required <= set(r.tags)]
        found.sort(key=lambda r: r.created_at)
        return found[:limit]

    async def list_tags(self) -> builtins.list[str]:
        tags: set[str] = set()
        for role_model in self._role_models.values():
            if role_model.active:
                tags.update(role_model.tags)
        return sorted(tags)

    async def upsert(
        self,
        role_model_id: UUID | None,
        kind: str,
        name: str,
        tags: builtins.list[str],
        content: dict[str, Any],
    ) -> RoleModel:
        now = datetime.now(UTC)
        existing = self._role_models.get(role_model_id) if role_model_id is not None else None
        role_model = RoleModel(
            id=existing.id if existing else (role_model_id or uuid.uuid4()),
            kind=kind,
            name=name,
            tags=list(tags),
            content=dict(content),
            active=existing.active if existing else True,
            version=existing.version + 1 if existing else 1,
            created_at=existing.created_at if existing else now,
            updated_at=now,
        )
        self._role_models[role_model.id] = role_model
        return role_model

    async def deactivate(self, role_model_id: UUID) -> None:
        existing = self._role_models.get(role_model_id)
        if existing is not None:
            self._role_models[role_model_id] = existing.model_copy(
                update={"active": False, "updated_at": datetime.now(UTC)}
            )
