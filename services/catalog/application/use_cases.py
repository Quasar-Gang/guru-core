"""The Catalog Service's use cases — the whole service fits in one file.

The catalogue does five things: list templates, fetch one, write one, retire one, and load
the shipped six from `seeds/`. There is no scoring here and no user data: the catalogue is
the same for everybody, which is exactly what makes the Fit Verdict the only per-user
object in Station 1.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from uuid import UUID

import yaml

from packages.repo.entities import NewRoleModel, RoleModel
from packages.repo.ports import RoleModelRepo
from services.catalog.domain.errors import TemplateNotFound
from services.catalog.domain.tags import TagVocabulary
from services.catalog.domain.template import Author, RoleModelTemplate

__all__ = [
    "DeactivateRoleModel",
    "GetRoleModel",
    "ListRoleModels",
    "ListTags",
    "SeedCatalog",
    "UpsertRoleModel",
]


class ListRoleModels:
    """The shipped shapes, plus whatever this user has written for themselves."""

    def __init__(self, role_models: RoleModelRepo) -> None:
        self._role_models = role_models

    async def __call__(
        self,
        *,
        author_user_id: UUID | None = None,
        tags_any: Sequence[str] | None = None,
        limit: int = 50,
    ) -> list[RoleModel]:
        return await self._role_models.list(
            author_user_id=author_user_id, tags_any=tags_any, active_only=True, limit=limit
        )


class GetRoleModel:
    def __init__(self, role_models: RoleModelRepo) -> None:
        self._role_models = role_models

    async def __call__(self, role_model_id: UUID) -> RoleModel:
        found = await self._role_models.get(role_model_id)
        if found is None:
            raise TemplateNotFound(f"no role model {role_model_id}")
        return found


class ListTags:
    def __init__(self, role_models: RoleModelRepo) -> None:
        self._role_models = role_models

    async def __call__(self) -> list[str]:
        return await self._role_models.list_tags()


class UpsertRoleModel:
    """Write a template. The tag vocabulary and the cost rule are enforced here, once."""

    def __init__(self, role_models: RoleModelRepo, vocabulary: TagVocabulary) -> None:
        self._role_models = role_models
        self._vocabulary = vocabulary

    async def __call__(
        self,
        template: RoleModelTemplate,
        *,
        author: Author = "system",
        author_user_id: UUID | None = None,
    ) -> RoleModel:
        return await self._role_models.upsert(
            NewRoleModel(
                code=template.code,
                name=template.name,
                vision=template.vision,
                five_year_path=template.five_year_path,
                must_accumulate=template.must_accumulate,
                cost=template.cost,
                tags=self._vocabulary.validate_tags(template.tags),
                author=author,
                author_user_id=author_user_id,
            )
        )


class DeactivateRoleModel:
    """Retire a template without deleting it: a Hypothesis may still point at it."""

    def __init__(self, role_models: RoleModelRepo) -> None:
        self._role_models = role_models

    async def __call__(self, role_model_id: UUID) -> None:
        found = await self._role_models.get(role_model_id)
        if found is None:
            raise TemplateNotFound(f"no role model {role_model_id}")
        await self._role_models.deactivate(role_model_id)


class SeedCatalog:
    """Load the shipped six from `seeds/role_models/shapes.yaml`. Idempotent, by code."""

    def __init__(self, upsert: UpsertRoleModel, seeds_path: Path) -> None:
        self._upsert = upsert
        self._seeds_path = seeds_path

    async def __call__(self) -> list[RoleModel]:
        raw = yaml.safe_load(self._seeds_path.read_text(encoding="utf-8")) or []
        templates = [RoleModelTemplate.model_validate(entry) for entry in raw]
        return [await self._upsert(template, author="system") for template in templates]
