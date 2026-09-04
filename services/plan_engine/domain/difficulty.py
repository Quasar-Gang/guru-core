"""Derive the three difficulty variants from one baseline PlanTemplate (PRD 4.3.1.1).

The LLM produces a single baseline template; easy / hard / extremely_hard are scaled from it
by the coefficients here and then clamped to the ``pacing`` bounds of the trait role model.
All three share the same ``goal_statement``, ``success_criteria`` and ``assumptions``.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from packages.config import CONFIG_DIR, load_yaml_config
from services.plan_engine.domain.template import Phase, PlanTemplate, WeeklyItem

__all__ = [
    "Difficulty",
    "DifficultyCoefficients",
    "DifficultyConfig",
    "Pacing",
    "derive",
    "load_difficulty_config",
]

_MIN_DURATION_MINUTES = 5
_MAX_DURATION_MINUTES = 300
_MIN_TIMES_PER_WEEK = 1
_MAX_TIMES_PER_WEEK = 7
_DAYS_PER_WEEK = 7


class Difficulty(StrEnum):
    easy = "easy"
    hard = "hard"
    extremely_hard = "extremely_hard"


class DifficultyCoefficients(BaseModel):
    """Scaling coefficients for one difficulty."""

    model_config = ConfigDict(extra="forbid")

    frequency: float
    duration: float
    weeks: float
    title_suffix: str


class DifficultyConfig(BaseModel):
    """Contents of ``config/difficulty_coefficients.yaml``."""

    model_config = ConfigDict(extra="forbid")

    coefficients: dict[Difficulty, DifficultyCoefficients]


class Pacing(BaseModel):
    """Hard constraints coming from the trait role model.

    Deliberate duplicate: Role Model defines the same name and the same fields in
    ``services/role_model/domain/content.py``. Services must not import each other, so the
    two copies are bound by a JSON contract — ``role_models.content["pacing"]``, carried here
    through ``plan_sessions.context_snapshot`` and read back with
    ``Pacing.model_validate(dict)``. Change one side and you must change the other.
    """

    model_config = ConfigDict(extra="forbid")

    sessions_per_week: tuple[int, int]
    session_minutes: tuple[int, int]
    rest_days_min: int
    progression_rate: float
    missed_policy: Literal["none", "same-week", "next-day"]
    deload_every_weeks: int | None = None
    intensity_bias: Literal["low", "medium", "high"]


def load_difficulty_config(path: Path | None = None) -> DifficultyConfig:
    """Load the difficulty coefficients; defaults to ``config/difficulty_coefficients.yaml``."""
    return load_yaml_config(path or CONFIG_DIR / "difficulty_coefficients.yaml", DifficultyConfig)


def derive(
    base: PlanTemplate,
    difficulty: Difficulty,
    config: DifficultyConfig,
    pacing: Pacing | None,
) -> PlanTemplate:
    """Derive the template for one difficulty from the coefficients and the pacing bounds.

    ``duration_weeks`` is floored at ``len(base.phases)``: every phase needs at least one
    week, and phases must stay contiguous and cover the whole plan, so fewer weeks than
    phases has no solution. A coefficient that scales below that floor is raised to it.
    """
    coefficients = config.coefficients[difficulty]

    # 1. Number of weeks.
    weeks = max(1, round(base.duration_weeks * coefficients.weeks), len(base.phases))

    # 2. Frequency and duration of each weekly item.
    items = [_scale_item(item, coefficients) for item in base.weekly_template]

    # 3. Rescale the phases proportionally to the new week count.
    phases = _rescale_phases(base.phases, base.duration_weeks, weeks)

    # 4. Clamp to the pacing bounds.
    if pacing is not None:
        items = _apply_pacing(items, pacing)

    # 5-6. Suffix the title; goal_statement / success_criteria / assumptions carry over as is.
    # Go through model_validate rather than model_copy so the phase coverage validator runs.
    return PlanTemplate.model_validate(
        {
            **base.model_dump(),
            "title": f"{base.title}{coefficients.title_suffix}",
            "duration_weeks": weeks,
            "phases": [phase.model_dump() for phase in phases],
            "weekly_template": [item.model_dump() for item in items],
        }
    )


def _scale_item(item: WeeklyItem, coefficients: DifficultyCoefficients) -> WeeklyItem:
    times = _clamp(
        round(item.times_per_week * coefficients.frequency),
        _MIN_TIMES_PER_WEEK,
        _MAX_TIMES_PER_WEEK,
    )
    minutes = _clamp(
        round(item.duration_minutes * coefficients.duration),
        _MIN_DURATION_MINUTES,
        _MAX_DURATION_MINUTES,
    )
    return item.model_copy(update={"times_per_week": times, "duration_minutes": minutes})


def _rescale_phases(phases: list[Phase], old_weeks: int, new_weeks: int) -> list[Phase]:
    """Rescale phase boundaries proportionally, keeping them contiguous, complete, >= 1 week."""
    count = len(phases)
    # Exclusive end boundary of each phase, scaled proportionally.
    bounds = [round((phase.week_end + 1) * new_weeks / old_weeks) for phase in phases]

    # Forward pass: at least one week each, strictly increasing.
    previous = 0
    for index in range(count):
        bounds[index] = max(bounds[index], previous + 1)
        previous = bounds[index]

    # Backward pass: the last phase must land exactly on the end; push the earlier ones
    # back, still keeping at least one week each.
    bounds[-1] = new_weeks
    for index in range(count - 2, -1, -1):
        bounds[index] = min(bounds[index], bounds[index + 1] - 1)

    rescaled: list[Phase] = []
    start = 0
    for phase, end in zip(phases, bounds, strict=True):
        rescaled.append(phase.model_copy(update={"week_start": start, "week_end": end - 1}))
        start = end
    return rescaled


def _apply_pacing(items: list[WeeklyItem], pacing: Pacing) -> list[WeeklyItem]:
    """Clamp each duration into ``session_minutes``, then the session count into its bounds."""
    minutes_min, minutes_max = pacing.session_minutes
    working = [
        item.model_copy(
            update={
                "duration_minutes": _clamp(
                    item.duration_minutes,
                    max(minutes_min, _MIN_DURATION_MINUTES),
                    min(minutes_max, _MAX_DURATION_MINUTES),
                )
            }
        )
        for item in items
    ]

    sessions = [index for index, item in enumerate(working) if item.task_type == "session"]
    if not sessions:
        return working

    # Days scheduled per week cannot exceed 7 - rest_days_min (the scheduler re-checks).
    weekly_min, weekly_max = pacing.sessions_per_week
    weekly_max = min(weekly_max, _DAYS_PER_WEEK - pacing.rest_days_min)
    weekly_min = min(weekly_min, weekly_max)

    total = sum(working[index].times_per_week for index in sessions)
    while total > weekly_max:
        # Take 1 off the item with the largest times_per_week; never drop below 1.
        candidates = [i for i in sessions if working[i].times_per_week > _MIN_TIMES_PER_WEEK]
        if not candidates:
            break
        target = max(candidates, key=lambda i: (working[i].times_per_week, -i))
        working[target] = _bump(working[target], -1)
        total -= 1
    while total < weekly_min:
        # The reverse: add 1 to the smallest item; never go above 7.
        candidates = [i for i in sessions if working[i].times_per_week < _MAX_TIMES_PER_WEEK]
        if not candidates:
            break
        target = min(candidates, key=lambda i: (working[i].times_per_week, i))
        working[target] = _bump(working[target], 1)
        total += 1
    return working


def _bump(item: WeeklyItem, delta: int) -> WeeklyItem:
    return item.model_copy(update={"times_per_week": item.times_per_week + delta})


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))
