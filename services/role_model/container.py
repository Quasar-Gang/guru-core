"""Composition root for the Role Model Service: the only place that picks implementations.

`build_container()` wires the production dependencies (PostgreSQL); `build_test_container()`
wires in-memory ones so tests do not need Docker.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from fastapi import FastAPI

from packages.llm.config import LLMConfig, load_llm_config
from packages.llm.factory import build_llm
from packages.llm.fake import FakeLLM
from packages.llm.observability import NullObserver
from packages.llm.ports import LLMPort
from packages.llm.prompts import PromptRegistry
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
    RoleModelView,
    UpsertRoleModel,
)
from services.role_model.application.recommend_role_models import RecommendRoleModels
from services.role_model.domain import RoleModelRenderer
from services.role_model.settings import ROOT, RoleModelSettings

__all__ = [
    "RoleModelContainer",
    "PROMPTS_DIR",
    "SEEDS_DIR",
    "build_container",
    "build_test_container",
    "create_app",
    "create_asgi_app",
    "seed_role_models",
]


PROMPTS_DIR = ROOT / "packages" / "llm" / "prompts"
SEEDS_DIR = ROOT / "seeds" / "role_models"


@dataclass(frozen=True)
class RoleModelContainer:
    """The wired-up use cases and ports. Task 28's recommendation use case just adds a field."""

    settings: RoleModelSettings
    role_models: RoleModelRepo
    llm: LLMPort
    list_role_models: ListRoleModels
    get_role_model: GetRoleModel
    upsert_role_model: UpsertRoleModel
    deactivate_role_model: DeactivateRoleModel
    list_tags: ListTags
    recommend_role_models: RecommendRoleModels

    def create_app(self) -> FastAPI:
        """The ASGI app for this container."""
        return create_app(self)


def _wire(
    settings: RoleModelSettings,
    role_models: RoleModelRepo,
    llm: LLMPort,
    llm_config: LLMConfig,
) -> RoleModelContainer:
    return RoleModelContainer(
        settings=settings,
        role_models=role_models,
        llm=llm,
        list_role_models=ListRoleModels(role_models),
        get_role_model=GetRoleModel(role_models),
        upsert_role_model=UpsertRoleModel(role_models, settings.tag_vocab_path),
        deactivate_role_model=DeactivateRoleModel(role_models),
        list_tags=ListTags(role_models),
        recommend_role_models=RecommendRoleModels(
            role_models,
            llm,
            RoleModelRenderer(),
            llm_config.retry.max_attempts,
        ),
    )


def build_container(settings: RoleModelSettings | None = None) -> RoleModelContainer:
    """Production wiring: PostgreSQL-backed repo."""
    settings = settings or RoleModelSettings()
    session_factory = build_session_factory(build_engine(settings.database_url))
    llm_config = load_llm_config()
    llm = build_llm(
        llm_config,
        PromptRegistry(PROMPTS_DIR),
        NullObserver(),
        settings.llm_fixtures_dir,
    )
    return _wire(settings, PgRoleModelRepo(session_factory), llm, llm_config)


def build_test_container(**overrides: Any) -> RoleModelContainer:
    """Fully in-memory wiring.

    Unrecognised keys are treated as `RoleModelSettings` fields (for example
    `tag_vocab_path` or `role_model_api_key`); pass `role_models` to supply a custom repo.
    """
    role_models: RoleModelRepo = overrides.pop("role_models", None) or InMemoryRoleModelRepo()
    llm: LLMPort | None = overrides.pop("llm", None)
    overrides.setdefault("role_model_api_key", "test-key")
    settings = overrides.pop("settings", None) or RoleModelSettings(
        _env_file=None,
        **overrides,
    )
    return _wire(
        settings,
        role_models,
        llm or FakeLLM(settings.llm_fixtures_dir),
        load_llm_config(),
    )


async def seed_role_models(
    container: RoleModelContainer, directory: Path = SEEDS_DIR
) -> list[RoleModelView]:
    """Upsert every role model declared in `directory`/*.yaml, matching rows by name.

    Seed files carry no ids, so an existing row with the same name is updated rather than
    duplicated; running the seed twice leaves the same twelve rows behind.
    """
    existing = await container.role_models.list(
        kind=None, tags_any=None, tags_all=None, active_only=False, limit=1000
    )
    known = {row.name: row.id for row in existing}
    written: list[RoleModelView] = []
    for path in sorted(directory.glob("*.yaml")):
        rows = yaml.safe_load(path.read_text(encoding="utf-8"))["role_models"]
        for row in rows:
            written.append(
                await container.upsert_role_model(
                    role_model_id=known.get(row["name"]),
                    kind=row["kind"],
                    name=row["name"],
                    tags=list(row["tags"]),
                    content=dict(row["content"]),
                )
            )
    return written


def create_asgi_app() -> FastAPI:
    """The uvicorn factory used by `cmd/role_model_server.py`."""
    return build_container().create_app()
