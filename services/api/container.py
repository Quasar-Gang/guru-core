"""API Service 的唯一組裝點。

`ApiContainer` 是 frozen dataclass：settings、14 個 repo、基礎設施 port，以及
**每個 use case 一個欄位**。adapters 只認 container，不自己 new 任何實作。

新增一個 use case的步驟：
1. 在 `ApiContainer` 加一個欄位；
2. 在 `_build_use_cases()` 裡用 `parts` 組裝它。
`build_container` 與 `build_test_container` 都會自動帶到，不需改兩次。
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

    # --- repos（14 個，對應 packages/repo/ports.py） ---
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

    # --- 基礎設施 port ---
    storage: StoragePort
    queue: QueuePort
    cache: CachePort
    clock: ClockPort
    tokens: TokenIssuerPort
    oidc: GoogleOidcPort

    # --- use cases（每個一個欄位） ---
    login_with_google: LoginWithGoogle


def _build_use_cases(parts: dict[str, Any]) -> dict[str, Any]:
    """從已組好的 repo / port 組出所有 use case。"""
    return {
        "login_with_google": LoginWithGoogle(
            parts["users"], parts["profiles"], parts["oidc"], parts["tokens"]
        ),
    }


def _assemble(parts: dict[str, Any], overrides: dict[str, Any]) -> ApiContainer:
    """先套用 overrides，再用「被覆蓋後」的元件組 use case。

    這確保被覆蓋的 repo / port 會真的被依賴它的 use case 拿到；
    overrides 也可以直接指定某個 use case，最後再套一次即可覆蓋預設組裝結果。
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
        raise NotImplementedError("R2Storage 於 M5 補上（Task 40）")
    return LocalFileStorage(
        Path(settings.storage_local_root),
        settings.storage_public_base_url,
        settings.storage_signing_secret,
    )


def build_container(settings: ApiSettings | None = None) -> ApiContainer:
    """正式組裝：PostgreSQL repo + Local storage + ARQ + Redis。"""
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
        _env_file=None,  # 測試不讀 .env，保持決定性
        database_url="postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/guru_core_test",
        redis_url="redis://127.0.0.1:6379/15",
        jwt_secret="test-jwt-secret-at-least-32-bytes-long",
        storage_backend="memory",
        storage_public_base_url="http://testserver/v1/files",
        storage_signing_secret="test-storage-secret",
    )


def build_test_container(**overrides: Any) -> ApiContainer:
    """全 Fake 的 container：不碰 DB、Redis、檔案系統、外網。

    任一欄位都可以用 keyword 覆蓋，例如
    `build_test_container(oidc=FakeGoogleOidc(...), clock=FakeClock(...))`。
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
    # tokens 預設綁在預設 clock 上；若呼叫端只覆蓋 clock，重新綁一次才不會用到舊時鐘。
    if "clock" in overrides and "tokens" not in overrides:
        parts["tokens"] = HmacTokenIssuer(
            settings.jwt_secret, settings.jwt_ttl_seconds, overrides["clock"]
        )
    return _assemble(parts, overrides)


def create_asgi_app() -> FastAPI:
    """`cmd/api_server.py` 用的 uvicorn factory。"""
    return create_app(build_container())
