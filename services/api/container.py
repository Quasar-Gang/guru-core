"""The single composition root for the API service.

`ApiContainer` is a frozen dataclass holding settings, the 14 repos, the infrastructure
ports, and **one field per use case**. Adapters only ever read from the container; they
never construct an implementation themselves.

To add a use case:
1. add a field to `ApiContainer`;
2. build it from `parts` in `_build_use_cases()`.
Both `build_container` and `build_test_container` pick it up automatically, so there is
no second place to update.
"""

from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

from fastapi import FastAPI

from packages.cache import CachePort, DictCache, RedisCache
from packages.queue import ArqQueue, InMemoryQueue, QueuePort
from packages.repo import (
    CheckinRepo,
    DocumentRepo,
    FollowupRoundRepo,
    ImportRepo,
    InMemoryCheckinRepo,
    InMemoryDocumentRepo,
    InMemoryFollowupRoundRepo,
    InMemoryImportRepo,
    InMemoryLlmCallRepo,
    InMemoryOAuthConnectionRepo,
    InMemoryPlanExportRepo,
    InMemoryPlanRepo,
    InMemoryPlanRevisionRepo,
    InMemoryPlanSessionRepo,
    InMemoryPlanTaskRepo,
    InMemoryProfileRepo,
    InMemoryRoleModelRepo,
    InMemoryUserRepo,
    LlmCallRepo,
    OAuthConnectionRepo,
    PgCheckinRepo,
    PgDocumentRepo,
    PgFollowupRoundRepo,
    PgImportRepo,
    PgLlmCallRepo,
    PgOAuthConnectionRepo,
    PgPlanExportRepo,
    PgPlanRepo,
    PgPlanRevisionRepo,
    PgPlanSessionRepo,
    PgPlanTaskRepo,
    PgProfileRepo,
    PgRoleModelRepo,
    PgUserRepo,
    PlanExportRepo,
    PlanRepo,
    PlanRevisionRepo,
    PlanSessionRepo,
    PlanTaskRepo,
    ProfileRepo,
    RoleModelRepo,
    UserRepo,
    build_engine,
    build_session_factory,
)
from packages.storage import InMemoryStorage, LocalFileStorage, StoragePort
from services.api.adapters.clock import FakeClock, SystemClock
from services.api.adapters.google.oidc import FakeGoogleOidc, GoogleOidc
from services.api.adapters.http.app import create_app
from services.api.adapters.jwt_issuer import HmacTokenIssuer
from services.api.application.login_with_google import LoginWithGoogle
from services.api.application.ports import ClockPort, GoogleOidcPort, TokenIssuerPort
from services.api.settings import ApiSettings

__all__ = [
    "ApiContainer",
    "build_container",
    "build_test_container",
    "create_app",
    "create_asgi_app",
]


@dataclass(frozen=True)
class ApiContainer:
    settings: ApiSettings

    # --- repos (14, mirroring packages/repo/ports.py) ---
    users: UserRepo
    profiles: ProfileRepo
    oauth_connections: OAuthConnectionRepo
    imports: ImportRepo
    documents: DocumentRepo
    role_models: RoleModelRepo
    plan_sessions: PlanSessionRepo
    followup_rounds: FollowupRoundRepo
    plans: PlanRepo
    plan_tasks: PlanTaskRepo
    checkins: CheckinRepo
    plan_revisions: PlanRevisionRepo
    plan_exports: PlanExportRepo
    llm_calls: LlmCallRepo

    # --- infrastructure ports ---
    storage: StoragePort
    queue: QueuePort
    cache: CachePort
    clock: ClockPort
    tokens: TokenIssuerPort
    oidc: GoogleOidcPort

    # --- use cases (one field each) ---
    login_with_google: LoginWithGoogle


def _build_use_cases(parts: dict[str, Any]) -> dict[str, Any]:
    """Build every use case from the already-assembled repos and ports."""
    return {
        "login_with_google": LoginWithGoogle(
            parts["users"], parts["profiles"], parts["oidc"], parts["tokens"]
        ),
    }


def _assemble(parts: dict[str, Any], overrides: dict[str, Any]) -> ApiContainer:
    """Apply overrides first, then build the use cases from the overridden components.

    This guarantees an overridden repo or port actually reaches the use cases that depend
    on it. Overrides may also name a use case directly; applying them once more at the end
    lets that win over the default wiring.
    """
    known = {f.name for f in fields(ApiContainer)}
    unknown = set(overrides) - known
    if unknown:
        raise TypeError(f"unknown ApiContainer field(s): {sorted(unknown)}")
    merged = parts | overrides
    return ApiContainer(**(merged | _build_use_cases(merged) | overrides))


