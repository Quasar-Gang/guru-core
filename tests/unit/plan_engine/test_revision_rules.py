"""Revision strategy constraints (plan Task 36, PRD 3.8.1)."""

from typing import Any

from packages.llm.validation import BusinessRule
from services.plan_engine.domain.difficulty import Pacing
from services.plan_engine.domain.revision import (
    RevisedTemplateOutput,
    Strategy,
    strategy_rules,
)
from services.plan_engine.domain.template import PlanTemplate

PACING = Pacing(
    sessions_per_week=(1, 3),
    session_minutes=(20, 60),
    rest_days_min=1,
    progression_rate=0.1,
    missed_policy="same-week",
    intensity_bias="medium",
)


def _phases(weeks: int) -> list[dict[str, Any]]:
    per_phase = weeks // 3
    bounds = [(0, per_phase - 1), (per_phase, 2 * per_phase - 1), (2 * per_phase, weeks - 1)]
    names = ["base", "build", "peak"]
    return [
        {
            "index": index,
            "name": names[index],
            "week_start": start,
            "week_end": end,
            "focus": "focus",
            "milestone": {"title": "milestone", "metric": "metric"},
        }
        for index, (start, end) in enumerate(bounds)
    ]


def _template(
    *,
    weeks: int = 12,
    goal: str = "run 5k under 30 minutes",
    criteria: list[str] | None = None,
    times: int = 3,
    minutes: int = 40,
) -> PlanTemplate:
    return PlanTemplate.model_validate(
        {
            "title": "run 5k",
            "goal_statement": goal,
            "duration_weeks": weeks,
            "assumptions": [],
            "success_criteria": criteria or ["finish 5k under 30:00"],
            "phases": _phases(weeks),
            "weekly_template": [
                {
                    "key": "run",
                    "title": "run",
                    "task_type": "session",
                    "day_hint": "any",
                    "slot_hint": "evening",
                    "duration_minutes": minutes,
                    "description": "steady run",
                    "times_per_week": times,
                }
            ],
        }
    )


ORIGINAL = _template()


def _violations(rules: list[BusinessRule], output: RevisedTemplateOutput) -> list[str]:
    return [message for rule in rules for message in rule(output)]


def test_postpone_rejects_changed_goal_statement() -> None:
    rules = strategy_rules(Strategy.postpone, ORIGINAL, None)
    output = RevisedTemplateOutput(
        template=_template(goal="run 10k under 60 minutes"), rationale="延後兩週"
    )
    assert any("goal_statement" in message for message in _violations(rules, output))


def test_postpone_rejects_shorter_duration() -> None:
    rules = strategy_rules(Strategy.postpone, ORIGINAL, None)
    output = RevisedTemplateOutput(template=_template(weeks=9), rationale="延後兩週")
    assert any("duration_weeks" in message for message in _violations(rules, output))


def test_postpone_rejects_changed_task_density() -> None:
    rules = strategy_rules(Strategy.postpone, ORIGINAL, None)
    output = RevisedTemplateOutput(template=_template(times=2), rationale="延後兩週")
    assert any("times_per_week" in message for message in _violations(rules, output))


def test_postpone_rejects_changed_weekly_keys() -> None:
    rules = strategy_rules(Strategy.postpone, ORIGINAL, None)
    revised = _template()
    renamed = revised.model_copy(
        update={
            "weekly_template": [
                revised.weekly_template[0].model_copy(update={"key": "long_run"}),
            ]
        }
    )
    output = RevisedTemplateOutput(template=renamed, rationale="延後兩週")
    assert any("weekly_template" in message for message in _violations(rules, output))


def test_postpone_accepts_longer_duration_same_density() -> None:
    rules = strategy_rules(Strategy.postpone, ORIGINAL, None)
    output = RevisedTemplateOutput(template=_template(weeks=15), rationale="把期程延後三週")
    assert _violations(rules, output) == []


def test_reduce_rejects_changed_duration() -> None:
    rules = strategy_rules(Strategy.reduce, ORIGINAL, None)
    output = RevisedTemplateOutput(
        template=_template(weeks=15, goal="run 5k under 33 minutes", criteria=["finish 5k"]),
        rationale="降標，把目標放寬",
    )
    assert any("duration_weeks" in message for message in _violations(rules, output))


def test_reduce_requires_changed_goal_statement() -> None:
    rules = strategy_rules(Strategy.reduce, ORIGINAL, None)
    output = RevisedTemplateOutput(
        template=_template(criteria=["finish 5k"]), rationale="降標，把目標放寬"
    )
    assert any("goal_statement" in message for message in _violations(rules, output))


def test_reduce_requires_changed_success_criteria() -> None:
    rules = strategy_rules(Strategy.reduce, ORIGINAL, None)
    output = RevisedTemplateOutput(
        template=_template(goal="run 5k under 33 minutes"), rationale="降標，把目標放寬"
    )
    assert any("success_criteria" in message for message in _violations(rules, output))


def test_reduce_accepts_lower_goal_within_same_duration() -> None:
    rules = strategy_rules(Strategy.reduce, ORIGINAL, None)
    output = RevisedTemplateOutput(
        template=_template(goal="run 5k under 33 minutes", criteria=["finish 5k under 33:00"]),
        rationale="剩下的時間不夠，降標到 33 分",
    )
    assert _violations(rules, output) == []


def test_rationale_must_mention_strategy() -> None:
    rules = strategy_rules(Strategy.postpone, ORIGINAL, None)
    output = RevisedTemplateOutput(template=_template(weeks=15), rationale="稍微調整了一下")
    assert any("rationale" in message for message in _violations(rules, output))


def test_pacing_still_enforced_in_both_strategies() -> None:
    postpone = strategy_rules(Strategy.postpone, ORIGINAL, PACING)
    too_many = RevisedTemplateOutput(template=_template(weeks=15, times=6), rationale="延後三週")
    assert any("sessions_per_week" in message for message in _violations(postpone, too_many))

    reduce = strategy_rules(Strategy.reduce, ORIGINAL, PACING)
    too_long = RevisedTemplateOutput(
        template=_template(
            goal="run 5k under 33 minutes", criteria=["finish 5k under 33:00"], minutes=120
        ),
        rationale="降標到 33 分",
    )
    assert any("session_minutes" in message for message in _violations(reduce, too_long))


def test_pacing_absent_means_no_pacing_violation() -> None:
    rules = strategy_rules(Strategy.postpone, ORIGINAL, None)
    output = RevisedTemplateOutput(
        template=_template(weeks=15, times=6, minutes=120), rationale="延後三週"
    )
    assert not any(
        "sessions_per_week" in message or "session_minutes" in message
        for message in _violations(rules, output)
    )
