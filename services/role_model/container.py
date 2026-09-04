"""Composition root for the Role Model Service: the only place that picks implementations.

`build_container()` wires the production dependencies (PostgreSQL); `build_test_container()`
wires in-memory ones so tests do not need Docker.
"""

from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI

from packages.repo import (
    InMemoryRoleModelRepo,
    PgRoleModelRepo,
    RoleModelRepo,
    build_engine,
    build_session_factory,
)
from services.role_model.adapters.http.app import create_app
from services.role_model.application import (
    DeactivateRoleModel,
    GetRoleModel,
    ListRoleModels,
    ListTags,
    UpsertRoleModel,
)
from services.role_model.settings import RoleModelSettings

__all__ = [
    "RoleModelContainer",
    "build_container",
    "build_test_container",
    "create_app",
    "create_asgi_app",
]


@dataclass(frozen=True)
class RoleModelContainer:
    """The wired-up use cases and ports. Task 28's recommendation use case just adds a field."""

    settings: RoleModelSettings
    role_models: RoleModelRepo
    list_role_models: ListRoleModels
    get_role_model: GetRoleModel
    upsert_role_model: UpsertRoleModel
    deactivate_role_model: DeactivateRoleModel
    list_tags: ListTags

    def create_app(self) -> FastAPI:
        """The ASGI app for this container."""
        return create_app(self)


def _wire(
    settings: RoleModelSettings,
    role_models: RoleModelRepo,
) -> RoleModelContainer:
    return RoleModelContainer(
        settings=settings,
        role_models=role_models,
        list_role_models=ListRoleModels(role_models),
        get_role_model=GetRoleModel(role_models),
        upsert_role_model=UpsertRoleModel(role_models, settings.tag_vocab_path),
        deactivate_role_model=DeactivateRoleModel(role_models),
        list_tags=ListTags(role_models),
    )


def build_container(settings: RoleModelSettings | None = None) -> RoleModelContainer:
    """Production wiring: PostgreSQL-backed repo."""
    settings = settings or RoleModelSettings()
    session_factory = build_session_factory(build_engine(settings.database_url))
    return _wire(settings, PgRoleModelRepo(session_factory))


def build_test_container(**overrides: Any) -> RoleModelContainer:
    """Fully in-memory wiring.

    Unrecognised keys are treated as `RoleModelSettings` fields (for example
    `tag_vocab_path` or `role_model_api_key`); pass `role_models` to supply a custom repo.
    """
    role_models: RoleModelRepo = overrides.pop("role_models", None) or InMemoryRoleModelRepo()
    overrides.setdefault("role_model_api_key", "test-key")
    settings = overrides.pop("settings", None) or RoleModelSettings(
        _env_file=None,
        **overrides,
    )
    return _wire(settings, role_models)


def create_asgi_app() -> FastAPI:
    """The uvicorn factory used by `cmd/role_model_server.py`."""
    return build_container().create_app()
