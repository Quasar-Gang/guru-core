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

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

from fastapi import FastAPI

from packages.cache import CachePort, DictCache, RedisCache
from packages.importers import ParserRegistry, default_registry
from packages.queue import ArqQueue, InMemoryQueue, JobPayload, QueuePort
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
from packages.storage import InMemoryStorage, LocalFileStorage, R2Storage, StoragePort
from services.api.adapters.clock import FakeClock, SystemClock
from services.api.adapters.google.oidc import FakeGoogleOidc, GoogleOidc
from services.api.adapters.http.app import create_app
from services.api.adapters.jwt_issuer import HmacTokenIssuer
from services.api.adapters.queue.import_consumer import ImportParseConsumer
from services.api.application.complete_import import CompleteImport
from services.api.application.create_plan_session import CreatePlanSession
from services.api.application.get_job import GetJob
from services.api.application.get_plan_session import GetPlanSession
from services.api.application.get_profile import GetProfile
from services.api.application.list_imports import ListImports
from services.api.application.login_with_google import LoginWithGoogle
from services.api.application.parse_import import ParseImport
from services.api.application.ports import ClockPort, GoogleOidcPort, TokenIssuerPort
from services.api.application.presign_import import PresignImport
from services.api.application.submit_answers import SubmitAnswers
from services.api.application.update_profile import UpdateProfile
from services.api.settings import ApiSettings

__all__ = [
    "ApiContainer",
    "build_container",
    "build_test_container",
    "create_app",
    "create_asgi_app",
    "create_worker_handlers",
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
    parsers: ParserRegistry
    cache: CachePort
    clock: ClockPort
    tokens: TokenIssuerPort
    oidc: GoogleOidcPort

    # --- use cases (one field each) ---
    login_with_google: LoginWithGoogle
    get_profile: GetProfile
    update_profile: UpdateProfile
    presign_import: PresignImport
    complete_import: CompleteImport
    list_imports: ListImports
    parse_import: ParseImport
    create_plan_session: CreatePlanSession
    get_plan_session: GetPlanSession
    submit_answers: SubmitAnswers
    get_job: GetJob


def _build_use_cases(parts: dict[str, Any]) -> dict[str, Any]:
    """Build every use case from the already-assembled repos and ports."""
    return {
        "login_with_google": LoginWithGoogle(
            parts["users"], parts["profiles"], parts["oidc"], parts["tokens"]
        ),
        "get_profile": GetProfile(parts["profiles"], parts["clock"]),
        "update_profile": UpdateProfile(parts["profiles"]),
        "presign_import": PresignImport(parts["imports"], parts["storage"]),
        "complete_import": CompleteImport(
            parts["imports"], parts["documents"], parts["storage"], parts["queue"]
        ),
        "list_imports": ListImports(parts["imports"], parts["documents"]),
        "parse_import": ParseImport(
            parts["imports"], parts["documents"], parts["storage"], parts["parsers"]
        ),
        "create_plan_session": CreatePlanSession(
            parts["plan_sessions"],
            parts["imports"],
            parts["oauth_connections"],
            parts["queue"],
        ),
        "get_plan_session": GetPlanSession(
            parts["plan_sessions"],
            parts["followup_rounds"],
            parts["plans"],
            parts["plan_tasks"],
        ),
        "submit_answers": SubmitAnswers(
            parts["plan_sessions"], parts["followup_rounds"], parts["queue"], parts["clock"]
        ),
        "get_job": GetJob(parts["cache"], parts["queue"]),
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


_R2_REQUIRED_SETTINGS = ("r2_account_id", "r2_access_key_id", "r2_secret_access_key", "r2_bucket")


def _build_storage(settings: ApiSettings) -> StoragePort:
    """Pick the StoragePort implementation. This is the only place the backend is chosen."""
    if settings.storage_backend == "memory":
        return InMemoryStorage()
    if settings.storage_backend == "r2":
        missing = [name for name in _R2_REQUIRED_SETTINGS if not getattr(settings, name)]
        if missing:
            raise ValueError(
                "storage_backend='r2' requires these settings to be set: " + ", ".join(missing)
            )
        return R2Storage(
            account_id=settings.r2_account_id,
            access_key_id=settings.r2_access_key_id,
            secret_access_key=settings.r2_secret_access_key,
            bucket=settings.r2_bucket,
        )
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
        "parsers": default_registry(),
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
        "parsers": default_registry(),
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


def create_worker_handlers(
    container: ApiContainer,
) -> dict[str, Callable[[JobPayload], Awaitable[None]]]:
    """Queue name -> handler map used by `cmd/api_worker.py`."""
    return {
        "import.parse": ImportParseConsumer(container.parse_import),
        # TODO(Task 34): register the "export.push" handler once PushExport exists.
    }
