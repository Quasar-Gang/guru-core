"""The scheduler's 11 placement rules (PRD 4.3.2)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from services.plan_engine.domain.capacity import BusyBlock, Capacity, TimeWindow
from services.plan_engine.domain.difficulty import Pacing
from services.plan_engine.domain.scheduler import (
    ScheduledTask,
    SchedulerConfig,
    ScheduleResult,
    load_scheduler_config,
    schedule,
)
from services.plan_engine.domain.template import (
    DayHint,
    Milestone,
    Phase,
    PlanTemplate,
    SlotHint,
    TaskType,
    WeeklyItem,
)

MONDAY = date(2026, 9, 7)
UTC_CAPACITY = Capacity.default("UTC")


# --------------------------------------------------------------------------- helpers


def _item(
    key: str,
    day_hint: DayHint,
    slot_hint: SlotHint,
    duration_minutes: int,
    times: int = 1,
    task_type: TaskType = "session",
) -> WeeklyItem:
    return WeeklyItem(
        key=key,
        title=key.replace("_", " "),
        task_type=task_type,
        day_hint=day_hint,
        slot_hint=slot_hint,
        duration_minutes=duration_minutes,
        description=f"desc of {key}",
        times_per_week=times,
    )


def _p(index: int, week_start: int, week_end: int) -> Phase:
    return Phase(
        index=index,
        name=f"phase {index}",
        week_start=week_start,
        week_end=week_end,
        focus=f"focus {index}",
        milestone=Milestone(title=f"milestone {index}", metric=f"metric {index}"),
    )


def _tpl(
    items: list[WeeklyItem],
    duration_weeks: int = 1,
    phases: list[Phase] | None = None,
) -> PlanTemplate:
    return PlanTemplate(
        title="t",
        goal_statement="g",
        duration_weeks=duration_weeks,
        success_criteria=["c"],
        phases=phases or [_p(0, 0, duration_weeks - 1)],
        weekly_template=items,
    )


def _pacing(
    sessions_per_week: tuple[int, int] = (0, 7),
    session_minutes: tuple[int, int] = (5, 300),
    rest_days_min: int = 0,
) -> Pacing:
    return Pacing(
        sessions_per_week=sessions_per_week,
        session_minutes=session_minutes,
        rest_days_min=rest_days_min,
        progression_rate=0.1,
        missed_policy="none",
        intensity_bias="medium",
    )


def _run(
    template: PlanTemplate,
    *,
    start_date: date = MONDAY,
    capacity: Capacity | None = None,
    busy: Sequence[BusyBlock] = (),
    pacing: Pacing | None = None,
    config: SchedulerConfig | None = None,
) -> ScheduleResult:
    return schedule(
        template,
        start_date=start_date,
        capacity=capacity or UTC_CAPACITY,
        busy=busy,
        pacing=pacing,
        config=config or SchedulerConfig(),
    )


def _capacity_with_only_30min_morning() -> Capacity:
    window = TimeWindow(start_minute=7 * 60, end_minute=7 * 60 + 30)
    return Capacity(
        timezone="UTC",
        slots={weekday: {"morning": [window]} for weekday in range(7)},
    )


def _overlaps(task: ScheduledTask, block: BusyBlock) -> bool:
    return task.start_at < block.end_at and block.start_at < task.end_at


def _utc(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=UTC)


def _of(tasks: Sequence[ScheduledTask], key: str) -> list[ScheduledTask]:
    return [t for t in tasks if t.template_key == key]


# --------------------------------------------------------------------------- config


def test_scheduler_config_loads_from_yaml() -> None:
    cfg = load_scheduler_config()
    assert cfg.default_start == "next_monday"
    assert cfg.min_gap_minutes == 30
    assert cfg.max_shift_days == 3
    assert cfg.checkpoint_hour == 0
    assert cfg.slot_order == ["morning", "evening", "noon", "any"]


# --------------------------------------------------------------------------- rule 1-2


def test_week_zero_starts_on_given_date() -> None:
    r = _run(_tpl([_item("run", "mon", "morning", 30)]))
    run = _of(r.tasks, "run")
    assert len(run) == 1
    assert run[0].week_index == 0
    assert run[0].start_at.date() == MONDAY


def test_duration_weeks_produces_that_many_weeks() -> None:
    r = _run(_tpl([_item("run", "tue", "evening", 30)], duration_weeks=4))
    assert {t.week_index for t in r.tasks if t.template_key == "run"} == {0, 1, 2, 3}


# --------------------------------------------------------------------------- rule 3


def test_day_hint_specific_weekday_lands_on_that_weekday() -> None:
    r = _run(_tpl([_item("run", "thu", "morning", 30)], duration_weeks=3))
    run = _of(r.tasks, "run")
    assert len(run) == 3
    assert all(t.start_at.weekday() == 3 for t in run)


def test_day_hint_weekday_never_lands_on_weekend() -> None:
    r = _run(_tpl([_item("run", "weekday", "morning", 30, times=5)], duration_weeks=2))
    run = _of(r.tasks, "run")
    assert len(run) == 10
    assert all(t.start_at.weekday() < 5 for t in run)


def test_day_hint_weekend_only_lands_on_sat_or_sun() -> None:
    r = _run(_tpl([_item("run", "weekend", "morning", 30, times=2)], duration_weeks=2))
    run = _of(r.tasks, "run")
    assert len(run) == 4
    assert all(t.start_at.weekday() in (5, 6) for t in run)


def test_times_per_week_three_spreads_across_week() -> None:
    r = _run(_tpl([_item("run", "any", "any", 30, times=3)]))
    run = sorted(_of(r.tasks, "run"), key=lambda t: t.start_at)
    days = [t.start_at.date() for t in run]
    assert len(set(days)) == 3
    # evenly spread over the 7 candidate days -> indices 0 / 3 / 6
    assert [(d - MONDAY).days for d in days] == [0, 3, 6]
    assert all((b - a).days >= 1 for a, b in zip(days, days[1:], strict=False))
    assert [t.occurrence for t in run] == [0, 1, 2]


# --------------------------------------------------------------------------- rule 4-5


def test_slot_hint_morning_lands_in_morning_window() -> None:
    r = _run(_tpl([_item("run", "tue", "morning", 30)]))
    task = _of(r.tasks, "run")[0]
    assert task.start_at.hour >= 7
    assert task.end_at <= _utc(MONDAY + timedelta(days=1), 9)


def test_slot_hint_any_falls_back_through_slot_order() -> None:
    tuesday = MONDAY + timedelta(days=1)
    # Tuesday morning is fully booked -> the next slot in slot_order is evening, not noon
    busy = [BusyBlock(start_at=_utc(day, 6), end_at=_utc(day, 10)) for day in (MONDAY, tuesday)]
    r = _run(_tpl([_item("run", "tue", "any", 30)]), busy=busy)
    task = _of(r.tasks, "run")[0]
    assert task.start_at.date() == tuesday
    assert 19 <= task.start_at.hour < 22


def test_busy_block_is_avoided() -> None:
    tuesday = MONDAY + timedelta(days=1)
    busy = [BusyBlock(start_at=_utc(tuesday, 19), end_at=_utc(tuesday, 20, 30))]
    r = _run(_tpl([_item("run", "tue", "evening", 30)]), busy=busy)
    assert r.tasks
    assert all(not _overlaps(t, busy[0]) for t in r.tasks)
    task = _of(r.tasks, "run")[0]
    assert task.start_at >= busy[0].end_at + timedelta(minutes=30)


def test_min_gap_between_two_tasks_respected() -> None:
    r = _run(
        _tpl([_item("a", "tue", "morning", 30), _item("b", "tue", "morning", 30)]),
    )
    first, second = sorted(_of(r.tasks, "a") + _of(r.tasks, "b"), key=lambda t: t.start_at)
    assert second.start_at - first.end_at >= timedelta(minutes=30)


# --------------------------------------------------------------------------- rule 6


def test_conflict_shifts_to_next_day_within_week() -> None:
    tuesday = MONDAY + timedelta(days=1)
    busy = [BusyBlock(start_at=_utc(tuesday, 0), end_at=_utc(tuesday, 23, 59))]
    r = _run(_tpl([_item("run", "tue", "morning", 60)]), busy=busy)
    task = _of(r.tasks, "run")[0]
    assert task.start_at.date() == tuesday + timedelta(days=1)
    assert r.unplaced == []


def test_conflict_shift_never_crosses_the_week_boundary() -> None:
    sunday = MONDAY + timedelta(days=6)
    busy = [BusyBlock(start_at=_utc(sunday, 0), end_at=_utc(sunday, 23, 59))]
    r = _run(_tpl([_item("run", "sun", "morning", 60)], duration_weeks=2), busy=busy)
    run = _of(r.tasks, "run")
    # week 0 Sunday does not fit and shifting lands in week 1, which is not allowed;
    # week 1 itself is unaffected
    assert [t.week_index for t in run] == [1]
    assert run[0].start_at.date() == MONDAY + timedelta(days=13)
    assert r.unplaced == ["run"]


def test_unplaceable_task_recorded_in_unplaced_not_raised() -> None:
    r = _run(
        _tpl([_item("run", "tue", "morning", 240)]),
        capacity=_capacity_with_only_30min_morning(),
    )
    assert "run" in r.unplaced
    assert _of(r.tasks, "run") == []
    # the only task produced is the rule 7 checkpoint (all-day tasks ignore capacity)
    assert {t.task_type for t in r.tasks} == {"checkpoint"}


# --------------------------------------------------------------------------- rule 7-8


def test_checkpoint_added_on_last_sunday_of_each_phase() -> None:
    r = _run(
        _tpl(
            [_item("run", "tue", "morning", 30)],
            duration_weeks=8,
            phases=[_p(0, 0, 3), _p(1, 4, 7)],
        ),
        capacity=UTC_CAPACITY,
    )
    cps = sorted((t for t in r.tasks if t.task_type == "checkpoint"), key=lambda t: t.start_at)
    assert len(cps) == 2
    assert all(t.all_day for t in cps)
    assert cps[0].week_index == 3 and cps[1].week_index == 7
    assert cps[0].start_at.weekday() == 6
    assert cps[0].template_key == "checkpoint_p0"
    assert cps[0].title == "milestone 0" and cps[0].description == "metric 0"
    assert cps[0].end_at - cps[0].start_at == timedelta(days=1)


def test_rest_task_is_all_day() -> None:
    r = _run(_tpl([_item("off", "sun", "any", 30, task_type="rest")]))
    rest = _of(r.tasks, "off")[0]
    assert rest.all_day is True
    assert rest.start_at == _utc(MONDAY + timedelta(days=6), 0)
    assert rest.end_at == _utc(MONDAY + timedelta(days=7), 0)


# --------------------------------------------------------------------------- rule 9


def test_pacing_max_violation_recorded() -> None:
    pacing = _pacing(sessions_per_week=(2, 3))
    r = _run(_tpl([_item("a", "any", "any", 30, times=5)]), pacing=pacing)
    assert any(v.rule == "sessions_per_week_max" for v in r.violations)
    assert all(v.week_index == 0 for v in r.violations)


def test_pacing_min_violation_recorded() -> None:
    pacing = _pacing(sessions_per_week=(4, 6))
    r = _run(_tpl([_item("a", "any", "any", 30, times=2)]), pacing=pacing)
    assert any(v.rule == "sessions_per_week_min" for v in r.violations)


def test_pacing_rest_days_violation_recorded() -> None:
    pacing = _pacing(sessions_per_week=(0, 7), rest_days_min=2)
    # 6 training days a week leaves only 1 rest day -> violation
    r = _run(_tpl([_item("a", "any", "any", 30, times=6)]), pacing=pacing)
    assert any(v.rule == "rest_days_min" for v in r.violations)


def test_pacing_session_minutes_violation_recorded() -> None:
    pacing = _pacing(session_minutes=(20, 45))
    r = _run(_tpl([_item("a", "tue", "morning", 90)]), pacing=pacing)
    assert any(v.rule == "session_minutes" for v in r.violations)


def test_no_violations_when_within_pacing() -> None:
    pacing = _pacing(sessions_per_week=(1, 3), session_minutes=(20, 60), rest_days_min=2)
    r = _run(
        _tpl([_item("a", "any", "any", 30, times=2)], duration_weeks=3),
        pacing=pacing,
    )
    assert r.violations == []
    assert r.unplaced == []


# --------------------------------------------------------------------------- rule 10-11


def test_sort_order_is_monotonic_by_start_at() -> None:
    r = _run(
        _tpl(
            [
                _item("b", "any", "any", 30, times=3),
                _item("a", "weekday", "evening", 45, times=2),
                _item("off", "sun", "any", 30, task_type="rest"),
            ],
            duration_weeks=3,
            phases=[_p(0, 0, 1), _p(1, 2, 2)],
        )
    )
    ordered = sorted(r.tasks, key=lambda t: t.sort_order)
    assert [t.start_at for t in ordered] == sorted(t.start_at for t in r.tasks)
    assert [t.sort_order for t in ordered] == list(range(len(r.tasks)))


def test_unique_key_tuple_never_repeats() -> None:
    r = _run(
        _tpl(
            [
                _item("b", "any", "any", 30, times=3),
                _item("a", "weekday", "evening", 45, times=2),
                _item("off", "sun", "any", 30, task_type="rest"),
            ],
            duration_weeks=4,
            phases=[_p(0, 0, 1), _p(1, 2, 3)],
        )
    )
    keys = [(t.template_key, t.week_index, t.occurrence) for t in r.tasks]
    assert len(keys) == len(set(keys))
    assert all(t.start_at.tzinfo is not None and t.end_at.tzinfo is not None for t in r.tasks)


def test_timezone_conversion_produces_local_morning() -> None:
    cap = Capacity.default("Asia/Taipei")
    r = _run(_tpl([_item("run", "tue", "morning", 30)]), capacity=cap)
    local = _of(r.tasks, "run")[0].start_at.astimezone(ZoneInfo("Asia/Taipei"))
    assert 7 <= local.hour < 9
    assert local.date() == MONDAY + timedelta(days=1)


def test_dst_spring_forward_keeps_local_wall_clock() -> None:
    # 2027-03-14 is the America/New_York spring-forward date (02:00 -> 03:00).
    cap = Capacity.default("America/New_York")
    tz = ZoneInfo("America/New_York")
    start = date(2027, 3, 8)  # Monday
    r = _run(
        _tpl([_item("run", "any", "morning", 30, times=7)], duration_weeks=1),
        start_date=start,
        capacity=cap,
    )
    run = sorted(_of(r.tasks, "run"), key=lambda t: t.start_at)
    assert len(run) == 7
    locals_ = [t.start_at.astimezone(tz) for t in run]
    assert all(7 <= dt.hour < 9 for dt in locals_)
    # the UTC offset differs across the transition, but the local wall clock does not
    assert {dt.utcoffset() for dt in locals_} == {timedelta(hours=-5), timedelta(hours=-4)}
