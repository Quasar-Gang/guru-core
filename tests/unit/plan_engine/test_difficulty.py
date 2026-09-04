"""難度推導：係數換算、phases 重算與 pacing 夾住（PRD 4.3.1.1）。"""

from typing import Any

from services.plan_engine.domain import (
    Difficulty,
    DifficultyCoefficients,
    DifficultyConfig,
    Milestone,
    Pacing,
    Phase,
    PlanTemplate,
    WeeklyItem,
    derive,
    load_difficulty_config,
)

CFG = DifficultyConfig(
    coefficients={
        Difficulty.easy: DifficultyCoefficients(
            frequency=0.6, duration=0.75, weeks=1.25, title_suffix="（輕鬆）"
        ),
        Difficulty.hard: DifficultyCoefficients(
            frequency=1.0, duration=1.0, weeks=1.0, title_suffix="（穩健）"
        ),
        Difficulty.extremely_hard: DifficultyCoefficients(
            frequency=1.3, duration=1.25, weeks=0.85, title_suffix="（挑戰）"
        ),
    }
)


def _phase(index: int, week_start: int, week_end: int) -> Phase:
    return Phase(
        index=index,
        name=f"phase-{index}",
        week_start=week_start,
        week_end=week_end,
        focus="build the base",
        milestone=Milestone(title="checkpoint", metric="run 5k without stopping"),
    )


def _base(**overrides: Any) -> PlanTemplate:
    """12 週、4 次/週、40 分的合法基準模板。"""
    item_keys = {"times_per_week", "duration_minutes", "task_type", "day_hint", "slot_hint"}
    item_kwargs: dict[str, Any] = {
        "key": "long_run",
        "title": "長距離慢跑",
        "task_type": "session",
        "day_hint": "any",
        "slot_hint": "morning",
        "duration_minutes": 40,
        "description": "慢速跑 40 分鐘",
        "times_per_week": 4,
    }
    item_kwargs.update({k: v for k, v in overrides.items() if k in item_keys})
    kwargs: dict[str, Any] = {
        "title": "12 週 5K 跑進 30 分",
        "goal_statement": "12 週後 5K 跑進 30 分",
        "duration_weeks": 12,
        "assumptions": ["每週可跑四次"],
        "success_criteria": ["5K 成績 < 30:00", "連續四週無傷"],
        "phases": [_phase(0, 0, 3), _phase(1, 4, 7), _phase(2, 8, 11)],
        "weekly_template": [WeeklyItem(**item_kwargs)],
    }
    kwargs.update({k: v for k, v in overrides.items() if k not in item_keys})
    return PlanTemplate(**kwargs)


BASE = _base()


def test_hard_is_identity_except_title() -> None:
    out = derive(BASE, Difficulty.hard, CFG, None)
    assert out.duration_weeks == BASE.duration_weeks
    assert out.weekly_template == BASE.weekly_template
    assert out.title.endswith("（穩健）")


def test_easy_reduces_frequency_and_extends_weeks() -> None:
    out = derive(BASE, Difficulty.easy, CFG, None)  # BASE: 12 週, 4 次/週, 40 分
    assert out.duration_weeks == 15
    assert sum(i.times_per_week for i in out.weekly_template) == 2  # round(4*0.6)=2
    assert out.weekly_template[0].duration_minutes == 30  # round(40*0.75)


def test_extremely_hard_capped_by_trait_pacing() -> None:
    pacing = Pacing(
        sessions_per_week=(2, 3),
        session_minutes=(20, 45),
        rest_days_min=2,
        progression_rate=0.05,
        missed_policy="none",
        deload_every_weeks=None,
        intensity_bias="low",
    )
    out = derive(BASE, Difficulty.extremely_hard, CFG, pacing)
    assert sum(i.times_per_week for i in out.weekly_template if i.task_type == "session") <= 3
    assert all(i.duration_minutes <= 45 for i in out.weekly_template)


