"""Propose a revision of a running plan (PRD 3.8), never apply one.

The LLM only ever touches the template; the deterministic scheduler turns the revised
template back into tasks, and the diff against today's schedule is computed in code. The
proposal is written to ``plan_revisions`` and waits for the user: accepting it is the API
service's job. There is deliberately **no fallback** — a revision the model cannot get right
is reported as failed rather than silently rewriting the user's plan with a system default.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Sequence
from datetime import UTC, date, datetime, time
from typing import Any
from zoneinfo import ZoneInfo

from packages.llm.ports import LLMPort, Purpose
from packages.llm.validation import BusinessRule, complete_validated
from packages.queue import PlanReviseJobV1
from packages.repo.entities import Checkin, Plan, PlanTask
from packages.repo.ports import CheckinRepo, PlanRepo, PlanRevisionRepo, PlanTaskRepo
from services.plan_engine.application.context_builder import ContextBuilder, SessionContext
from services.plan_engine.application.ports import ClockPort
from services.plan_engine.domain.capacity import BusyBlock
from services.plan_engine.domain.diff import TaskSnapshotWithKey, diff_tasks
from services.plan_engine.domain.revision import (
    RevisedTemplateOutput,
    Strategy,
    encode_proposal,
    strategy_rules,
)
from services.plan_engine.domain.scheduler import SchedulerConfig, ScheduleResult, schedule
from services.plan_engine.domain.template import PlanTemplate

__all__ = ["RevisePlan"]

_LOG = logging.getLogger(__name__)
_DAYS_PER_WEEK = 7

#: Statuses that mean the revision is still waiting to be proposed. Anything else has
#: already been decided, and re-running the job must not touch it.
_PENDING = "pending"


class RevisePlan:
    """The `plan.revise` queue handler."""

    def __init__(
        self,
        plans: PlanRepo,
        plan_tasks: PlanTaskRepo,
        revisions: PlanRevisionRepo,
        checkins: CheckinRepo,
        context_builder: ContextBuilder,
        llm: LLMPort,
        scheduler_config: SchedulerConfig,
        clock: ClockPort,
        max_attempts: int,
    ) -> None:
        self._plans = plans
        self._plan_tasks = plan_tasks
        self._revisions = revisions
        self._checkins = checkins
        self._context_builder = context_builder
        self._llm = llm
        self._scheduler_config = scheduler_config
        self._clock = clock
        self._max_attempts = max_attempts

    async def __call__(self, job: PlanReviseJobV1) -> None:
        revision = await self._revisions.get_unscoped(job.revision_id)
        if revision is None:
            raise LookupError(f"unknown plan revision {job.revision_id}")
        if revision.status != _PENDING:
            # Already proposed, accepted, rejected or failed: the job is a duplicate.
            return
        try:
            await self._propose(job, revision.rationale)
        except Exception as exc:  # noqa: BLE001 - a failed revision is a state, not a crash
            _LOG.warning("plan revision %s failed: %s", job.revision_id, exc)
            await self._revisions.set_status(job.revision_id, "failed", None)

    async def _propose(self, job: PlanReviseJobV1, note: str | None) -> None:
        plan = await self._plans.get_unscoped(job.plan_id)
        if plan is None:
            raise LookupError(f"unknown plan {job.plan_id}")
        original = PlanTemplate.model_validate(plan.template)
        strategy = Strategy(job.strategy)

        context = await self._context_builder.build(plan.session_id, Purpose.revise)
        cutoff = _cutoff(self._clock.now(), context.timezone)
        tasks = await self._plan_tasks.list(plan.id, None, None)
        checkins = await self._checkins.list_for_plan(plan.id)
        busy = _busy_blocks(context)

        outcome = await complete_validated(
            self._llm,
            "revise_plan",
            context.to_prompt_context()
            | {
                "current_template": plan.template,
                "progress_summary": _progress_summary(tasks, checkins, cutoff),
                "remaining_weeks": _remaining_weeks(plan, cutoff, context.timezone),
                "strategy": strategy.value,
                "note": note or "",
            },
            RevisedTemplateOutput,
            Purpose.revise,
            max_attempts=self._max_attempts,
            rules=[
                *strategy_rules(strategy, original, context.pacing),
                self._schedulable_rule(context, plan.start_date, busy),
            ],
            # No fallback on purpose: see the module docstring.
            fallback=None,
        )
        revised = outcome.value.template

        # The template is expanded from the plan's own start date so that `week_index` keeps
        # meaning the same thing on both sides of the diff; only the part of the schedule
        # that lies after the cutoff becomes the proposal.
        result = self._schedule(revised, context, plan.start_date, busy)
        proposed = [task for task in result.tasks if task.start_at >= cutoff]
        diff = diff_tasks(_snapshots(tasks, cutoff), proposed)

        await self._revisions.set_proposal(
            job.revision_id,
            encode_proposal(revised, plan.start_date, proposed),
            [entry.model_dump(mode="json") for entry in diff],
            outcome.value.rationale,
        )
        await self._revisions.set_status(job.revision_id, "proposed", None)

    # ------------------------------------------------------------------ business rule

    def _schedulable_rule(
        self,
        context: SessionContext,
        start_date: date,
        busy: Sequence[BusyBlock],
    ) -> BusinessRule:
        """A well-formed revision can still be unschedulable; feed that back to the model."""

        def rule(output: Any) -> list[str]:
            if not isinstance(output, RevisedTemplateOutput):
                return []
            result = self._schedule(output.template, context, start_date, busy)
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


def _cutoff(now: datetime, timezone: str) -> datetime:
    """Midnight of the plan owner's today, as UTC: everything from here on is rescheduled."""
    zone = ZoneInfo(timezone)
    today = now.astimezone(zone).date()
    return datetime.combine(today, time.min, tzinfo=zone).astimezone(UTC)


def _remaining_weeks(plan: Plan, cutoff: datetime, timezone: str) -> int:
    """Whole weeks left until the deadline, never negative."""
    today = cutoff.astimezone(ZoneInfo(timezone)).date()
    return max(0, math.ceil((plan.deadline - today).days / _DAYS_PER_WEEK))


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


def _snapshots(tasks: Sequence[PlanTask], cutoff: datetime) -> list[TaskSnapshotWithKey]:
    """The side of the diff that is being replaced: today's schedule from the cutoff on."""
    return [
        TaskSnapshotWithKey(
            template_key=task.template_key,
            week_index=task.week_index,
            occurrence=task.occurrence,
            title=task.title,
            start_at=task.start_at,
            end_at=task.end_at,
            all_day=task.all_day,
        )
        for task in tasks
        if task.start_at >= cutoff
    ]


def _progress_summary(
    tasks: Sequence[PlanTask], checkins: Sequence[Checkin], cutoff: datetime
) -> str:
    """How the plan has gone so far, as the lines the revise prompt renders verbatim."""
    past = [task for task in tasks if task.start_at < cutoff]
    counts = {status: sum(1 for task in past if task.status == status) for status in _STATUSES}
    lines = [
        f"tasks so far: {len(past)}",
        ", ".join(f"{status}: {count}" for status, count in counts.items()),
    ]
    reasons = [
        task.missed_reason for task in past if task.status == "missed" and task.missed_reason
    ]
    if reasons:
        lines.append("missed reasons: " + "; ".join(reasons))
    notes = [checkin.note for checkin in checkins if checkin.note]
    if notes:
        lines.append("check-in notes: " + "; ".join(notes))
    return "\n".join(lines)


_STATUSES = ("done", "missed", "skipped", "pending")
