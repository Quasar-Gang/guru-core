"""Place a `PlanTemplate` on real dates. Pure, and deterministic by contract.

Same template, start date, capacity, busy blocks and quota in — byte-identical Schedule
out. That is not an engineering preference: the Direction Hypothesis is only falsifiable if
the thing it predicted was computed the same way twice. If the Schedule could drift between
two runs of the same inputs, Station 3 would be comparing against noise.

Two things can go wrong, and neither is an exception. An item with no free window lands in
`unplaced`; an item cut to stay inside the Quota lands in `trimmed`. Both are reported back
so the Plan can say what it dropped instead of silently shipping a week nobody can survive.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field

from packages.config import CONFIG_DIR, load_yaml_config
from services.engine.domain.capacity import MINUTES_PER_DAY, BusyBlock, Capacity
from services.engine.domain.plan_template import (
    Area,
    DayHint,
    FlatMilestone,
    PlanTemplate,
    SlotHint,
    TaskSpec,
    TaskType,
    flatten,
)
from services.engine.domain.quota import Quota

__all__ = [
    "ScheduleResult",
    "ScheduledTask",
    "SchedulerConfig",
    "TrimmedItem",
    "load_scheduler_config",
    "schedule",
]

_DAYS_PER_WEEK = 7

#: `day_hint` -> the `date.weekday()` values it allows.
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

#: Task types that get no specific time and always become all-day tasks. They also cost
#: nothing against the Quota: a checkpoint is a moment to look up, not work to fit in.
_ALL_DAY_TYPES: frozenset[TaskType] = frozenset({"rest", "checkpoint"})


class SchedulerConfig(BaseModel):
    """`config/scheduler.yaml`: system-level placement rules, never set by the model."""

    model_config = ConfigDict(extra="forbid")

    default_start: Literal["next_monday", "tomorrow"] = "next_monday"
    min_gap_minutes: int = Field(default=30, ge=0)
    max_shift_days: int = Field(default=3, ge=0)
    checkpoint_hour: int = Field(default=0, ge=0, le=23)
    slot_order: list[SlotHint] = ["morning", "evening", "noon", "any"]


class ScheduledTask(BaseModel):
    """One placed Task: everything a `tasks` row and its `schedule_slots` row need."""

    model_config = ConfigDict(extra="forbid")

    milestone_key: str
    key: str
    week_index: int
    occurrence: int
    area: Area
    task_type: TaskType
    title: str
    description: str
    duration_minutes: int
    start_at: datetime
    end_at: datetime
    all_day: bool
    sort_order: int


class TrimmedItem(BaseModel):
    """One occurrence dropped to stay inside the Quota, and why it went first."""

    model_config = ConfigDict(extra="forbid")

    key: str
    week_index: int
    occurrence: int
    area: Area
    reason: str


class ScheduleResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tasks: list[ScheduledTask]
    trimmed: list[TrimmedItem]
    unplaced: list[str]


def load_scheduler_config(path: Path | None = None) -> SchedulerConfig:
    """Load the scheduler config; defaults to `config/scheduler.yaml`."""
    return load_yaml_config(path or CONFIG_DIR / "scheduler.yaml", SchedulerConfig)


def schedule(
    template: PlanTemplate,
    *,
    start_date: date,
    capacity: Capacity,
    busy: Sequence[BusyBlock],
    quota: Quota,
    config: SchedulerConfig,
) -> ScheduleResult:
    """Expand `template` into `duration_weeks` of absolutely timed Tasks.

    Week 0 starts on `start_date`; week w covers the seven days from `start_date + 7w`.
    Every time is computed in the local `capacity.timezone` and stored as UTC.
    """
    zone = ZoneInfo(capacity.timezone)
    gap = timedelta(minutes=config.min_gap_minutes)
    milestones = flatten(template.milestones)
    areas = _checkpoint_areas(milestones, template.tasks)
    # Absolute ranges already taken: existing commitments plus timed tasks already placed.
    # All-day tasks occupy nothing.
    occupied: list[tuple[datetime, datetime]] = [(block.start_at, block.end_at) for block in busy]

    tasks: list[ScheduledTask] = []
    trimmed: list[TrimmedItem] = []
    unplaced: list[str] = []

    for week_index in range(template.duration_weeks):
        week_start = start_date + timedelta(days=_DAYS_PER_WEEK * week_index)
        planned, cut = _apply_quota(template.tasks, week_index, quota)
        trimmed.extend(cut)

        for spec, occurrence, target_day in _placements(planned, week_start):
            if spec.task_type in _ALL_DAY_TYPES:
                start_at, end_at = _all_day_bounds(target_day, zone, config.checkpoint_hour)
            else:
                placed = _place(
                    spec,
                    target_day=target_day,
                    week_start=week_start,
                    capacity=capacity,
                    zone=zone,
                    occupied=occupied,
                    gap=gap,
                    config=config,
                )
                if placed is None:
                    if spec.key not in unplaced:
                        unplaced.append(spec.key)
                    continue
                start_at, end_at = placed
                occupied.append(placed)

            tasks.append(
                ScheduledTask(
                    milestone_key=spec.milestone_key,
                    key=spec.key,
                    week_index=week_index,
                    occurrence=occurrence,
                    area=spec.area,
                    task_type=spec.task_type,
                    title=spec.title,
                    description=spec.description,
                    duration_minutes=spec.duration_minutes,
                    start_at=start_at,
                    end_at=end_at,
                    all_day=spec.task_type in _ALL_DAY_TYPES,
                    sort_order=0,
                )
            )

        tasks.extend(
            _checkpoint(milestone, week_index, week_start, zone, config, areas[milestone.key])
            for milestone in milestones
            if milestone.target_week == week_index
        )

    return ScheduleResult(tasks=_with_sort_order(tasks), trimmed=trimmed, unplaced=unplaced)


# --------------------------------------------------------------------- the Quota


def _apply_quota(
    specs: Sequence[TaskSpec], week_index: int, quota: Quota
) -> tuple[list[tuple[TaskSpec, int]], list[TrimmedItem]]:
    """Choose which occurrences of which Tasks this week may keep.

    Deterministic and explainable: everything active in the week is listed, the week's
    minutes are added up, and while the total is over the ceiling the next occurrence in the
    cut order goes. Within an area the later occurrences go first, so a Task keeps its
    rhythm rather than disappearing entirely.
    """
    active = [spec for spec in specs if spec.week_start <= week_index <= spec.week_end]
    planned = [(spec, occurrence) for spec in active for occurrence in range(spec.times_per_week)]
    total = sum(_cost(spec) for spec, _ in planned)
    if total <= quota.weekly_minutes:
        return planned, []

    order = {area: index for index, area in enumerate(quota.cut_order)}
    position = {spec.key: index for index, spec in enumerate(active)}
    # Cut candidates, most droppable first: earliest in the cut order, then latest
    # occurrence, then latest task in the template.
    candidates = sorted(
        (item for item in planned if _cost(item[0]) > 0),
        key=lambda item: (order[item[0].area], -item[1], -position[item[0].key]),
    )
    trimmed: list[TrimmedItem] = []
    dropped: set[tuple[str, int]] = set()
    for spec, occurrence in candidates:
        if total <= quota.weekly_minutes:
            break
        total -= _cost(spec)
        dropped.add((spec.key, occurrence))
        trimmed.append(
            TrimmedItem(
                key=spec.key,
                week_index=week_index,
                occurrence=occurrence,
                area=spec.area,
                reason=(
                    f"week {week_index + 1} exceeded the {quota.weekly_minutes}-minute quota; "
                    f"'{spec.area}' is dropped first"
                ),
            )
        )
    kept = [item for item in planned if (item[0].key, item[1]) not in dropped]
    return kept, trimmed


def _cost(spec: TaskSpec) -> int:
    """What one occurrence spends against the Quota. All-day markers spend nothing."""
    return 0 if spec.task_type in _ALL_DAY_TYPES else spec.duration_minutes


# ------------------------------------------------------------------- day spreading


def _placements(
    planned: Sequence[tuple[TaskSpec, int]], week_start: date
) -> list[tuple[TaskSpec, int, date]]:
    """Give every surviving occurrence the day it should aim for."""
    by_spec: dict[str, list[date]] = {}
    result: list[tuple[TaskSpec, int, date]] = []
    for spec, occurrence in planned:
        days = by_spec.setdefault(spec.key, _target_days(week_start, spec))
        if occurrence < len(days):
            result.append((spec, occurrence, days[occurrence]))
    return result


def _target_days(week_start: date, spec: TaskSpec) -> list[date]:
    """Spread `times_per_week` occurrences evenly over the days `day_hint` allows.

    Candidate days are numbered 0..L-1 and occurrence i takes index
    `round(i * (L-1) / (n-1))` — three occurrences over seven candidates land on 0, 3 and 6.
    Fully deterministic, no randomness.
    """
    candidates = _candidate_days(week_start, spec.day_hint)
    if not candidates:
        return []
    times = spec.times_per_week
    if times <= 1:
        return [candidates[0]]
    last = len(candidates) - 1
    return [candidates[min(round(index * last / (times - 1)), last)] for index in range(times)]


def _candidate_days(week_start: date, day_hint: DayHint) -> list[date]:
    weekdays = _DAY_HINT_WEEKDAYS[day_hint]
    days = [week_start + timedelta(days=offset) for offset in range(_DAYS_PER_WEEK)]
    return [day for day in days if day.weekday() in weekdays]


# ----------------------------------------------------------------------- placement


def _place(
    spec: TaskSpec,
    *,
    target_day: date,
    week_start: date,
    capacity: Capacity,
    zone: ZoneInfo,
    occupied: Sequence[tuple[datetime, datetime]],
    gap: timedelta,
    config: SchedulerConfig,
) -> tuple[datetime, datetime] | None:
    """First slot that fits, from `target_day` up to `max_shift_days` later.

    Shifting later must not leave the week: a task pushed into the next week would silently
    change what that week's progress means.
    """
    week_end = week_start + timedelta(days=_DAYS_PER_WEEK - 1)
    duration = timedelta(minutes=spec.duration_minutes)
    slots = [spec.slot_hint] if spec.slot_hint != "any" else config.slot_order

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
    """First start in the window that fits `duration` and keeps `gap` from everything taken."""
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


# ---------------------------------------------------------------------- checkpoints


def _checkpoint(
    milestone: FlatMilestone,
    week_index: int,
    week_start: date,
    zone: ZoneInfo,
    config: SchedulerConfig,
    area: Area,
) -> ScheduledTask:
    """A Milestone's own all-day marker, on the Sunday of the week it targets."""
    sunday = week_start + timedelta(days=(6 - week_start.weekday()) % _DAYS_PER_WEEK)
    start_at, end_at = _all_day_bounds(sunday, zone, config.checkpoint_hour)
    return ScheduledTask(
        milestone_key=milestone.key,
        key=f"checkpoint_{milestone.key}",
        week_index=week_index,
        occurrence=0,
        area=area,
        task_type="checkpoint",
        title=milestone.title,
        description=milestone.metric,
        duration_minutes=0,
        start_at=start_at,
        end_at=end_at,
        all_day=True,
        sort_order=0,
    )


