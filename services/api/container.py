"""The single composition root for the API service.

`ApiContainer` is a frozen dataclass holding settings, the repos, the infrastructure ports,
and **one field per use case**. Adapters only ever read from the container; they never
construct an implementation themselves.

To add a use case:
1. add a field to `ApiContainer`;
2. build it from `parts` in `_build_use_cases()`.
Both `build_container` and `build_test_container` pick it up automatically, so there is no
second place to update.

Application modules are grouped by station — `direction`, `questions`, `hypotheses`,
`plans`, `checkins`, `exports`, `reconciliations` — because the use cases inside one station
share their view models, and splitting them would only mean importing sideways.
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
    DirectionHypothesisRepo,
    DirectionRunRepo,
    DocumentRepo,
    FitVerdictRepo,
    ImportRepo,
    InMemoryCheckinRepo,
    InMemoryDirectionHypothesisRepo,
    InMemoryDirectionRunRepo,
    InMemoryDocumentRepo,
    InMemoryFitVerdictRepo,
    InMemoryImportRepo,
    InMemoryOAuthConnectionRepo,
    InMemoryPlanExportRepo,
    InMemoryPlanRepo,
    InMemoryPlanTreeRepo,
    InMemoryProfileRepo,
    InMemoryQuestionAnswerRepo,
    InMemoryQuotaRepo,
    InMemoryReconciliationRepo,
    InMemoryReportRepo,
    InMemoryRoleModelRepo,
    InMemoryUserRepo,
    OAuthConnectionRepo,
    PgCheckinRepo,
    PgDirectionHypothesisRepo,
    PgDirectionRunRepo,
    PgDocumentRepo,
    PgFitVerdictRepo,
    PgImportRepo,
    PgOAuthConnectionRepo,
    PgPlanExportRepo,
    PgPlanRepo,
    PgPlanTreeRepo,
    PgProfileRepo,
    PgQuestionAnswerRepo,
    PgQuotaRepo,
    PgReconciliationRepo,
    PgReportRepo,
    PgRoleModelRepo,
    PgUserRepo,
    PlanExportRepo,
    PlanRepo,
    PlanTreeRepo,
    ProfileRepo,
    QuestionAnswerRepo,
    QuotaRepo,
    ReconciliationRepo,
    ReportRepo,
    RoleModelRepo,
    UserRepo,
    build_engine,
    build_session_factory,
)
from packages.storage import InMemoryStorage, LocalFileStorage, R2Storage, StoragePort
from services.api.adapters.clock import FakeClock, SystemClock
from services.api.adapters.crypto import FernetTokenCipher, PlainTokenCipher
from services.api.adapters.google.calendar import FakeCalendar, GoogleCalendar
from services.api.adapters.google.oauth import FakeOAuth, GoogleOAuth
from services.api.adapters.google.oidc import FakeGoogleOidc, GoogleOidc
from services.api.adapters.http.app import create_app
from services.api.adapters.jwt_issuer import HmacTokenIssuer
from services.api.adapters.queue.export_consumer import ExportPushConsumer
from services.api.adapters.queue.import_consumer import ImportParseConsumer
from services.api.application.authorize_integration import AuthorizeIntegration
from services.api.application.catalog import AuthorRoleModel, ListRoleModels
from services.api.application.checkins import ListCheckins, SubmitCheckin
from services.api.application.complete_import import CompleteImport
from services.api.application.complete_integration import CompleteIntegration
from services.api.application.direction import (
    GetDirectionRun,
    ReadProfile,
    StartDirectionRun,
)
from services.api.application.disconnect_integration import DisconnectIntegration
from services.api.application.exports import (
    GetExportStatus,
    PushExport,
    RequestExport,
    UnexportPlan,
)
from services.api.application.get_job import GetJob
from services.api.application.google_access_token import GoogleAccessTokenProvider
from services.api.application.hypotheses import (
    CreateHypothesis,
    GetHypothesis,
    ListHypotheses,
)
from services.api.application.import_google_calendar import ImportGoogleCalendar
from services.api.application.list_imports import ListImports
from services.api.application.list_integrations import ListIntegrations
from services.api.application.login_with_google import LoginWithGoogle
from services.api.application.parse_import import ParseImport
from services.api.application.plans import (
    GetPlan,
    ListPlans,
    ListPlanTasks,
    SetPlanStatus,
    UpdateTaskStatus,
)
from services.api.application.ports import (
    CalendarPort,
    ClockPort,
    GoogleOAuthPort,
    GoogleOidcPort,
    TokenCipherPort,
    TokenIssuerPort,
)
from services.api.application.presign_import import PresignImport
from services.api.application.questions import AnswerQuestion, GetQuota, ListQuestions
from services.api.application.reconciliations import (
    DecideReconciliation,
    GetReconciliation,
    StartReconciliation,
)
from services.api.domain.calendar_mapping import load_color_map
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

    # --- repos ---
    users: UserRepo
    profiles: ProfileRepo
    oauth_connections: OAuthConnectionRepo
    imports: ImportRepo
    documents: DocumentRepo
    runs: DirectionRunRepo
    reports: ReportRepo
    verdicts: FitVerdictRepo
    role_models: RoleModelRepo
    question_answers: QuestionAnswerRepo
    quotas: QuotaRepo
    hypotheses: DirectionHypothesisRepo
    plans: PlanRepo
    tree: PlanTreeRepo
    checkins: CheckinRepo
    plan_exports: PlanExportRepo
    reconciliations: ReconciliationRepo

    # --- infrastructure ports ---
    storage: StoragePort
    queue: QueuePort
    parsers: ParserRegistry
    cache: CachePort
    clock: ClockPort
    tokens: TokenIssuerPort
    oidc: GoogleOidcPort
    google_oauth: GoogleOAuthPort
    calendar: CalendarPort
    cipher: TokenCipherPort

    # --- use cases (one field each) ---
    login_with_google: LoginWithGoogle
    read_profile: ReadProfile
    presign_import: PresignImport
    complete_import: CompleteImport
    list_imports: ListImports
    parse_import: ParseImport
    import_google_calendar: ImportGoogleCalendar
    google_token_provider: GoogleAccessTokenProvider
    authorize_integration: AuthorizeIntegration
    complete_integration: CompleteIntegration
    list_integrations: ListIntegrations
    disconnect_integration: DisconnectIntegration
    start_direction_run: StartDirectionRun
    get_direction_run: GetDirectionRun
    list_questions: ListQuestions
    answer_question: AnswerQuestion
    get_quota: GetQuota
    list_role_models: ListRoleModels
    author_role_model: AuthorRoleModel
    create_hypothesis: CreateHypothesis
    list_hypotheses: ListHypotheses
    get_hypothesis: GetHypothesis
    list_plans: ListPlans
    get_plan: GetPlan
    set_plan_status: SetPlanStatus
    list_plan_tasks: ListPlanTasks
    update_task_status: UpdateTaskStatus
    submit_checkin: SubmitCheckin
    list_checkins: ListCheckins
    request_export: RequestExport
    push_export: PushExport
    get_export_status: GetExportStatus
    unexport_plan: UnexportPlan
    start_reconciliation: StartReconciliation
    get_reconciliation: GetReconciliation
    decide_reconciliation: DecideReconciliation
    get_job: GetJob


def _build_use_cases(parts: dict[str, Any]) -> dict[str, Any]:
    """Build every use case from the already-assembled repos and ports."""
    get_plan = GetPlan(parts["plans"], parts["tree"])
    # Shared by every Google-facing use case so they hit one cache entry, not several.
    google_token_provider = GoogleAccessTokenProvider(
        parts["oauth_connections"],
        parts["google_oauth"],
        parts["cipher"],
        parts["cache"],
        parts["clock"],
    )
    return {
        "login_with_google": LoginWithGoogle(
            parts["users"], parts["profiles"], parts["oidc"], parts["tokens"]
        ),
        "read_profile": ReadProfile(parts["profiles"]),
        "presign_import": PresignImport(parts["imports"], parts["storage"]),
        "complete_import": CompleteImport(
            parts["imports"], parts["documents"], parts["storage"], parts["queue"]
        ),
        "list_imports": ListImports(parts["imports"], parts["documents"]),
        "parse_import": ParseImport(
            parts["imports"],
            parts["documents"],
            parts["storage"],
            parts["parsers"],
            parts["queue"],
        ),
        "import_google_calendar": ImportGoogleCalendar(
            parts["imports"],
            parts["documents"],
            parts["calendar"],
            google_token_provider,
            parts["clock"],
            parts["queue"],
        ),
        "google_token_provider": google_token_provider,
        "authorize_integration": AuthorizeIntegration(parts["google_oauth"]),
        "complete_integration": CompleteIntegration(
            parts["oauth_connections"], parts["google_oauth"], parts["cipher"]
        ),
        "list_integrations": ListIntegrations(parts["oauth_connections"]),
        "disconnect_integration": DisconnectIntegration(
            parts["oauth_connections"],
            parts["google_oauth"],
            parts["cipher"],
            parts["cache"],
            parts["clock"],
        ),
        "start_direction_run": StartDirectionRun(parts["runs"], parts["profiles"], parts["queue"]),
        "get_direction_run": GetDirectionRun(
            parts["runs"], parts["reports"], parts["verdicts"], parts["role_models"]
        ),
        "list_questions": ListQuestions(parts["question_answers"]),
        "answer_question": AnswerQuestion(
            parts["question_answers"], parts["quotas"], parts["queue"], parts["clock"]
        ),
        "get_quota": GetQuota(parts["quotas"]),
        "list_role_models": ListRoleModels(parts["role_models"]),
        "author_role_model": AuthorRoleModel(parts["role_models"]),
        "create_hypothesis": CreateHypothesis(
            parts["hypotheses"],
            parts["verdicts"],
            parts["role_models"],
            parts["quotas"],
            parts["question_answers"],
            parts["plans"],
            parts["queue"],
            parts["clock"],
        ),
        "list_hypotheses": ListHypotheses(
            parts["hypotheses"], parts["role_models"], parts["plans"]
        ),
        "get_hypothesis": GetHypothesis(parts["hypotheses"], parts["role_models"], parts["plans"]),
        "list_plans": ListPlans(parts["plans"], parts["tree"]),
        "get_plan": get_plan,
        "set_plan_status": SetPlanStatus(parts["plans"], get_plan, parts["clock"]),
        "list_plan_tasks": ListPlanTasks(get_plan, parts["tree"]),
        "update_task_status": UpdateTaskStatus(
            get_plan,
            parts["tree"],
            parts["plan_exports"],
            parts["queue"],
            parts["clock"],
        ),
        "submit_checkin": SubmitCheckin(
            get_plan,
            parts["tree"],
            parts["checkins"],
            parts["plan_exports"],
            parts["queue"],
            parts["clock"],
        ),
        "list_checkins": ListCheckins(get_plan, parts["checkins"]),
        "request_export": RequestExport(
            parts["plans"], parts["plan_exports"], parts["queue"], google_token_provider
        ),
        "push_export": PushExport(
            parts["plans"],
            parts["tree"],
            parts["plan_exports"],
            parts["calendar"],
            google_token_provider,
            load_color_map(),
            parts["clock"],
        ),
        "get_export_status": GetExportStatus(parts["plans"], parts["plan_exports"], parts["tree"]),
        "unexport_plan": UnexportPlan(
            parts["plans"],
            parts["tree"],
            parts["plan_exports"],
            parts["calendar"],
            google_token_provider,
        ),
        "start_reconciliation": StartReconciliation(
            parts["reconciliations"], parts["hypotheses"], parts["queue"], parts["clock"]
        ),
        "get_reconciliation": GetReconciliation(parts["reconciliations"]),
        "decide_reconciliation": DecideReconciliation(
            parts["reconciliations"],
            parts["hypotheses"],
            parts["quotas"],
            parts["question_answers"],
            parts["clock"],
        ),
        "get_job": GetJob(parts["cache"], parts["queue"]),
    }


def _assemble(parts: dict[str, Any], overrides: dict[str, Any]) -> ApiContainer:
    """Apply overrides first, then build the use cases from the overridden components.

    This guarantees an overridden repo or port actually reaches the use cases that depend on
    it. Overrides may also name a use case directly; applying them once more at the end lets
    that win over the default wiring.
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


