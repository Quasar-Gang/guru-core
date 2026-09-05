"""Request and response bodies for the Catalog Service."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from packages.repo.entities import RoleModel

__all__ = ["RoleModelView", "UpsertRoleModelRequest"]


class UpsertRoleModelRequest(BaseModel):
    """A template being written. Every field is required, `cost` included."""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=16, examples=["S-7"])
    name: str = Field(min_length=1, max_length=128, examples=["The Quiet Maintainer"])
    vision: str = Field(min_length=1)
    five_year_path: str = Field(min_length=1)
    must_accumulate: str = Field(min_length=1)
    cost: str = Field(
        min_length=1,
        description="What this shape costs. Required: a template without one is not valid.",
    )
    tags: list[str] = Field(default_factory=list, examples=[["shape:depth", "area:career"]])


class RoleModelView(BaseModel):
    """One template as the catalogue serves it."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    code: str
    name: str
    vision: str
    five_year_path: str
    must_accumulate: str
    cost: str
    tags: list[str]
    author: str
    version: int
    updated_at: datetime

    @classmethod
    def of(cls, role_model: RoleModel) -> RoleModelView:
        return cls(
            id=role_model.id,
            code=role_model.code,
            name=role_model.name,
            vision=role_model.vision,
            five_year_path=role_model.five_year_path,
            must_accumulate=role_model.must_accumulate,
            cost=role_model.cost,
            tags=role_model.tags,
            author=role_model.author,
            version=role_model.version,
            updated_at=role_model.updated_at,
        )
