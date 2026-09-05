"""In-memory Role Model catalogue."""

from __future__ import annotations

import builtins
from collections.abc import Sequence
from uuid import UUID, uuid4

from packages.repo.entities import NewRoleModel, RoleModel
from packages.repo.memory.identity import now

__all__ = ["InMemoryRoleModelRepo"]


class InMemoryRoleModelRepo:
    def __init__(self) -> None:
        self._rows: dict[UUID, RoleModel] = {}

    async def get(self, role_model_id: UUID) -> RoleModel | None:
        return self._rows.get(role_model_id)

    async def get_by_code(self, code: str) -> RoleModel | None:
        return next((row for row in self._rows.values() if row.code == code), None)

    async def list(
        self,
        author_user_id: UUID | None = None,
        tags_any: Sequence[str] | None = None,
        active_only: bool = True,
        limit: int = 50,
    ) -> builtins.list[RoleModel]:
        rows = list(self._rows.values())
        if active_only:
            rows = [row for row in rows if row.active]
        rows = [
            row
            for row in rows
            if row.author == "system"
            or (author_user_id is not None and row.author_user_id == author_user_id)
        ]
        if tags_any:
            wanted = set(tags_any)
            rows = [row for row in rows if wanted & set(row.tags)]
        return sorted(rows, key=lambda row: row.code)[:limit]

    async def list_tags(self) -> builtins.list[str]:
        return sorted({tag for row in self._rows.values() if row.active for tag in row.tags})

    async def upsert(self, role_model: NewRoleModel) -> RoleModel:
        existing = await self.get_by_code(role_model.code)
        row = RoleModel(
            id=existing.id if existing else uuid4(),
            active=True,
            version=existing.version + 1 if existing else 1,
            created_at=existing.created_at if existing else now(),
            updated_at=now(),
            **role_model.model_dump(),
        )
        self._rows[row.id] = row
        return row

    async def deactivate(self, role_model_id: UUID) -> None:
        row = self._rows.get(role_model_id)
        if row is not None:
            self._rows[role_model_id] = row.model_copy(update={"active": False})
