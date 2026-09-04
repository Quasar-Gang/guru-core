"""把 ``PlanTemplate`` 展開成帶絕對時間的任務列（PRD 4.3.2）。

純函式、無隨機：同樣的輸入永遠得到同樣的輸出，這是修訂 diff（Task 20）能靠
``(template_key, week_index, occurrence)`` 對齊的前提。

排程失敗不是例外：排不下的項目只記進 ``ScheduleResult.unplaced``，pacing 違規
只記進 ``ScheduleResult.violations``，由 use case 決定要回灌 LLM 重生還是接受。
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

#: ``day_hint`` -> 允許的 ``date.weekday()`` 值。
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

#: 不排具體時刻、一律展開成全天任務的型別（規則 7、8）。
_ALL_DAY_TYPES: frozenset[TaskType] = frozenset({"rest", "checkpoint"})


class SchedulerConfig(BaseModel):
    """``config/scheduler.yaml``：scheduler 的系統層規則，不由 LLM 指定。"""

    model_config = ConfigDict(extra="forbid")

    default_start: Literal["next_monday", "tomorrow"] = "next_monday"
    min_gap_minutes: int = Field(default=30, ge=0)
    max_shift_days: int = Field(default=3, ge=0)
    checkpoint_hour: int = Field(default=0, ge=0, le=23)
    slot_order: list[SlotHint] = ["morning", "evening", "noon", "any"]


class ScheduledTask(BaseModel):
    """展開後的單一任務，對應一列 ``plan_tasks``。"""

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
    """單週對 trait ``pacing`` 的違規；只記錄，不 raise（規則 9）。"""

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
    """讀排程設定，預設 ``config/scheduler.yaml``。"""
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
    """把 ``template`` 展開成 ``duration_weeks`` 週的絕對時間任務列。

    第 0 週的第一天是 ``start_date``，第 w 週涵蓋 ``start_date + 7w`` 起的七天
    （規則 1）。所有時刻先以 ``capacity.timezone`` 當地時間計算，再轉 UTC 儲存
    （規則 11）。
    """
    zone = ZoneInfo(capacity.timezone)
    gap = timedelta(minutes=config.min_gap_minutes)
    # 已佔用的絕對時間區段：既有行程 + 已排定的計時任務。全天任務不佔時段。
    occupied: list[tuple[datetime, datetime]] = [(block.start_at, block.end_at) for block in busy]

    tasks: list[ScheduledTask] = []
    unplaced: list[str] = []

    for week_index in range(template.duration_weeks):
        week_start = start_date + timedelta(days=_DAYS_PER_WEEK * week_index)
        phase = _phase_for_week(template.phases, week_index)

        for item in template.weekly_template:
            for occurrence, target_day in enumerate(_target_days(week_start, item)):
                if item.task_type in _ALL_DAY_TYPES:
                    # 規則 8：不排具體時間，直接產全天任務。
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
                        # 規則 6：往後找不到空檔就記入 unplaced，不產生該任務。
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


# --------------------------------------------------------------------------- 規則 3


def _target_days(week_start: date, item: WeeklyItem) -> list[date]:
    """``day_hint`` 的候選日中，把 ``times_per_week`` 次平均分佈開來。

    候選日依序編號 0..L-1，第 i 次取索引 ``round(i * (L-1) / (n-1))``——
    例如 7 個候選日排 3 次會落在索引 0、3、6。完全確定性，沒有隨機。
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


# ------------------------------------------------------------------------ 規則 4-6


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
    """從 ``target_day`` 起往後最多 ``max_shift_days`` 天找第一個容得下的空檔。

    規則 6：往後挪不得跨出該週（``week_start`` 起的七天）。
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
    """規則 5：區間內第一個容得下 ``duration`` 且與已佔用區段保持 ``gap`` 的起點。"""
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


# ------------------------------------------------------------------------ 規則 7-8


def _checkpoint(
    phase: Phase,
    week_index: int,
    week_start: date,
    zone: ZoneInfo,
    config: SchedulerConfig,
) -> ScheduledTask:
    """規則 7：phase 最後一週的週日放一個全天 checkpoint。"""
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


# ------------------------------------------------------------------------- 規則 11


def _local(day: date, minute: int, zone: ZoneInfo) -> datetime:
    """當地日的第 ``minute`` 分鐘轉成 UTC；``minute`` 可為 1440（次日 00:00）。"""
    extra_days, minute_of_day = divmod(minute, MINUTES_PER_DAY)
    local_date = day + timedelta(days=extra_days)
    local_time = time(hour=minute_of_day // 60, minute=minute_of_day % 60)
    return datetime.combine(local_date, local_time, tzinfo=zone).astimezone(UTC)


def _all_day_bounds(day: date, zone: ZoneInfo, hour: int) -> tuple[datetime, datetime]:
    """全天任務：當地 ``hour``:00 起、次日當地 00:00 止，皆以 UTC 表示。"""
    return _local(day, hour * 60, zone), _local(day, MINUTES_PER_DAY, zone)


# -------------------------------------------------------------------------- 規則 9


def _pacing_violations(
    tasks: Sequence[ScheduledTask], duration_weeks: int, pacing: Pacing | None
) -> list[PacingViolation]:
    """逐週比對 trait pacing。只記錄，絕不 raise。

    兩點刻意的判讀：``rest_days_min`` 只數「有非 rest 任務的天數」（rest 任務
    本身就代表休息日），``session_minutes`` 只檢查有具體時長的任務（全天任務
    沒有可比的時長）。
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
                        f"第 {week_index + 1} 週有 {len(sessions)} 次 session，"
                        f"超過上限 {sessions_max}"
                    ),
                )
            )
        elif len(sessions) < sessions_min:
            violations.append(
                PacingViolation(
                    week_index=week_index,
                    rule="sessions_per_week_min",
                    detail=(
                        f"第 {week_index + 1} 週只有 {len(sessions)} 次 session，"
                        f"低於下限 {sessions_min}"
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
                        f"第 {week_index + 1} 週有 {len(busy_days)} 天排了任務，"
                        f"休息日不足 {pacing.rest_days_min} 天"
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
                        f"第 {week_index + 1} 週的 {task.template_key} 長 {minutes} 分鐘，"
                        f"不在 {minutes_min}–{minutes_max} 分鐘之內"
                    ),
                )
            )

    return violations


# ------------------------------------------------------------------------- 規則 10


def _with_sort_order(tasks: Sequence[ScheduledTask]) -> list[ScheduledTask]:
    ordered = sorted(tasks, key=lambda task: (task.start_at, task.template_key, task.occurrence))
    return [task.model_copy(update={"sort_order": index}) for index, task in enumerate(ordered)]
