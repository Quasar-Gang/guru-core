"""The single composition root for the Plan Engine.

`PlanEngineContainer` is a frozen dataclass holding settings, the repos this service reads
and writes, the infrastructure ports, the loaded configuration, and **one field per use
case**. Adapters only ever read from the container; they never construct an implementation.

To add a use case:
1. add a field to `PlanEngineContainer`;
2. build it from `parts` in `_build_use_cases()`.
Both `build_container` and `build_test_container` pick it up automatically.
"""

from dataclasses import dataclass, field, fields
from datetime import UTC, datetime, timedelta
from typing import Any

from packages.cache import CachePort, DictCache, RedisCache
from packages.llm.config import LLMConfig, load_llm_config
from packages.llm.factory import build_llm
from packages.llm.fake import FakeLLM
from packages.llm.observability import NullObserver
from packages.llm.ports import LLMPort
from packages.llm.prompts import PromptRegistry
from packages.repo import (
    DocumentRepo,
    FollowupRoundRepo,
    InMemoryDocumentRepo,
    InMemoryFollowupRoundRepo,
    InMemoryLlmCallRepo,
    InMemoryPlanRepo,
    InMemoryPlanRevisionRepo,
    InMemoryPlanSessionRepo,
    InMemoryPlanTaskRepo,
    InMemoryProfileRepo,
    InMemoryRoleModelRepo,
    LlmCallRepo,
    PgDocumentRepo,
    PgFollowupRoundRepo,
    PgLlmCallRepo,
    PgPlanRepo,
    PgPlanRevisionRepo,
    PgPlanSessionRepo,
    PgPlanTaskRepo,
    PgProfileRepo,
    PgRoleModelRepo,
    PlanRepo,
    PlanRevisionRepo,
    PlanSessionRepo,
    PlanTaskRepo,
    ProfileRepo,
    RoleModelRepo,
    build_engine,
    build_session_factory,
)
from services.plan_engine.application.context_builder import ContextBuilder
from services.plan_engine.application.evaluate_session import EvaluateSession
from services.plan_engine.application.generate_plans import GeneratePlans
from services.plan_engine.application.ports import (
    ClockPort,
    NullRoleModelRenderer,
    RoleModelRendererPort,
)
from services.plan_engine.domain.difficulty import DifficultyConfig, load_difficulty_config
from services.plan_engine.domain.readiness import ReadinessConfig, load_readiness_config
from services.plan_engine.domain.scheduler import SchedulerConfig, load_scheduler_config
from services.plan_engine.settings import PlanEngineSettings

__all__ = [
    "FakeClock",
    "PlanEngineContainer",
    "SystemClock",
    "build_container",
    "build_test_container",
]


class SystemClock:
    """Real clock; always returns a timezone-aware UTC datetime."""

    def now(self) -> datetime:
        return datetime.now(UTC)


class FakeClock:
    """Controllable clock for tests.

    Both clocks live here rather than in `adapters/`: the Plan Engine grows its adapters
    package in Task 24 (the ARQ consumers), and they will move there with it.
    """

    def __init__(self, start: datetime) -> None:
        if start.tzinfo is None:
            raise ValueError("FakeClock needs a timezone-aware datetime")
        self._now = start

    def now(self) -> datetime:
        return self._now

    def advance(self, *, seconds: float = 0, days: float = 0) -> None:
        self._now += timedelta(seconds=seconds, days=days)


@dataclass(frozen=True)
class PlanEngineContainer:
    settings: PlanEngineSettings

    # --- repos this service touches ---
    sessions: PlanSessionRepo
    followups: FollowupRoundRepo
    plans: PlanRepo
    plan_tasks: PlanTaskRepo
    plan_revisions: PlanRevisionRepo
    documents: DocumentRepo
    role_models: RoleModelRepo
    profiles: ProfileRepo
    llm_calls: LlmCallRepo

    # --- infrastructure ports ---
    cache: CachePort
    clock: ClockPort
    llm: LLMPort
    renderer: RoleModelRendererPort

    # --- loaded configuration ---
    llm_config: LLMConfig
    readiness_config: ReadinessConfig
    difficulty_config: DifficultyConfig
    scheduler_config: SchedulerConfig

    # --- collaborators ---
    context_builder: ContextBuilder

    # --- use cases (one field each) ---
    evaluate_session: EvaluateSession
    generate_plans: GeneratePlans

    #: Task 36 fills this in with `RevisePlan`; kept here so the wiring has one home.
    revise_plan: object | None = field(default=None)


