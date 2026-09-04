"""Turn one session into three draft plans, one per difficulty (PRD 4.3, 7.5, 7.6).

The LLM produces a single baseline template with relative timing; this use case derives the
easy / hard / extremely_hard variants from the coefficients, expands each into absolutely
timed tasks with the deterministic scheduler, and stores the three plans.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from packages.llm.ports import LLMPort, Purpose
from packages.llm.validation import BusinessRule, complete_validated
from packages.repo.entities import NewPlan, NewPlanTask
from packages.repo.ports import (
    DocumentRepo,
    PlanRepo,
    PlanSessionRepo,
    PlanTaskRepo,
    RoleModelRepo,
)
from services.plan_engine.application.context_builder import ContextBuilder, SessionContext
from services.plan_engine.application.ports import ClockPort
from services.plan_engine.domain.capacity import BusyBlock
from services.plan_engine.domain.difficulty import Difficulty, DifficultyConfig, derive
from services.plan_engine.domain.scheduler import (
    ScheduledTask,
    SchedulerConfig,
    ScheduleResult,
    schedule,
)
from services.plan_engine.domain.session import SessionStatus, assert_transition
from services.plan_engine.domain.template import (
    Milestone,
    Phase,
    PlanTemplate,
    PlanTemplateOutput,
    WeeklyItem,
)

__all__ = ["GeneratePlans"]

_DAYS_PER_WEEK = 7

# --- conservative defaults for the degraded path (PRD 7.5) ---
_FALLBACK_WEEKS = 12
_FALLBACK_PHASES = 3
_FALLBACK_TIMES_PER_WEEK = 3
_FALLBACK_MINUTES = 40
_TITLE_MAX_CHARS = 20

# End-user facing product strings; kept in Chinese on purpose (global constraint 19).
_SYSTEM_ASSUMPTION_HEADER = "以下項目為系統假設，建議補完後重新規劃"
_NO_CALENDAR_ASSUMPTION = "未參考既有行事曆，只依你宣告的可用時段排程"
_DEGRADED_ASSUMPTION = "模型輸出多次未通過檢查，已改用系統保守預設產生此計畫"
_FALLBACK_PHASE_NAMES = ("基礎期", "強化期", "鞏固期")
_FALLBACK_PHASE_FOCUS = ("建立習慣與基本量", "逐步加量與提升強度", "穩定表現並驗收成果")
_FALLBACK_SUCCESS_CRITERION = "完成計畫中 80% 以上的任務"
_FALLBACK_ITEM_TITLE = "固定練習"
_FALLBACK_ITEM_DESCRIPTION = "依目標進行一次固定練習"
_MISSING_ASSUMPTION = "缺少「{item}」，以最保守的預設值代替"
_UNPLACED_ASSUMPTION = "「{key}」有部分次數排不進可用時段，已略過那幾次"


class GeneratePlans:
    """The ``generating`` step of the session state machine."""

    def __init__(
        self,
        sessions: PlanSessionRepo,
        plans: PlanRepo,
        plan_tasks: PlanTaskRepo,
        documents: DocumentRepo,
        role_models: RoleModelRepo,
        context_builder: ContextBuilder,
        llm: LLMPort,
        difficulty_config: DifficultyConfig,
        scheduler_config: SchedulerConfig,
        clock: ClockPort,
        max_attempts: int,
    ) -> None:
        self._sessions = sessions
        self._plans = plans
        self._plan_tasks = plan_tasks
        # documents / role_models are part of the mandated signature: everything they hold
        # reaches this use case through ContextBuilder today, and the revision use case
        # (Task 36) will read them here directly.
        self._documents = documents
        self._role_models = role_models
        self._context_builder = context_builder
        self._llm = llm
        self._difficulty_config = difficulty_config
        self._scheduler_config = scheduler_config
        self._clock = clock
        self._max_attempts = max_attempts

    async def __call__(
        self,
        session_id: UUID,
        *,
        forced_missing: Sequence[str] = (),
        degraded: bool = False,
    ) -> list[UUID]:
        session = await self._sessions.get_unscoped(session_id)
        if session is None:
            raise LookupError(f"unknown plan session {session_id}")
        try:
            # PRD 3.1: only a session in `generating` may reach `done`.
            assert_transition(SessionStatus(session.status), SessionStatus.done)
            context = await self._context_builder.build(session_id, Purpose.generate)
            await self._sessions.set_context_snapshot(session_id, context.model_dump(mode="json"))
            start_date = self._start_date(context.timezone)
            busy = _busy_blocks(context)

            outcome = await complete_validated(
                self._llm,
                "generate_plans",
                context.to_prompt_context()
                | {
                    "forced_missing": list(forced_missing),
                    "default_duration_weeks": _FALLBACK_WEEKS,
                },
                PlanTemplateOutput,
                Purpose.generate,
                max_attempts=self._max_attempts,
                rules=[self._schedulable_rule(context, start_date, busy)],
                fallback=lambda _violations: PlanTemplateOutput(
                    template=_conservative_template(context.goal)
                ),
            )
            baseline = outcome.value.template
            shared = _shared_assumptions(
                baseline, context, forced_missing, degraded or outcome.degraded
            )

            new_plans: list[NewPlan] = []
            task_sets: list[list[ScheduledTask]] = []
            for difficulty in (Difficulty.easy, Difficulty.hard, Difficulty.extremely_hard):
                variant = derive(baseline, difficulty, self._difficulty_config, context.pacing)
                result = self._schedule(variant, context, start_date, busy)
                assumptions = _dedupe(
                    [
                        *shared,
                        *(_UNPLACED_ASSUMPTION.format(key=key) for key in result.unplaced),
                    ]
                )
                new_plans.append(
                    NewPlan(
                        user_id=session.user_id,
                        session_id=session_id,
                        title=variant.title,
                        difficulty=difficulty.value,
                        status="draft",
                        goal_statement=baseline.goal_statement,
                        duration_weeks=variant.duration_weeks,
                        start_date=start_date,
                        deadline=_deadline(start_date, variant.duration_weeks),
                        template=variant.model_dump(mode="json"),
                        structure={
                            "phases": [phase.model_dump(mode="json") for phase in variant.phases],
                            "success_criteria": list(baseline.success_criteria),
                            "assumptions": assumptions,
                        },
                    )
                )
                task_sets.append(result.tasks)

            created = await self._plans.create_many(new_plans)
            for plan, tasks in zip(created, task_sets, strict=True):
                await self._plan_tasks.replace_all(plan.id, [_new_task(task) for task in tasks])

            await self._sessions.set_status(session_id, SessionStatus.done.value)
            return [plan.id for plan in created]
        except Exception as exc:
            await self._fail(session_id, exc)
            raise

    # ------------------------------------------------------------------ business rule

    def _schedulable_rule(
        self,
        context: SessionContext,
        start_date: date,
        busy: Sequence[BusyBlock],
    ) -> BusinessRule:
        """PRD 7.5's business-rule check: a well-formed template can still be unschedulable.

        The template is scheduled at the ``hard`` coefficients (the baseline, 1.0 across the
        board) against the trait pacing. ``derive`` is deliberately called with no pacing:
        it would clamp the frequency into the allowed range and hide the very breach we want
        to feed back to the model.
        """

        def rule(output: Any) -> list[str]:
            if not isinstance(output, PlanTemplateOutput):
                return []
            variant = derive(output.template, Difficulty.hard, self._difficulty_config, None)
            result = self._schedule(variant, context, start_date, busy)
            return [
                *(violation.detail for violation in result.violations),
                *(
                    f"{key} could not be placed in any available time window"
                    for key in result.unplaced
                ),
            ]

        return rule

    # ----------------------------------------------------------------------- helpers

    def _schedule(
        self,
        template: PlanTemplate,
        context: SessionContext,
        start_date: date,
        busy: Sequence[BusyBlock],
    ) -> ScheduleResult:
        return schedule(
            template,
            start_date=start_date,
            capacity=context.capacity,
            busy=busy,
            pacing=context.pacing,
            config=self._scheduler_config,
        )

    def _start_date(self, timezone: str) -> date:
        """The plan start, in the user's local calendar (``config/scheduler.yaml``)."""
        today = self._clock.now().astimezone(ZoneInfo(timezone)).date()
        if self._scheduler_config.default_start == "tomorrow":
            return today + timedelta(days=1)
        return today + timedelta(days=(-today.weekday()) % _DAYS_PER_WEEK or _DAYS_PER_WEEK)

    async def _fail(self, session_id: UUID, exc: Exception) -> None:
        """Record the failure, unless the session is already in a terminal state."""
        session = await self._sessions.get_unscoped(session_id)
        if session is None or session.status in (SessionStatus.done, SessionStatus.failed):
            return
        await self._sessions.set_status(session_id, SessionStatus.failed.value, str(exc))


