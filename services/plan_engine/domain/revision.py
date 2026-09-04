"""Revision strategies and the constraints each one puts on the LLM (PRD 3.8 / 3.8.1).

Pure and deterministic. ``strategy_rules`` returns the business rules
``complete_validated`` applies to a ``revise_plan`` response: the schema layer only says the
output is well formed, these say it is a legal revision of *this* plan under *this* strategy.

The proposal itself is encoded here too: ``plan_revisions.proposed_tasks`` is a JSON list
whose first element is the plan patch (the fields ``plans`` has to be updated with when the
user accepts) and whose remaining elements are the proposed tasks.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, timedelta
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from packages.llm.validation import BusinessRule
from services.plan_engine.domain.difficulty import Pacing
from services.plan_engine.domain.scheduler import ScheduledTask
from services.plan_engine.domain.template import PlanTemplate

__all__ = [
    "RevisedTemplateOutput",
    "Strategy",
    "encode_proposal",
    "plan_deadline",
    "strategy_rules",
]

_DAYS_PER_WEEK = 7

#: Task types the scheduler turns into all-day tasks; they have no comparable duration, so
#: the ``session_minutes`` bound does not apply to them (same reading as the scheduler).
_ALL_DAY_TYPES = frozenset({"rest", "checkpoint"})


class Strategy(StrEnum):
    """How a revision is allowed to change the plan (PRD 3.8.1)."""

    postpone = "postpone"
    reduce = "reduce"


#: The word the rationale has to contain, per strategy. These are content, not code: the
#: rationale is written by the LLM in Traditional Chinese (global constraint 19), and this
#: is the term it uses for the strategy. The English strategy value is accepted as well.
_STRATEGY_TERM: dict[Strategy, str] = {
    Strategy.postpone: "延後",
    Strategy.reduce: "降標",
}


class RevisedTemplateOutput(BaseModel):
    """LLM ``output_schema`` for ``revise_plan``."""

    model_config = ConfigDict(extra="forbid")

    template: PlanTemplate
    rationale: str = Field(min_length=1, max_length=500)


def plan_deadline(start_date: date, duration_weeks: int) -> date:
    """The last day of the last week, exactly as ``generate_plans`` computes it."""
    return start_date + timedelta(days=duration_weeks * _DAYS_PER_WEEK - 1)


def encode_proposal(
    template: PlanTemplate,
    start_date: date,
    tasks: Sequence[ScheduledTask],
) -> list[dict[str, Any]]:
    """Encode what ``plan_revisions.proposed_tasks`` holds.

    ``[plan_patch, task, task, ...]``: the head is the set of ``plans`` columns to write on
    accept, the tail is the proposed ``plan_tasks`` rows. The API service decodes the same
    shape in ``services/api/application/decide_revision.py``; the two sides are bound by
    this JSON contract, never by an import.
    """
    patch = {
        "goal_statement": template.goal_statement,
        "duration_weeks": template.duration_weeks,
        "deadline": plan_deadline(start_date, template.duration_weeks).isoformat(),
        "template": template.model_dump(mode="json"),
        "structure": {
            "phases": [phase.model_dump(mode="json") for phase in template.phases],
            "success_criteria": list(template.success_criteria),
            "assumptions": list(template.assumptions),
        },
    }
    return [patch, *(task.model_dump(mode="json") for task in tasks)]


def strategy_rules(
    strategy: Strategy,
    original: PlanTemplate,
    pacing: Pacing | None,
) -> list[BusinessRule]:
    """The rules a revised template must satisfy, given the plan it revises."""
    specific = _postpone_rule(original) if strategy is Strategy.postpone else _reduce_rule(original)
    return [specific, _pacing_rule(pacing), _rationale_rule(strategy)]


def _postpone_rule(original: PlanTemplate) -> BusinessRule:
    """Same goal, same weekly intensity; only the horizon may move (PRD 3.8.1)."""

    def rule(output: Any) -> list[str]:
        if not isinstance(output, RevisedTemplateOutput):
            return []
        revised = output.template
        violations: list[str] = []
        if revised.goal_statement != original.goal_statement:
            violations.append(
                "goal_statement must stay exactly the same under the postpone strategy"
            )
        if list(revised.success_criteria) != list(original.success_criteria):
            violations.append(
                "success_criteria must stay exactly the same under the postpone strategy"
            )
        if revised.duration_weeks < original.duration_weeks:
            violations.append(
                f"duration_weeks must be at least {original.duration_weeks} under the "
                f"postpone strategy, got {revised.duration_weeks}"
            )
        old_items = {item.key: item for item in original.weekly_template}
        new_items = {item.key: item for item in revised.weekly_template}
        if old_items.keys() != new_items.keys():
            violations.append(
                "weekly_template keys must stay the same under the postpone strategy: "
                f"expected {sorted(old_items)}, got {sorted(new_items)}"
            )
        for key in sorted(old_items.keys() & new_items.keys()):
            old, new = old_items[key], new_items[key]
            if new.times_per_week != old.times_per_week:
                violations.append(
                    f"weekly_template[{key}].times_per_week must stay {old.times_per_week} "
                    f"under the postpone strategy, got {new.times_per_week}"
                )
            if new.duration_minutes != old.duration_minutes:
                violations.append(
                    f"weekly_template[{key}].duration_minutes must stay "
                    f"{old.duration_minutes} under the postpone strategy, got "
                    f"{new.duration_minutes}"
                )
        return violations

    return rule


def _reduce_rule(original: PlanTemplate) -> BusinessRule:
    """Deadline is fixed; the goal itself has to come down (PRD 3.8.1)."""

    def rule(output: Any) -> list[str]:
        if not isinstance(output, RevisedTemplateOutput):
            return []
        revised = output.template
        violations: list[str] = []
        if revised.duration_weeks != original.duration_weeks:
            violations.append(
                f"duration_weeks must stay {original.duration_weeks} under the reduce "
                f"strategy, got {revised.duration_weeks}"
            )
        if revised.goal_statement == original.goal_statement:
            violations.append("goal_statement must be lowered under the reduce strategy")
        if list(revised.success_criteria) == list(original.success_criteria):
            violations.append("success_criteria must be lowered under the reduce strategy")
        return violations

    return rule


def _pacing_rule(pacing: Pacing | None) -> BusinessRule:
    """The trait pacing is a hard ceiling for both strategies (PRD 3.8.1)."""

    def rule(output: Any) -> list[str]:
        if pacing is None or not isinstance(output, RevisedTemplateOutput):
            return []
        sessions_min, sessions_max = pacing.sessions_per_week
        minutes_min, minutes_max = pacing.session_minutes
        violations: list[str] = []

        weekly_sessions = sum(
            item.times_per_week
            for item in output.template.weekly_template
            if item.task_type == "session"
        )
        if weekly_sessions > sessions_max:
            violations.append(
                f"sessions_per_week is capped at {sessions_max}, but the weekly template "
                f"asks for {weekly_sessions}"
            )
        elif weekly_sessions < sessions_min:
            violations.append(
                f"sessions_per_week must be at least {sessions_min}, but the weekly "
                f"template asks for {weekly_sessions}"
            )

        for item in output.template.weekly_template:
            if item.task_type in _ALL_DAY_TYPES:
                continue
            if not minutes_min <= item.duration_minutes <= minutes_max:
                violations.append(
                    f"weekly_template[{item.key}] runs {item.duration_minutes} minutes, "
                    f"outside the session_minutes bound {minutes_min}-{minutes_max}"
                )
        return violations

    return rule


def _rationale_rule(strategy: Strategy) -> BusinessRule:
    """The user has to be told which strategy was applied (PRD 3.8)."""
    term = _STRATEGY_TERM[strategy]

    def rule(output: Any) -> list[str]:
        if not isinstance(output, RevisedTemplateOutput):
            return []
        rationale = output.rationale
        if term in rationale or strategy.value in rationale.lower():
            return []
        return [f"rationale must say the {strategy.value} strategy was applied ({term})"]

    return rule
