"""The single composition root for the Engine.

`EngineContainer` is a frozen dataclass holding settings, the repos this service touches,
the infrastructure ports, the loaded configuration, and **one field per use case**. Adapters
only ever read from the container; they never construct an implementation themselves.

To add a use case:
1. add a field to `EngineContainer`;
2. build it from `parts` in `_build_use_cases()`.
Both `build_container` and `build_test_container` pick it up automatically.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, fields
from datetime import UTC, datetime, timedelta
from typing import Any

from packages.llm.config import LLMConfig, load_llm_config
from packages.llm.factory import build_llm
from packages.llm.fake import FakeLLM
from packages.llm.observability import DbLlmObserver
from packages.llm.ports import LLMPort
from packages.llm.prompts import PromptRegistry
from packages.queue import JobPayload
from packages.repo import (
    DirectionHypothesisRepo,
    DirectionRunRepo,
    DocumentRepo,
    FitVerdictRepo,
    ImportRepo,
    InMemoryDirectionHypothesisRepo,
    InMemoryDirectionRunRepo,
    InMemoryDocumentRepo,
    InMemoryFitVerdictRepo,
    InMemoryImportRepo,
    InMemoryLlmCallRepo,
    InMemoryPlanRepo,
    InMemoryPlanTreeRepo,
    InMemoryProfileRepo,
    InMemoryQuestionAnswerRepo,
    InMemoryQuotaRepo,
    InMemoryReconciliationRepo,
    InMemoryReportRepo,
    InMemoryRoleModelRepo,
    LlmCallRepo,
    PgDirectionHypothesisRepo,
    PgDirectionRunRepo,
    PgDocumentRepo,
    PgFitVerdictRepo,
    PgImportRepo,
    PgLlmCallRepo,
    PgPlanRepo,
    PgPlanTreeRepo,
    PgProfileRepo,
    PgQuestionAnswerRepo,
    PgQuotaRepo,
    PgReconciliationRepo,
    PgReportRepo,
    PgRoleModelRepo,
    PlanRepo,
    PlanTreeRepo,
    ProfileRepo,
    QuestionAnswerRepo,
    QuotaRepo,
    ReconciliationRepo,
    ReportRepo,
    RoleModelRepo,
    build_engine,
    build_session_factory,
)
from services.engine.adapters.queue.consumers import (
    DirectionRunConsumer,
    PlanGenerateConsumer,
    ProfileBuildConsumer,
    ReconcileConsumer,
)
from services.engine.application.build_profile import BuildProfile
from services.engine.application.generate_plan import GeneratePlan
from services.engine.application.ports import ClockPort
from services.engine.application.reconcile import Reconcile
from services.engine.application.run_direction import RunDirection
from services.engine.domain.dimensions import ReportDimensionsConfig, load_dimensions_config
from services.engine.domain.quota import QuotaConfig, load_quota_config
from services.engine.domain.scheduler import SchedulerConfig, load_scheduler_config
from services.engine.settings import EngineSettings

__all__ = [
    "EngineContainer",
    "FakeClock",
    "SystemClock",
    "build_container",
    "build_test_container",
    "create_worker_handlers",
]


class SystemClock:
    """Real clock; always returns a timezone-aware UTC datetime."""

    def now(self) -> datetime:
        return datetime.now(UTC)


class FakeClock:
    """Controllable clock for tests."""

    def __init__(self, start: datetime) -> None:
        if start.tzinfo is None:
            raise ValueError("FakeClock needs a timezone-aware datetime")
        self._now = start

    def now(self) -> datetime:
        return self._now

    def advance(self, *, seconds: float = 0, days: float = 0) -> None:
        self._now += timedelta(seconds=seconds, days=days)


@dataclass(frozen=True)
class EngineContainer:
    settings: EngineSettings

    # --- repos this service touches ---
    runs: DirectionRunRepo
    reports: ReportRepo
    verdicts: FitVerdictRepo
    hypotheses: DirectionHypothesisRepo
    quotas: QuotaRepo
    answers: QuestionAnswerRepo
    profiles: ProfileRepo
    imports: ImportRepo
    documents: DocumentRepo
    role_models: RoleModelRepo
    plans: PlanRepo
    tree: PlanTreeRepo
    reconciliations: ReconciliationRepo
    llm_calls: LlmCallRepo

    # --- infrastructure ports ---
    clock: ClockPort
    llm: LLMPort

    # --- loaded configuration ---
    llm_config: LLMConfig
    dimensions_config: ReportDimensionsConfig
    scheduler_config: SchedulerConfig
    quota_config: QuotaConfig

    # --- use cases (one field each) ---
    build_profile: BuildProfile
    run_direction: RunDirection
    generate_plan: GeneratePlan
    reconcile: Reconcile


def _build_use_cases(parts: dict[str, Any]) -> dict[str, Any]:
    llm_config: LLMConfig = parts["llm_config"]
    max_attempts = llm_config.retry.max_attempts
    return {
        "build_profile": BuildProfile(
            parts["imports"],
            parts["documents"],
            parts["profiles"],
            parts["answers"],
            parts["llm"],
            parts["dimensions_config"],
            max_attempts,
        ),
        "run_direction": RunDirection(
            parts["runs"],
            parts["profiles"],
            parts["imports"],
            parts["documents"],
            parts["reports"],
            parts["verdicts"],
            parts["role_models"],
            parts["answers"],
            parts["llm"],
            parts["dimensions_config"],
            parts["clock"],
            max_attempts,
        ),
        "generate_plan": GeneratePlan(
            parts["plans"],
            parts["tree"],
            parts["hypotheses"],
            parts["verdicts"],
            parts["role_models"],
            parts["quotas"],
            parts["answers"],
            parts["profiles"],
            parts["imports"],
            parts["documents"],
            parts["llm"],
            parts["scheduler_config"],
            parts["quota_config"],
            parts["clock"],
            max_attempts,
        ),
        "reconcile": Reconcile(
            parts["reconciliations"],
            parts["hypotheses"],
            parts["verdicts"],
            parts["role_models"],
            parts["runs"],
            parts["reports"],
            parts["plans"],
            parts["tree"],
            parts["answers"],
            parts["llm"],
            max_attempts,
        ),
    }


def _assemble(parts: dict[str, Any], overrides: dict[str, Any]) -> EngineContainer:
    """Apply overrides first, then build the use cases from the overridden components."""
    known = {f.name for f in fields(EngineContainer)}
    unknown = set(overrides) - known
    if unknown:
        raise TypeError(f"unknown EngineContainer field(s): {sorted(unknown)}")
    merged = parts | overrides
    return EngineContainer(**(merged | _build_use_cases(merged) | overrides))


def _configs() -> dict[str, Any]:
    return {
        "llm_config": load_llm_config(),
        "dimensions_config": load_dimensions_config(),
        "scheduler_config": load_scheduler_config(),
        "quota_config": load_quota_config(),
    }


def build_container(settings: EngineSettings | None = None) -> EngineContainer:
    """Production wiring: PostgreSQL repos and the configured LLM provider."""
    resolved = settings if settings is not None else EngineSettings()
    session_factory = build_session_factory(build_engine(resolved.database_url))
    configs = _configs()
    llm_calls = PgLlmCallRepo(session_factory)
    parts: dict[str, Any] = {
        "settings": resolved,
        "runs": PgDirectionRunRepo(session_factory),
        "reports": PgReportRepo(session_factory),
        "verdicts": PgFitVerdictRepo(session_factory),
        "hypotheses": PgDirectionHypothesisRepo(session_factory),
        "quotas": PgQuotaRepo(session_factory),
        "answers": PgQuestionAnswerRepo(session_factory),
        "profiles": PgProfileRepo(session_factory),
        "imports": PgImportRepo(session_factory),
        "documents": PgDocumentRepo(session_factory),
        "role_models": PgRoleModelRepo(session_factory),
        "plans": PgPlanRepo(session_factory),
        "tree": PgPlanTreeRepo(session_factory),
        "reconciliations": PgReconciliationRepo(session_factory),
        "llm_calls": llm_calls,
        "clock": SystemClock(),
        "llm": build_llm(
            configs["llm_config"],
            PromptRegistry(resolved.prompts_dir),
            DbLlmObserver(llm_calls),
            resolved.llm_fixtures_dir,
        ),
        **configs,
    }
    return _assemble(parts, {})


def build_test_container(**overrides: Any) -> EngineContainer:
    """A fully faked container: no database, no Redis, no network."""
    settings: EngineSettings = overrides.get("settings") or EngineSettings(_env_file=None)
    llm_calls = InMemoryLlmCallRepo()
    parts: dict[str, Any] = {
        "settings": settings,
        "runs": InMemoryDirectionRunRepo(),
        "reports": InMemoryReportRepo(),
        "verdicts": InMemoryFitVerdictRepo(),
        "hypotheses": InMemoryDirectionHypothesisRepo(),
        "quotas": InMemoryQuotaRepo(),
        "answers": InMemoryQuestionAnswerRepo(),
        "profiles": InMemoryProfileRepo(),
        "imports": InMemoryImportRepo(),
        "documents": InMemoryDocumentRepo(),
        "role_models": InMemoryRoleModelRepo(),
        "plans": InMemoryPlanRepo(),
        "tree": InMemoryPlanTreeRepo(),
        "reconciliations": InMemoryReconciliationRepo(),
        "llm_calls": llm_calls,
        "clock": FakeClock(datetime.now(UTC)),
        # The fake reports its calls too, so the observability wiring is exercised by the
        # application suite instead of only by the production container.
        "llm": FakeLLM(settings.llm_fixtures_dir, observer=DbLlmObserver(llm_calls)),
        **_configs(),
    }
    return _assemble(parts, overrides)


def create_worker_handlers(
    container: EngineContainer,
) -> dict[str, Callable[[JobPayload], Awaitable[None]]]:
    """Queue name -> handler map used by `cmd/engine_worker.py`."""
    return {
        "profile.build": ProfileBuildConsumer(container.build_profile),
        "direction.run": DirectionRunConsumer(container.run_direction),
        "plan.generate": PlanGenerateConsumer(container.generate_plan),
        "reconcile.run": ReconcileConsumer(container.reconcile),
    }