def _checkpoint_areas(
    milestones: Sequence[FlatMilestone], specs: Sequence[TaskSpec]
) -> dict[str, Area]:
    """A checkpoint belongs to the area its Milestone's own work belongs to."""
    first: dict[str, Area] = {}
    for spec in specs:
        first.setdefault(spec.milestone_key, spec.area)
    return {milestone.key: first.get(milestone.key, "career") for milestone in milestones}


# ------------------------------------------------------------------ time arithmetic


def _local(day: date, minute: int, zone: ZoneInfo) -> datetime:
    """Minute `minute` of a local day, as UTC; 1440 means 00:00 of the next day."""
    extra_days, minute_of_day = divmod(minute, MINUTES_PER_DAY)
    local_date = day + timedelta(days=extra_days)
    local_time = time(hour=minute_of_day // 60, minute=minute_of_day % 60)
    return datetime.combine(local_date, local_time, tzinfo=zone).astimezone(UTC)


def _all_day_bounds(day: date, zone: ZoneInfo, hour: int) -> tuple[datetime, datetime]:
    """All-day task: local `hour`:00 until local 00:00 the next day, both as UTC."""
    return _local(day, hour * 60, zone), _local(day, MINUTES_PER_DAY, zone)


def _with_sort_order(tasks: Sequence[ScheduledTask]) -> list[ScheduledTask]:
    ordered = sorted(tasks, key=lambda task: (task.start_at, task.key, task.occurrence))
    return [task.model_copy(update={"sort_order": index}) for index, task in enumerate(ordered)]