def _build_oidc(settings: ApiSettings) -> GoogleOidcPort:
    """Pick the sign-in adapter. `allow_fake_login` lets anyone log in as anyone.

    It exists so `scripts/smoke.sh` can walk the happy path on a developer machine with no
    Google credentials. Never enable it anywhere reachable from outside that machine.
    """
    if settings.allow_fake_login:
        return FakeGoogleOidc(derive_from_code=True)
    return GoogleOidc(settings.google_client_id, settings.google_client_secret)


def build_container(settings: ApiSettings | None = None) -> ApiContainer:
    """Production wiring: PostgreSQL repos + local storage + ARQ + Redis."""
    resolved = settings if settings is not None else ApiSettings()
    if not resolved.oauth_token_enc_key:
        raise ValueError(
            "OAUTH_TOKEN_ENC_KEY must be set: refresh tokens are never stored unencrypted. "
            'Generate one with `python -c "from cryptography.fernet import Fernet; '
            'print(Fernet.generate_key().decode())"`.'
        )
    session_factory = build_session_factory(build_engine(resolved.database_url))
    clock: ClockPort = SystemClock()
    parts: dict[str, Any] = {
        "settings": resolved,
        "users": PgUserRepo(session_factory),
        "profiles": PgProfileRepo(session_factory),
        "oauth_connections": PgOAuthConnectionRepo(session_factory),
        "imports": PgImportRepo(session_factory),
        "documents": PgDocumentRepo(session_factory),
        "runs": PgDirectionRunRepo(session_factory),
        "reports": PgReportRepo(session_factory),
        "verdicts": PgFitVerdictRepo(session_factory),
        "role_models": PgRoleModelRepo(session_factory),
        "question_answers": PgQuestionAnswerRepo(session_factory),
        "quotas": PgQuotaRepo(session_factory),
        "hypotheses": PgDirectionHypothesisRepo(session_factory),
        "plans": PgPlanRepo(session_factory),
        "tree": PgPlanTreeRepo(session_factory),
        "checkins": PgCheckinRepo(session_factory),
        "plan_exports": PgPlanExportRepo(session_factory),
        "reconciliations": PgReconciliationRepo(session_factory),
        "storage": _build_storage(resolved),
        "parsers": default_registry(),
        "queue": ArqQueue(resolved.redis_url),
        "cache": RedisCache(resolved.redis_url),
        "clock": clock,
        "tokens": HmacTokenIssuer(resolved.jwt_secret, resolved.jwt_ttl_seconds, clock),
        "oidc": _build_oidc(resolved),
        "google_oauth": GoogleOAuth(
            resolved.google_client_id,
            resolved.google_client_secret,
            resolved.google_redirect_uri,
        ),
        "calendar": GoogleCalendar(),
        "cipher": FernetTokenCipher(resolved.oauth_token_enc_key),
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
        oauth_token_enc_key="test-oauth-token-enc-key",
        # Off by default so the test suite is never throttled; tests that exercise the
        # limiter pass their own settings with a positive budget.
        rate_limit_per_minute=0,
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
        "runs": InMemoryDirectionRunRepo(),
        "reports": InMemoryReportRepo(),
        "verdicts": InMemoryFitVerdictRepo(),
        "role_models": InMemoryRoleModelRepo(),
        "question_answers": InMemoryQuestionAnswerRepo(),
        "quotas": InMemoryQuotaRepo(),
        "hypotheses": InMemoryDirectionHypothesisRepo(),
        "plans": InMemoryPlanRepo(),
        "tree": InMemoryPlanTreeRepo(),
        "checkins": InMemoryCheckinRepo(),
        "plan_exports": InMemoryPlanExportRepo(),
        "reconciliations": InMemoryReconciliationRepo(),
        "storage": InMemoryStorage(),
        "parsers": default_registry(),
        "queue": InMemoryQueue(),
        "cache": DictCache(),
        "clock": clock,
        "tokens": HmacTokenIssuer(settings.jwt_secret, settings.jwt_ttl_seconds, clock),
        "oidc": FakeGoogleOidc(),
        "google_oauth": FakeOAuth(),
        "calendar": FakeCalendar(),
        "cipher": PlainTokenCipher(),
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
        "export.push": ExportPushConsumer(container.push_export),
    }
