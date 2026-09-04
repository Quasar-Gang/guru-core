"""Role Model Service 的組裝點：唯一知道「用哪個實作」的地方。

`build_container()` 接正式依賴（PostgreSQL）；`build_test_container()` 全部用
InMemory 實作，測試不需要 Docker。
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
    """已接好線的 use case 與 port。Task 28 的推薦 use case 直接加欄位即可。"""

    settings: RoleModelSettings
    role_models: RoleModelRepo
    list_role_models: ListRoleModels
    get_role_model: GetRoleModel
    upsert_role_model: UpsertRoleModel
    deactivate_role_model: DeactivateRoleModel
    list_tags: ListTags

    def create_app(self) -> FastAPI:
        """本 container 的 ASGI app。"""
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
    """正式組裝：PostgreSQL repo。"""
    settings = settings or RoleModelSettings()
    session_factory = build_session_factory(build_engine(settings.database_url))
    return _wire(settings, PgRoleModelRepo(session_factory))


def build_test_container(**overrides: Any) -> RoleModelContainer:
    """全 InMemory 組裝。

    未知的 key 視為 `RoleModelSettings` 欄位（例如 `tag_vocab_path`、
    `role_model_api_key`）；`role_models` 可直接傳入自訂 repo。
    """
    role_models: RoleModelRepo = overrides.pop("role_models", None) or InMemoryRoleModelRepo()
    overrides.setdefault("role_model_api_key", "test-key")
    settings = overrides.pop("settings", None) or RoleModelSettings(
        _env_file=None,
        **overrides,
    )
    return _wire(settings, role_models)


def create_asgi_app() -> FastAPI:
    """`cmd/role_model_server.py` 用的 uvicorn factory。"""
    return build_container().create_app()
