"""Expand a ``PlanTemplate`` into tasks with absolute times (PRD 4.3.2).

Pure and deterministic: the same input always yields the same output, which is what lets
revision diffs (Task 20) align tasks on ``(template_key, week_index, occurrence)``.

A scheduling failure is not an exception: items that do not fit are recorded in
``ScheduleResult.unplaced`` and pacing breaches in ``ScheduleResult.violations``. The use
case decides whether to feed them back to the LLM for a regeneration or accept them.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field

from packages.config import CONFIG_DIR, load_yaml_config
from services.plan_engine.domain.capacity import MINUTES_PER_DAY, BusyBlock, Capacity
from services.plan_engine.domain.difficulty import Pacing
from services.plan_engine.domain.template import (
    DayHint,
    Phase,
    PlanTemplate,
    SlotHint,
    TaskType,
    WeeklyItem,
)

__all__ = [
    "PacingViolation",
    "ScheduleResult",
    "ScheduledTask",
    "SchedulerConfig",
    "load_scheduler_config",
    "schedule",
]

_DAYS_PER_WEEK = 7

#: ``day_hint`` -> the ``date.weekday()`` values it allows.
_DAY_HINT_WEEKDAYS: dict[DayHint, tuple[int, ...]] = {
    "mon": (0,),
    "tue": (1,),
    "wed": (2,),
    "thu": (3,),
    "fri": (4,),
    "sat": (5,),
    "sun": (6,),
    "weekday": (0, 1, 2, 3, 4),
    "weekend": (5, 6),
    "any": (0, 1, 2, 3, 4, 5, 6),
}

#: Task types that get no specific time and always become all-day tasks (rules 7 and 8).
_ALL_DAY_TYPES: frozenset[TaskType] = frozenset({"rest", "checkpoint"})


class SchedulerConfig(BaseModel):
    """``config/scheduler.yaml``: system-level scheduler rules, never set by the LLM."""

    model_config = ConfigDict(extra="forbid")

    default_start: Literal["next_monday", "tomorrow"] = "next_monday"
    min_gap_minutes: int = Field(default=30, ge=0)
    max_shift_days: int = Field(default=3, ge=0)
    checkpoint_hour: int = Field(default=0, ge=0, le=23)
    slot_order: list[SlotHint] = ["morning", "evening", "noon", "any"]


class ScheduledTask(BaseModel):
    """One expanded task, corresponding to a single ``plan_tasks`` row."""

    model_config = ConfigDict(extra="forbid")

    template_key: str
    week_index: int
    phase_index: int
    occurrence: int
    task_type: TaskType
    title: str
    description: str
    start_at: datetime
    end_at: datetime
    all_day: bool
    sort_order: int


class PacingViolation(BaseModel):
    """A breach of the trait ``pacing`` in one week; recorded, never raised (rule 9)."""

    model_config = ConfigDict(extra="forbid")

    week_index: int
    rule: Literal[
        "sessions_per_week_max",
        "sessions_per_week_min",
        "rest_days_min",
        "session_minutes",
    ]
    detail: str


class ScheduleResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tasks: list[ScheduledTask]
    violations: list[PacingViolation]
    unplaced: list[str]


def load_scheduler_config(path: Path | None = None) -> SchedulerConfig:
    """Load the scheduler config; defaults to ``config/scheduler.yaml``."""
    return load_yaml_config(path or CONFIG_DIR / "scheduler.yaml", SchedulerConfig)


def schedule(
    template: PlanTemplate,
    *,
    start_date: date,
    capacity: Capacity,
    busy: Sequence[BusyBlock],
    pacing: Pacing | None,
    config: SchedulerConfig,
) -> ScheduleResult:
    """Expand ``template`` into ``duration_weeks`` weeks of absolutely timed tasks.

    Week 0 starts on ``start_date``; week w covers the seven days from ``start_date + 7w``
    (rule 1). Every time is computed in the local ``capacity.timezone`` and then stored as
    UTC (rule 11).
    """
    zone = ZoneInfo(capacity.timezone)
    gap = timedelta(minutes=config.min_gap_minutes)
    # Absolute ranges already taken: existing commitments plus timed tasks already placed.
    # All-day tasks occupy nothing.
    occupied: list[tuple[datetime, datetime]] = [(block.start_at, block.end_at) for block in busy]

    tasks: list[ScheduledTask] = []
    unplaced: list[str] = []

    for week_index in range(template.duration_weeks):
        week_start = start_date + timedelta(days=_DAYS_PER_WEEK * week_index)
        phase = _phase_for_week(template.phases, week_index)

        for item in template.weekly_template:
            for occurrence, target_day in enumerate(_target_days(week_start, item)):
                if item.task_type in _ALL_DAY_TYPES:
                    # Rule 8: no specific time, emit an all-day task directly.
                    start_at, end_at = _all_day_bounds(target_day, zone, config.checkpoint_hour)
                else:
                    placed = _place(
                        item,
                        target_day=target_day,
                        week_start=week_start,
                        capacity=capacity,
                        zone=zone,
                        occupied=occupied,
                        gap=gap,
                        config=config,
                    )
                    if placed is None:
                        # Rule 6: no free slot further out, record it in unplaced and emit
                        # no task.
                        if item.key not in unplaced:
                            unplaced.append(item.key)
                        continue
                    start_at, end_at = placed
                    occupied.append(placed)

                tasks.append(
                    ScheduledTask(
                        template_key=item.key,
                        week_index=week_index,
                        phase_index=phase.index,
                        occurrence=occurrence,
                        task_type=item.task_type,
                        title=item.title,
                        description=item.description,
                        start_at=start_at,
                        end_at=end_at,
                        all_day=item.task_type in _ALL_DAY_TYPES,
                        sort_order=0,
                    )
                )

        if phase.week_end == week_index:
            tasks.append(_checkpoint(phase, week_index, week_start, zone, config))

    violations = _pacing_violations(tasks, template.duration_weeks, pacing)
    return ScheduleResult(tasks=_with_sort_order(tasks), violations=violations, unplaced=unplaced)


# ----------------------------------------------------------------------------- Rule 3


def _target_days(week_start: date, item: WeeklyItem) -> list[date]:
    """Spread ``times_per_week`` occurrences evenly over the days ``day_hint`` allows.

    Candidate days are numbered 0..L-1 and occurrence i takes index
    ``round(i * (L-1) / (n-1))`` — three occurrences over seven candidates land on 0, 3 and
    6. Fully deterministic, no randomness.
    """
    candidates = _candidate_days(week_start, item.day_hint)
    if not candidates:
        return []
    times = item.times_per_week
    if times <= 1:
        return [candidates[0]]
    last = len(candidates) - 1
    return [candidates[min(round(index * last / (times - 1)), last)] for index in range(times)]


def _candidate_days(week_start: date, day_hint: DayHint) -> list[date]:
    weekdays = _DAY_HINT_WEEKDAYS[day_hint]
    days = [week_start + timedelta(days=offset) for offset in range(_DAYS_PER_WEEK)]
    return [day for day in days if day.weekday() in weekdays]


# -------------------------------------------------------------------------- Rules 4-6


def _place(
    item: WeeklyItem,
    *,
    target_day: date,
    week_start: date,
    capacity: Capacity,
    zone: ZoneInfo,
    occupied: Sequence[tuple[datetime, datetime]],
    gap: timedelta,
    config: SchedulerConfig,
) -> tuple[datetime, datetime] | None:
    """Find the first slot that fits, from ``target_day`` up to ``max_shift_days`` later.

    Rule 6: shifting later must not leave the week (the seven days from ``week_start``).
    """
    week_end = week_start + timedelta(days=_DAYS_PER_WEEK - 1)
    duration = timedelta(minutes=item.duration_minutes)
    slots = [item.slot_hint] if item.slot_hint != "any" else config.slot_order

    for shift in range(config.max_shift_days + 1):
        day = target_day + timedelta(days=shift)
        if day > week_end:
            break
        for slot in slots:
            for window in capacity.windows(day.weekday(), slot):
                start_at = _first_fit(
                    _local(day, window.start_minute, zone),
                    _local(day, window.end_minute, zone),
                    duration,
                    occupied,
                    gap,
                )
                if start_at is not None:
                    return start_at, start_at + duration
    return None


def _first_fit(
    window_start: datetime,
    window_end: datetime,
    duration: timedelta,
    occupied: Iterable[tuple[datetime, datetime]],
    gap: timedelta,
) -> datetime | None:
    """Rule 5: first start in the window that fits ``duration`` and keeps ``gap`` from
    everything already occupied.
    """
    cursor = window_start
    blocked = sorted((start - gap, end + gap) for start, end in occupied)
    for start, end in blocked:
        if end <= cursor:
            continue
        if start - cursor >= duration:
            return cursor
        cursor = max(cursor, end)
        if cursor + duration > window_end:
            return None
    return cursor if cursor + duration <= window_end else None


# -------------------------------------------------------------------------- Rules 7-8


def _checkpoint(
    phase: Phase,
    week_index: int,
    week_start: date,
    zone: ZoneInfo,
    config: SchedulerConfig,
) -> ScheduledTask:
    """Rule 7: put an all-day checkpoint on the Sunday of a phase's last week."""
    sunday = week_start + timedelta(days=(6 - week_start.weekday()) % _DAYS_PER_WEEK)
    start_at, end_at = _all_day_bounds(sunday, zone, config.checkpoint_hour)
    return ScheduledTask(
        template_key=f"checkpoint_p{phase.index}",
        week_index=week_index,
        phase_index=phase.index,
        occurrence=0,
        task_type="checkpoint",
        title=phase.milestone.title,
        description=phase.milestone.metric,
        start_at=start_at,
        end_at=end_at,
        all_day=True,
        sort_order=0,
    )


