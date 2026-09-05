"""The Role Model catalogue, as the app sees it.

The API Service reads the catalogue table directly rather than calling the Catalog Service
over HTTP. That respects the schema's ownership rule — the Catalog Service is the only
writer of `role_models` — without adding a network hop to a read that is the same for
everybody. A user authoring their own template goes through here, because this is the only
service that knows who is asking.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field

from packages.repo import RoleModelRepo
from packages.repo.entities import NewRoleModel, RoleModel

__all__ = ["AuthorRoleModel", "ListRoleModels", "RoleModelView"]

#: A user-authored template is a Role Model like any other, and must also carry a cost.
AUTHOR_USER = "user"


class RoleModelView(BaseModel):
    """One borrowed shape. Six fields, identical for every user, and `cost` is one of them."""

    id: UUID
    code: str
    name: str
    vision: str
    five_year_path: str
    must_accumulate: str
    cost: str
    tags: list[str] = Field(default_factory=list)
    author: str


class ListRoleModels:
    """The shipped shapes, plus the ones this user wrote. Never anyone else's."""

    def __init__(self, role_models: RoleModelRepo) -> None:
        self._role_models = role_models

    async def __call__(self, user_id: UUID) -> list[RoleModelView]:
        found = await self._role_models.list(author_user_id=user_id)
        return [_view(row) for row in found]


class AuthorRoleModel:
    """Write your own shape. It is scored alongside the six, on the same terms."""

    def __init__(self, role_models: RoleModelRepo) -> None:
        self._role_models = role_models

    async def __call__(self, user_id: UUID, template: NewRoleModel) -> RoleModelView:
        stored = await self._role_models.upsert(
            template.model_copy(update={"author": AUTHOR_USER, "author_user_id": user_id})
        )
        return _view(stored)


def _view(row: RoleModel) -> RoleModelView:
    return RoleModelView(
        id=row.id,
        code=row.code,
        name=row.name,
        vision=row.vision,
        five_year_path=row.five_year_path,
        must_accumulate=row.must_accumulate,
        cost=row.cost,
        tags=row.tags,
        author=row.author,
    )
