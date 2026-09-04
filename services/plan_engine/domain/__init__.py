"""Plan Engine domain: plan template types and the session state machine."""

from services.plan_engine.domain.capacity import BusyBlock, Capacity, TimeWindow
from services.plan_engine.domain.difficulty import (
    Difficulty,
    DifficultyCoefficients,
    DifficultyConfig,
    Pacing,
    derive,
    load_difficulty_config,
)
from services.plan_engine.domain.errors import IllegalTransition, PlanEngineDomainError
from services.plan_engine.domain.readiness import (
    DomainProbeSpec,
    FollowupOption,
    FollowupQuestion,
    MetricSpec,
    ReadinessConfig,
    ReadinessOutput,
    load_readiness_config,
    readiness_rules,
)
from services.plan_engine.domain.scheduler import (
    PacingViolation,
    ScheduledTask,
    SchedulerConfig,
    ScheduleResult,
    load_scheduler_config,
    schedule,
)
from services.plan_engine.domain.session import (
    TRANSITIONS,
    SessionStatus,
    assert_transition,
    is_terminal,
)
from services.plan_engine.domain.template import (
    DayHint,
    Milestone,
    Phase,
    PlanTemplate,
    PlanTemplateOutput,
    SlotHint,
    TaskType,
    WeeklyItem,
)

__all__ = [
    "TRANSITIONS",
    "BusyBlock",
    "Capacity",
    "DayHint",
    "Difficulty",
    "DifficultyCoefficients",
    "DifficultyConfig",
    "DomainProbeSpec",
    "FollowupOption",
    "FollowupQuestion",
    "IllegalTransition",
    "MetricSpec",
    "Milestone",
    "Pacing",
    "PacingViolation",
    "Phase",
    "PlanEngineDomainError",
    "PlanTemplate",
    "PlanTemplateOutput",
    "ReadinessConfig",
    "ReadinessOutput",
    "ScheduleResult",
    "ScheduledTask",
    "SchedulerConfig",
    "SessionStatus",
    "SlotHint",
    "TaskType",
    "TimeWindow",
    "WeeklyItem",
    "assert_transition",
    "derive",
    "is_terminal",
    "load_difficulty_config",
    "load_readiness_config",
    "load_scheduler_config",
    "readiness_rules",
    "schedule",
]