def test_all_three_share_goal_and_criteria() -> None:
    outs = [derive(BASE, d, CFG, None) for d in Difficulty]
    assert len({o.goal_statement for o in outs}) == 1
    assert len({tuple(o.success_criteria) for o in outs}) == 1
    assert len({tuple(o.assumptions) for o in outs}) == 1


def test_phases_remain_contiguous_after_scaling() -> None:
    out = derive(BASE, Difficulty.easy, CFG, None)
    assert out.phases[0].week_start == 0
    assert out.phases[-1].week_end == out.duration_weeks - 1
    for a, b in zip(out.phases, out.phases[1:], strict=False):
        assert b.week_start == a.week_end + 1


def test_derive_never_produces_zero_frequency() -> None:
    base = _base(times_per_week=1)
    out = derive(base, Difficulty.easy, CFG, None)
    assert all(i.times_per_week >= 1 for i in out.weekly_template)


def test_pacing_raises_frequency_up_to_minimum() -> None:
    pacing = Pacing(
        sessions_per_week=(5, 6),
        session_minutes=(20, 60),
        rest_days_min=1,
        progression_rate=0.05,
        missed_policy="none",
        intensity_bias="medium",
    )
    out = derive(BASE, Difficulty.easy, CFG, pacing)
    assert sum(i.times_per_week for i in out.weekly_template if i.task_type == "session") == 5


def test_pacing_lifts_short_sessions_to_minimum_minutes() -> None:
    pacing = Pacing(
        sessions_per_week=(1, 7),
        session_minutes=(45, 60),
        rest_days_min=0,
        progression_rate=0.05,
        missed_policy="none",
        intensity_bias="medium",
    )
    out = derive(BASE, Difficulty.easy, CFG, pacing)  # 30 分 → 夾到 45
    assert out.weekly_template[0].duration_minutes == 45


def test_rest_days_min_limits_weekly_sessions() -> None:
    pacing = Pacing(
        sessions_per_week=(1, 7),
        session_minutes=(20, 60),
        rest_days_min=5,  # 一週最多排 2 天
        progression_rate=0.05,
        missed_policy="none",
        intensity_bias="low",
    )
    out = derive(BASE, Difficulty.extremely_hard, CFG, pacing)
    assert sum(i.times_per_week for i in out.weekly_template if i.task_type == "session") <= 2


def test_duration_weeks_never_below_phase_count() -> None:
    base = _base(duration_weeks=3, phases=[_phase(0, 0, 0), _phase(1, 1, 1), _phase(2, 2, 2)])
    out = derive(base, Difficulty.extremely_hard, CFG, None)  # round(3*0.85)=3 → 仍 >= 3
    assert out.duration_weeks >= len(out.phases)
    assert out.phases[-1].week_end == out.duration_weeks - 1


def test_non_session_items_are_not_touched_by_session_clamp() -> None:
    habit = WeeklyItem(
        key="sleep_log",
        title="睡眠紀錄",
        task_type="habit",
        day_hint="any",
        slot_hint="evening",
        duration_minutes=10,
        times_per_week=7,
    )
    base = _base(weekly_template=[*BASE.weekly_template, habit])
    pacing = Pacing(
        sessions_per_week=(1, 2),
        session_minutes=(5, 60),
        rest_days_min=0,
        progression_rate=0.05,
        missed_policy="none",
        intensity_bias="low",
    )
    out = derive(base, Difficulty.hard, CFG, pacing)
    by_key = {i.key: i for i in out.weekly_template}
    assert by_key["sleep_log"].times_per_week == 7
    assert by_key["long_run"].times_per_week == 2


def test_load_difficulty_config_reads_real_file() -> None:
    config = load_difficulty_config()
    assert set(config.coefficients) == set(Difficulty)
    assert config.coefficients[Difficulty.hard].frequency == 1.0
    assert config.coefficients[Difficulty.easy].title_suffix == "（輕鬆）"
