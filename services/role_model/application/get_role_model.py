"""Fetch a single role model."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel

from packages.repo import RoleModel, RoleModelRepo
from services.role_model.application.errors import NotFound


class RoleModelView(BaseModel):
    """The full projection of one role model: complete content, tags and version."""

    id: UUID
    kind: str
    name: str
    tags: list[str]
    content: dict[str, Any]
    active: bool
    version: int
    created_at: datetime
    updated_at: datetime

    @classmethod
    def of(cls, role_model: RoleModel) -> "RoleModelView":
        return cls.model_validate(role_model.model_dump())


class GetRoleModel:
    def __init__(self, role_models: RoleModelRepo) -> None:
        self._role_models = role_models

    async def __call__(self, role_model_id: UUID) -> RoleModelView:
        role_model = await self._role_models.get(role_model_id)
        if role_model is None:
            raise NotFound(f"role model {role_model_id} not found")
        return RoleModelView.of(role_model)