def _busy_blocks(context: SessionContext) -> list[BusyBlock]:
    """Existing commitments the scheduler must avoid; all-day events block nothing."""
    blocks: list[BusyBlock] = []
    for event in context.existing_events:
        if event.all_day:
            continue
        try:
            blocks.append(BusyBlock(start_at=event.start_at, end_at=event.end_at))
        except ValueError:
            continue
    return blocks


def _deadline(start_date: date, duration_weeks: int) -> date:
    """The authoritative end date: the last day of the last week."""
    return start_date + timedelta(days=duration_weeks * _DAYS_PER_WEEK - 1)


def _shared_assumptions(
    baseline: PlanTemplate,
    context: SessionContext,
    forced_missing: Sequence[str],
    degraded: bool,
) -> list[str]:
    """The assumptions every difficulty shares (PRD 3.3, 3.4, 7.5)."""
    assumptions = list(baseline.assumptions)
    if not context.use_calendar:
        assumptions.append(_NO_CALENDAR_ASSUMPTION)
    if forced_missing or degraded:
        assumptions.append(_SYSTEM_ASSUMPTION_HEADER)
    assumptions.extend(_MISSING_ASSUMPTION.format(item=item) for item in forced_missing)
    if degraded:
        assumptions.append(_DEGRADED_ASSUMPTION)
    return _dedupe(assumptions)


