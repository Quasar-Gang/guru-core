"""`plan.generate` — one Direction Hypothesis becomes one Plan.

Exactly one model call, and it produces a *relative* template: a Milestone tree, the Tasks
under it, and week ranges. Placing that on dates, applying the Quota and cutting what does
not fit are all arithmetic, done here in code.

The Plan row already exists in status `generating` — it was created with the Hypothesis, so
the client has something to poll from the first moment.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from packages.llm.ports import LLMPort, Purpose
from packages.llm.validation import BusinessRule, complete_validated
from packages.repo.entities import NewMilestone, NewTask
from packages.repo.ports import (
    DirectionHypothesisRepo,
    DocumentRepo,
    FitVerdictRepo,
    ImportRepo,
    PlanRepo,
    PlanTreeRepo,
    ProfileRepo,
    QuestionAnswerRepo,
    QuotaRepo,
    RoleModelRepo,
)
from services.engine.application.documents import load_uploads
from services.engine.application.ports import ClockPort
from services.engine.domain.capacity import BusyBlock, Capacity
from services.engine.domain.errors import EngineError
from services.engine.domain.plan_template import (
    FlatMilestone,
    PlanTemplate,
    PlanTemplateOutput,
    flatten,
)
from services.engine.domain.quota import Quota, QuotaConfig
from services.engine.domain.scheduler import (
    ScheduledTask,
    SchedulerConfig,
    ScheduleResult,
    schedule,
)
from services.engine.domain.verdict import Probe

__all__ = ["GeneratePlan"]

_DAYS_PER_WEEK = 7
_DEFAULT_DURATION_WEEKS = 12

_NO_QUOTA_ASSUMPTION = (
    "Q-3 was skipped, so the plan spends the default weekly allowance and drops "
    "'{drop_first}' first."
)
_TRIMMED_ASSUMPTION = "'{key}' was cut in week {week} to stay inside the weekly quota."
_UNPLACED_ASSUMPTION = "'{key}' had occurrences that fit no free window and were skipped."


class GeneratePlan:
    """Station 2, as one queue job."""

    def __init__(
        self,
        plans: PlanRepo,
        tree: PlanTreeRepo,
        hypotheses: DirectionHypothesisRepo,
        verdicts: FitVerdictRepo,
        role_models: RoleModelRepo,
        quotas: QuotaRepo,
        answers: QuestionAnswerRepo,
        profiles: ProfileRepo,
        imports: ImportRepo,
        documents: DocumentRepo,
        llm: LLMPort,
        scheduler_config: SchedulerConfig,
        quota_config: QuotaConfig,
        clock: ClockPort,
        max_attempts: int,
    ) -> None:
        self._plans = plans
        self._tree = tree
        self._hypotheses = hypotheses
        self._verdicts = verdicts
        self._role_models = role_models
        self._quotas = quotas
        self._answers = answers
        self._profiles = profiles
        self._imports = imports
        self._documents = documents
        self._llm = llm
        self._scheduler_config = scheduler_config
        self._quota_config = quota_config
        self._clock = clock
        self._max_attempts = max_attempts

    async def __call__(self, plan_id: UUID) -> None:
        plan = await self._plans.get_unscoped(plan_id)
        if plan is None:
            raise LookupError(f"unknown plan {plan_id}")
        try:
            hypothesis = await self._hypotheses.get_unscoped(plan.hypothesis_id)
            if hypothesis is None:
                raise EngineError(f"plan {plan_id} points at no hypothesis")
            verdict = await self._verdicts.get(plan.user_id, hypothesis.fit_verdict_id)
            role_model = await self._role_models.get(hypothesis.role_model_id)
            if verdict is None or role_model is None:
                raise EngineError("the hypothesis references a verdict or shape that is gone")

            profile = await self._profiles.get(plan.user_id)
            timezone = profile.timezone if profile is not None else "UTC"
            capacity = Capacity.default(timezone)
            start_date = _next_start_date(
                self._clock.now().astimezone(ZoneInfo(timezone)).date(), self._scheduler_config
            )
            busy = await self._busy_blocks(plan.user_id, start_date)
            stored_quota = await self._quotas.get(plan.user_id)
            quota = (
                Quota(
                    drop_first=stored_quota.drop_first,
                    weekly_minutes=stored_quota.weekly_minutes,
                )
                if stored_quota is not None
                else self._quota_config.fallback()
            )

            outcome = await complete_validated(
                self._llm,
                "build_plan",
                await self._context(plan.user_id, role_model, verdict, hypothesis, quota, capacity),
                PlanTemplateOutput,
                Purpose.generate,
                max_attempts=self._max_attempts,
                rules=[
                    _schedulable_rule(
                        start_date=start_date,
                        capacity=capacity,
                        busy=busy,
                        quota=quota,
                        config=self._scheduler_config,
                    )
                ],
            )
            template = outcome.value.plan
            result = schedule(
                template,
                start_date=start_date,
                capacity=capacity,
                busy=busy,
                quota=quota,
                config=self._scheduler_config,
            )
            await self._store(plan_id, start_date, template, result, quota, stored_quota is None)
        except Exception as exc:
            await self._plans.update_fields(plan_id, status="failed", error=str(exc))
            raise

    # ---------------------------------------------------------------------- storing

    async def _store(
        self,
        plan_id: UUID,
        start_date: date,
        template: PlanTemplate,
        result: ScheduleResult,
        quota: Quota,
        quota_defaulted: bool,
    ) -> None:
        milestones = flatten(template.milestones)
        await self._tree.replace_tree(
            plan_id,
            [_new_milestone(node, start_date) for node in milestones],
            [_new_task(task) for task in result.tasks],
        )
        await self._plans.update_fields(
            plan_id,
            status="draft",
            title=template.title,
            start_date=start_date,
            duration_weeks=template.duration_weeks,
            error=None,
            structure={
                "success_criteria": list(template.success_criteria),
                "assumptions": _assumptions(template, result, quota, quota_defaulted),
                "quota": quota.model_dump(mode="json"),
                "trimmed": [item.model_dump(mode="json") for item in result.trimmed],
                "unplaced": list(result.unplaced),
                # The Schedule as first computed. Station 3 diffs today's schedule against
                # this, which is the only way "the plan changed" can mean anything later.
                "baseline_schedule": [_snapshot(task) for task in result.tasks],
            },
        )

    # ---------------------------------------------------------------------- context

    async def _context(
        self,
        user_id: UUID,
        role_model: Any,
        verdict: Any,
        hypothesis: Any,
        quota: Quota,
        capacity: Capacity,
    ) -> dict[str, Any]:
        answered = await self._answers.list_for_user(user_id)
        return {
            "role_model": {
                "code": role_model.code,
                "name": role_model.name,
                "vision": role_model.vision,
                "five_year_path": role_model.five_year_path,
                "must_accumulate": role_model.must_accumulate,
                "cost": role_model.cost,
            },
            "probe": Probe.model_validate(verdict.probe).model_dump(),
            "evidence": verdict.evidence,
            "review_date": hypothesis.review_date.isoformat(),
            "quota": quota.model_dump(mode="json"),
            "capacity_summary": _capacity_summary(capacity),
            "default_duration_weeks": _DEFAULT_DURATION_WEEKS,
            "answers": [
                {"question": row.question_key, "text": row.answer}
                for row in answered
                if not row.skipped
            ],
        }

    async def _busy_blocks(self, user_id: UUID, start_date: date) -> list[BusyBlock]:
        """Existing commitments from the calendar the user already keeps.

        Only what falls on or after the plan's start matters; an all-day event blocks
        nothing, because it says which day it is, not which hours are gone.
        """
        uploads = await load_uploads(self._imports, self._documents, user_id)
        blocks: list[BusyBlock] = []
        for event in uploads.document.events:
            if event.all_day or event.start_at.date() < start_date:
                continue
            try:
                blocks.append(BusyBlock(start_at=event.start_at, end_at=event.end_at))
            except ValueError:
                continue
        return blocks


# ------------------------------------------------------------------- business rule


def _schedulable_rule(
    *,
    start_date: date,
    capacity: Capacity,
    busy: list[BusyBlock],
    quota: Quota,
    config: SchedulerConfig,
) -> BusinessRule:
    """A well-formed template can still be unschedulable; say so before storing it.

    Only `unplaced` is a violation. Quota trims are not: the quota is the user's own stated
    ceiling, and a plan that respects it is working correctly, not failing.
    """

    def rule(output: Any) -> list[str]:
        if not isinstance(output, PlanTemplateOutput):
            return []
        result = schedule(
            output.plan,
            start_date=start_date,
            capacity=capacity,
            busy=busy,
            quota=quota,
            config=config,
        )
        return [
            f"task '{key}' fits no available time window; "
            "shorten it, lower times_per_week, or widen its day_hint"
            for key in result.unplaced
        ]

    return rule


# ------------------------------------------------------------------------ helpers


def _new_milestone(node: FlatMilestone, start_date: date) -> NewMilestone:
    return NewMilestone(
        key=node.key,
        parent_key=node.parent_key,
        title=node.title,
        metric=node.metric,
        target_date=start_date + timedelta(days=_DAYS_PER_WEEK * (node.target_week + 1) - 1),
        depth=node.depth,
        position=node.position,
    )


def _new_task(task: ScheduledTask) -> NewTask:
    return NewTask(**task.model_dump())


def _snapshot(task: ScheduledTask) -> dict[str, Any]:
    return {
        "key": task.key,
        "week_index": task.week_index,
        "occurrence": task.occurrence,
        "title": task.title,
        "start_at": task.start_at.isoformat(),
        "end_at": task.end_at.isoformat(),
        "all_day": task.all_day,
    }


def _assumptions(
    template: PlanTemplate, result: ScheduleResult, quota: Quota, quota_defaulted: bool
) -> list[str]:
    """Everything the plan had to assume, said out loud rather than buried."""
    lines = list(template.assumptions)
    if quota_defaulted:
        lines.append(_NO_QUOTA_ASSUMPTION.format(drop_first=quota.drop_first))
    lines += [
        _TRIMMED_ASSUMPTION.format(key=item.key, week=item.week_index + 1)
        for item in result.trimmed
    ]
    lines += [_UNPLACED_ASSUMPTION.format(key=key) for key in result.unplaced]
    seen: list[str] = []
    for line in lines:
        if line not in seen:
            seen.append(line)
    return seen


def _capacity_summary(capacity: Capacity) -> str:
    zone = ZoneInfo(capacity.timezone)
    slots = sorted({slot for day in capacity.slots.values() for slot in day})
    return f"timezone {zone.key}; free slots on most days: {', '.join(slots) or 'none'}"


def _next_start_date(today: date, config: SchedulerConfig) -> date:
    """Where a plan starts, in the user's local calendar. Scheduling policy, so it lives here
    rather than in whichever service happened to create the row.
    """
    if config.default_start == "tomorrow":
        return today + timedelta(days=1)
    return today + timedelta(days=(-today.weekday()) % _DAYS_PER_WEEK or _DAYS_PER_WEEK)