def _phase_for_week(phases: Sequence[Phase], week_index: int) -> Phase:
    for phase in phases:
        if phase.week_start <= week_index <= phase.week_end:
            return phase
    return phases[-1]


# ---------------------------------------------------------------------------- Rule 11


def _local(day: date, minute: int, zone: ZoneInfo) -> datetime:
    """Minute ``minute`` of a local day, as UTC; 1440 means 00:00 of the next day."""
    extra_days, minute_of_day = divmod(minute, MINUTES_PER_DAY)
    local_date = day + timedelta(days=extra_days)
    local_time = time(hour=minute_of_day // 60, minute=minute_of_day % 60)
    return datetime.combine(local_date, local_time, tzinfo=zone).astimezone(UTC)


def _all_day_bounds(day: date, zone: ZoneInfo, hour: int) -> tuple[datetime, datetime]:
    """All-day task: local ``hour``:00 until local 00:00 the next day, both as UTC."""
    return _local(day, hour * 60, zone), _local(day, MINUTES_PER_DAY, zone)


# ----------------------------------------------------------------------------- Rule 9


def _pacing_violations(
    tasks: Sequence[ScheduledTask], duration_weeks: int, pacing: Pacing | None
) -> list[PacingViolation]:
    """Check the schedule against the trait pacing week by week. Records, never raises.

    Two deliberate readings: ``rest_days_min`` counts only days that carry a non-rest task
    (a rest task is itself a rest day), and ``session_minutes`` only checks tasks with a real
    duration (an all-day task has nothing comparable).
    """
    if pacing is None:
        return []

    sessions_min, sessions_max = pacing.sessions_per_week
    minutes_min, minutes_max = pacing.session_minutes
    max_busy_days = _DAYS_PER_WEEK - pacing.rest_days_min
    violations: list[PacingViolation] = []

    for week_index in range(duration_weeks):
        weekly = [task for task in tasks if task.week_index == week_index]
        sessions = [task for task in weekly if task.task_type == "session"]

        if len(sessions) > sessions_max:
            violations.append(
                PacingViolation(
                    week_index=week_index,
                    rule="sessions_per_week_max",
                    detail=(
                        f"week {week_index + 1} has {len(sessions)} sessions, "
                        f"above the maximum of {sessions_max}"
                    ),
                )
            )
        elif len(sessions) < sessions_min:
            violations.append(
                PacingViolation(
                    week_index=week_index,
                    rule="sessions_per_week_min",
                    detail=(
                        f"week {week_index + 1} has only {len(sessions)} sessions, "
                        f"below the minimum of {sessions_min}"
                    ),
                )
            )

        busy_days = {task.start_at.date() for task in weekly if task.task_type != "rest"}
        if len(busy_days) > max_busy_days:
            violations.append(
                PacingViolation(
                    week_index=week_index,
                    rule="rest_days_min",
                    detail=(
                        f"week {week_index + 1} has tasks on {len(busy_days)} days, "
                        f"leaving fewer than {pacing.rest_days_min} rest days"
                    ),
                )
            )

        for task in weekly:
            if task.all_day:
                continue
            minutes = round((task.end_at - task.start_at).total_seconds() / 60)
            if minutes_min <= minutes <= minutes_max:
                continue
            violations.append(
                PacingViolation(
                    week_index=week_index,
                    rule="session_minutes",
                    detail=(
                        f"{task.template_key} in week {week_index + 1} runs {minutes} "
                        f"minutes, outside {minutes_min}-{minutes_max} minutes"
                    ),
                )
            )

    return violations


# ---------------------------------------------------------------------------- Rule 10


def _with_sort_order(tasks: Sequence[ScheduledTask]) -> list[ScheduledTask]:
    ordered = sorted(tasks, key=lambda task: (task.start_at, task.template_key, task.occurrence))
    return [task.model_copy(update={"sort_order": index}) for index, task in enumerate(ordered)]