def _build_storage(settings: ApiSettings) -> StoragePort:
    if settings.storage_backend == "memory":
        return InMemoryStorage()
    if settings.storage_backend == "r2":
        raise NotImplementedError("R2Storage lands in M5 (Task 40)")
    return LocalFileStorage(
        Path(settings.storage_local_root),
        settings.storage_public_base_url,
        settings.storage_signing_secret,
    )


def build_container(settings: ApiSettings | None = None) -> ApiContainer:
    """Production wiring: PostgreSQL repos + local storage + ARQ + Redis."""
    resolved = settings if settings is not None else ApiSettings()
    session_factory = build_session_factory(build_engine(resolved.database_url))
    clock: ClockPort = SystemClock()
    parts: dict[str, Any] = {
        "settings": resolved,
        "users": PgUserRepo(session_factory),
        "profiles": PgProfileRepo(session_factory),
        "oauth_connections": PgOAuthConnectionRepo(session_factory),
        "imports": PgImportRepo(session_factory),
        "documents": PgDocumentRepo(session_factory),
        "role_models": PgRoleModelRepo(session_factory),
        "plan_sessions": PgPlanSessionRepo(session_factory),
        "followup_rounds": PgFollowupRoundRepo(session_factory),
        "plans": PgPlanRepo(session_factory),
        "plan_tasks": PgPlanTaskRepo(session_factory),
        "checkins": PgCheckinRepo(session_factory),
        "plan_revisions": PgPlanRevisionRepo(session_factory),
        "plan_exports": PgPlanExportRepo(session_factory),
        "llm_calls": PgLlmCallRepo(session_factory),
        "storage": _build_storage(resolved),
        "queue": ArqQueue(resolved.redis_url),
        "cache": RedisCache(resolved.redis_url),
        "clock": clock,
        "tokens": HmacTokenIssuer(resolved.jwt_secret, resolved.jwt_ttl_seconds, clock),
        "oidc": GoogleOidc(resolved.google_client_id, resolved.google_client_secret),
    }
    return _assemble(parts, {})


def _test_settings() -> ApiSettings:
    return ApiSettings(
        _env_file=None,  # tests never read .env, so results stay deterministic
        database_url="postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/guru_core_test",
        redis_url="redis://127.0.0.1:6379/15",
        jwt_secret="test-jwt-secret-at-least-32-bytes-long",
        storage_backend="memory",
        storage_public_base_url="http://testserver/v1/files",
        storage_signing_secret="test-storage-secret",
    )


def build_test_container(**overrides: Any) -> ApiContainer:
    """A fully faked container: no DB, Redis, filesystem, or network access.

    Any field can be replaced by keyword, e.g.
    `build_test_container(oidc=FakeGoogleOidc(...), clock=FakeClock(...))`.
    """
    settings = overrides.get("settings") or _test_settings()
    clock: ClockPort = FakeClock(SystemClock().now())
    parts: dict[str, Any] = {
        "settings": settings,
        "users": InMemoryUserRepo(),
        "profiles": InMemoryProfileRepo(),
        "oauth_connections": InMemoryOAuthConnectionRepo(),
        "imports": InMemoryImportRepo(),
        "documents": InMemoryDocumentRepo(),
        "role_models": InMemoryRoleModelRepo(),
        "plan_sessions": InMemoryPlanSessionRepo(),
        "followup_rounds": InMemoryFollowupRoundRepo(),
        "plans": InMemoryPlanRepo(),
        "plan_tasks": InMemoryPlanTaskRepo(),
        "checkins": InMemoryCheckinRepo(),
        "plan_revisions": InMemoryPlanRevisionRepo(),
        "plan_exports": InMemoryPlanExportRepo(),
        "llm_calls": InMemoryLlmCallRepo(),
        "storage": InMemoryStorage(),
        "queue": InMemoryQueue(),
        "cache": DictCache(),
        "clock": clock,
        "tokens": HmacTokenIssuer(settings.jwt_secret, settings.jwt_ttl_seconds, clock),
        "oidc": FakeGoogleOidc(),
    }
    # tokens is bound to the default clock; if the caller overrode only the clock, rebind it
    # so we do not keep issuing tokens against the old one.
    if "clock" in overrides and "tokens" not in overrides:
        parts["tokens"] = HmacTokenIssuer(
            settings.jwt_secret, settings.jwt_ttl_seconds, overrides["clock"]
        )
    return _assemble(parts, overrides)


def create_asgi_app() -> FastAPI:
    """uvicorn factory used by `cmd/api_server.py`."""
    return create_app(build_container())