def _build_use_cases(parts: dict[str, Any]) -> dict[str, Any]:
    """Build the collaborators and use cases from the already-assembled repos and ports."""
    llm_config: LLMConfig = parts["llm_config"]
    max_attempts = llm_config.retry.max_attempts
    context_builder = ContextBuilder(
        parts["sessions"],
        parts["profiles"],
        parts["documents"],
        parts["followups"],
        parts["role_models"],
        parts["renderer"],
        parts["readiness_config"],
        budgets=llm_config.budgets,
    )
    generate_plans = GeneratePlans(
        parts["sessions"],
        parts["plans"],
        parts["plan_tasks"],
        parts["documents"],
        parts["role_models"],
        context_builder,
        parts["llm"],
        parts["difficulty_config"],
        parts["scheduler_config"],
        parts["clock"],
        max_attempts,
    )
    evaluate_session = EvaluateSession(
        parts["sessions"],
        parts["followups"],
        context_builder,
        parts["llm"],
        parts["readiness_config"],
        generate_plans,
        parts["cache"],
        max_attempts,
    )
    return {
        "context_builder": context_builder,
        "generate_plans": generate_plans,
        "evaluate_session": evaluate_session,
    }


def _assemble(parts: dict[str, Any], overrides: dict[str, Any]) -> PlanEngineContainer:
    """Apply overrides first, then build the use cases from the overridden components.

    This guarantees an overridden repo or port actually reaches the use cases that depend on
    it. Overrides may also name a use case directly; applying them once more at the end lets
    that win over the default wiring.
    """
    known = {f.name for f in fields(PlanEngineContainer)}
    unknown = set(overrides) - known
    if unknown:
        raise TypeError(f"unknown PlanEngineContainer field(s): {sorted(unknown)}")
    merged = parts | overrides
    return PlanEngineContainer(**(merged | _build_use_cases(merged) | overrides))


def _configs() -> dict[str, Any]:
    return {
        "llm_config": load_llm_config(),
        "readiness_config": load_readiness_config(),
        "difficulty_config": load_difficulty_config(),
        "scheduler_config": load_scheduler_config(),
    }


def build_container(settings: PlanEngineSettings | None = None) -> PlanEngineContainer:
    """Production wiring: PostgreSQL repos + Redis cache + the configured LLM provider."""
    resolved = settings if settings is not None else PlanEngineSettings()
    session_factory = build_session_factory(build_engine(resolved.database_url))
    configs = _configs()
    llm_config: LLMConfig = configs["llm_config"]
    parts: dict[str, Any] = {
        "settings": resolved,
        "sessions": PgPlanSessionRepo(session_factory),
        "followups": PgFollowupRoundRepo(session_factory),
        "plans": PgPlanRepo(session_factory),
        "plan_tasks": PgPlanTaskRepo(session_factory),
        "plan_revisions": PgPlanRevisionRepo(session_factory),
        "documents": PgDocumentRepo(session_factory),
        "role_models": PgRoleModelRepo(session_factory),
        "profiles": PgProfileRepo(session_factory),
        "llm_calls": PgLlmCallRepo(session_factory),
        "cache": RedisCache(resolved.redis_url),
        "clock": SystemClock(),
        "llm": build_llm(
            llm_config,
            PromptRegistry(resolved.prompts_dir),
            NullObserver(),
            resolved.llm_fixtures_dir,
        ),
        # Task 29 replaces this with an adapter over the Role Model service; a direct import
        # of `services.role_model` would break the "services must not import each other"
        # contract, so the port stays no-op until that adapter exists.
        "renderer": NullRoleModelRenderer(),
        **configs,
    }
    return _assemble(parts, {})


def _test_settings() -> PlanEngineSettings:
    return PlanEngineSettings(
        _env_file=None,  # tests never read .env, so results stay deterministic
        database_url="postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/guru_core_test",
        redis_url="redis://127.0.0.1:6379/15",
    )


def build_test_container(**overrides: Any) -> PlanEngineContainer:
    """A fully faked container: no DB, Redis, filesystem writes, or network access.

    Any field can be replaced by keyword, e.g. `build_test_container(llm=FakeLLM(...))`.
    """
    settings: PlanEngineSettings = overrides.get("settings") or _test_settings()
    parts: dict[str, Any] = {
        "settings": settings,
        "sessions": InMemoryPlanSessionRepo(),
        "followups": InMemoryFollowupRoundRepo(),
        "plans": InMemoryPlanRepo(),
        "plan_tasks": InMemoryPlanTaskRepo(),
        "plan_revisions": InMemoryPlanRevisionRepo(),
        "documents": InMemoryDocumentRepo(),
        "role_models": InMemoryRoleModelRepo(),
        "profiles": InMemoryProfileRepo(),
        "llm_calls": InMemoryLlmCallRepo(),
        "cache": DictCache(),
        "clock": FakeClock(datetime.now(UTC)),
        "llm": FakeLLM(settings.llm_fixtures_dir),
        "renderer": NullRoleModelRenderer(),
        **_configs(),
    }
    return _assemble(parts, overrides)