def _dedupe(items: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    kept: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            kept.append(item)
    return kept


def _new_task(task: ScheduledTask) -> NewPlanTask:
    return NewPlanTask(**task.model_dump())


def _conservative_template(goal: str) -> PlanTemplate:
    """The degraded default of PRD 7.5: 3 x 40 minutes a week, three phases, twelve weeks."""
    weeks_per_phase = _FALLBACK_WEEKS // _FALLBACK_PHASES
    return PlanTemplate(
        title=_shorten(goal, _TITLE_MAX_CHARS),
        goal_statement=goal,
        duration_weeks=_FALLBACK_WEEKS,
        assumptions=[_SYSTEM_ASSUMPTION_HEADER],
        success_criteria=[_FALLBACK_SUCCESS_CRITERION],
        phases=[
            Phase(
                index=index,
                name=_FALLBACK_PHASE_NAMES[index],
                week_start=index * weeks_per_phase,
                week_end=(index + 1) * weeks_per_phase - 1,
                focus=_FALLBACK_PHASE_FOCUS[index],
                milestone=Milestone(
                    title=f"{_FALLBACK_PHASE_NAMES[index]}檢核",
                    metric=_FALLBACK_PHASE_FOCUS[index],
                ),
            )
            for index in range(_FALLBACK_PHASES)
        ],
        weekly_template=[
            WeeklyItem(
                key="core_session",
                title=_FALLBACK_ITEM_TITLE,
                task_type="session",
                day_hint="any",
                slot_hint="any",
                duration_minutes=_FALLBACK_MINUTES,
                description=_FALLBACK_ITEM_DESCRIPTION,
                times_per_week=_FALLBACK_TIMES_PER_WEEK,
            )
        ],
    )


def _shorten(text: str, limit: int) -> str:
    stripped = " ".join(text.split())
    return stripped if len(stripped) <= limit else f"{stripped[: limit - 1]}…"
