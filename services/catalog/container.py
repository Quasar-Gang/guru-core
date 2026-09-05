"""The single composition root for the Catalog Service.

`CatalogContainer` is a frozen dataclass holding settings, the one repo this service owns,
the loaded tag vocabulary, and one field per use case. Adapters only ever read from the
container; they never construct an implementation themselves.
"""

from dataclasses import dataclass, fields
from typing import Any

from fastapi import FastAPI

from packages.repo import (
    InMemoryRoleModelRepo,
    PgRoleModelRepo,
    RoleModelRepo,
    build_engine,
    build_session_factory,
)
from services.catalog.adapters.http.app import create_app
from services.catalog.application.use_cases import (
    DeactivateRoleModel,
    GetRoleModel,
    ListRoleModels,
    ListTags,
    SeedCatalog,
    UpsertRoleModel,
)
from services.catalog.domain.tags import TagVocabulary, load_tag_vocabulary
from services.catalog.settings import CatalogSettings

__all__ = [
    "CatalogContainer",
    "build_container",
    "build_test_container",
    "create_app",
    "create_asgi_app",
]


@dataclass(frozen=True)
class CatalogContainer:
    settings: CatalogSettings

    role_models: RoleModelRepo
    vocabulary: TagVocabulary

    list_role_models: ListRoleModels
    get_role_model: GetRoleModel
    list_tags: ListTags
    upsert_role_model: UpsertRoleModel
    deactivate_role_model: DeactivateRoleModel
    seed_catalog: SeedCatalog


def _build_use_cases(parts: dict[str, Any]) -> dict[str, Any]:
    upsert = UpsertRoleModel(parts["role_models"], parts["vocabulary"])
    return {
        "list_role_models": ListRoleModels(parts["role_models"]),
        "get_role_model": GetRoleModel(parts["role_models"]),
        "list_tags": ListTags(parts["role_models"]),
        "upsert_role_model": upsert,
        "deactivate_role_model": DeactivateRoleModel(parts["role_models"]),
        "seed_catalog": SeedCatalog(upsert, parts["settings"].seeds_path),
    }


def _assemble(parts: dict[str, Any], overrides: dict[str, Any]) -> CatalogContainer:
    known = {f.name for f in fields(CatalogContainer)}
    unknown = set(overrides) - known
    if unknown:
        raise TypeError(f"unknown CatalogContainer field(s): {sorted(unknown)}")
    merged = parts | overrides
    return CatalogContainer(**(merged | _build_use_cases(merged) | overrides))


def build_container(settings: CatalogSettings | None = None) -> CatalogContainer:
    """Production wiring: the PostgreSQL catalogue repo and the real tag vocabulary."""
    resolved = settings if settings is not None else CatalogSettings()
    session_factory = build_session_factory(build_engine(resolved.database_url))
    return _assemble(
        {
            "settings": resolved,
            "role_models": PgRoleModelRepo(session_factory),
            "vocabulary": load_tag_vocabulary(resolved.tag_vocab_path),
        },
        {},
    )


def build_test_container(**overrides: Any) -> CatalogContainer:
    """A fully faked container: no database, no network."""
    settings = overrides.get("settings") or CatalogSettings(_env_file=None)
    return _assemble(
        {
            "settings": settings,
            "role_models": InMemoryRoleModelRepo(),
            "vocabulary": load_tag_vocabulary(settings.tag_vocab_path),
        },
        overrides,
    )


def create_asgi_app() -> FastAPI:
    """uvicorn factory used by `cmd/catalog_server.py`."""
    return create_app(build_container())
