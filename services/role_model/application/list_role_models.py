"""List role model summaries, optionally filtered by kind and tags."""

from collections.abc import Sequence
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

from packages.repo import RoleModel, RoleModelRepo


class RoleModelSummary(BaseModel):
    """The trimmed projection used by listings; it omits the full content."""

    id: UUID
    kind: str
    name: str
    tags: list[str]
    summary: str

    @classmethod
    def of(cls, role_model: RoleModel) -> "RoleModelSummary":
        raw = role_model.content.get("summary", "")
        return cls(
            id=role_model.id,
            kind=role_model.kind,
            name=role_model.name,
            tags=list(role_model.tags),
            summary=raw if isinstance(raw, str) else "",
        )


class ListRoleModels:
    def __init__(self, role_models: RoleModelRepo) -> None:
        self._role_models = role_models

    async def __call__(
        self,
        kind: str | None,
        tags: Sequence[str],
        match: Literal["any", "all"] = "any",
        limit: int = 50,
    ) -> list[RoleModelSummary]:
        wanted = list(tags)
        found = await self._role_models.list(
            kind=kind,
            tags_any=wanted if wanted and match == "any" else None,
            tags_all=wanted if wanted and match == "all" else None,
            active_only=True,
            limit=limit,
        )
        return [RoleModelSummary.of(role_model) for role_model in found]
