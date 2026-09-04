"""PlanTemplate schema 與 phases 覆蓋驗證。"""

from typing import Any

import pytest
from pydantic import ValidationError

from services.plan_engine.domain import (
    Milestone,
    Phase,
    PlanTemplate,
    PlanTemplateOutput,
    WeeklyItem,
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


def _weekly_item(**overrides: Any) -> WeeklyItem:
    kwargs: dict[str, Any] = {
        "key": "long_run",
        "title": "長距離慢跑",
        "task_type": "session",
        "day_hint": "sat",
        "slot_hint": "morning",
        "duration_minutes": 60,
        "description": "慢速跑 60 分鐘",
    }
    kwargs.update(overrides)
    return WeeklyItem(**kwargs)


def _template(**overrides: Any) -> PlanTemplate:
    """建立一個合法完整的 template，欄位可用 overrides 覆寫。"""
    kwargs: dict[str, Any] = {
        "title": "12 週 5K 跑進 30 分",
        "goal_statement": "12 週內 5K 跑進 30 分鐘",
        "duration_weeks": 8,
        "assumptions": ["每週可跑三次"],
        "success_criteria": ["5K 用時 ≤ 30 分"],
        "phases": [_phase(0, 0, 3), _phase(1, 4, 7)],
        "weekly_template": [_weekly_item()],
    }
    kwargs.update(overrides)
    return PlanTemplate(**kwargs)


def test_phases_must_cover_full_duration() -> None:
    with pytest.raises(ValidationError, match="week_end"):
        _template(duration_weeks=12, phases=[_phase(0, 0, 3)])


def test_phases_must_be_contiguous() -> None:
    with pytest.raises(ValidationError):
        _template(duration_weeks=8, phases=[_phase(0, 0, 3), _phase(1, 5, 7)])


def test_valid_template_accepted() -> None:
    t = _template(duration_weeks=8, phases=[_phase(0, 0, 3), _phase(1, 4, 7)])
    assert t.duration_weeks == 8


def test_template_rejects_unknown_field() -> None:
    with pytest.raises(ValidationError):
        _template(difficulty="hard")


def test_first_phase_must_start_at_week_zero() -> None:
    with pytest.raises(ValidationError):
        _template(duration_weeks=8, phases=[_phase(0, 1, 3), _phase(1, 4, 7)])


def test_phase_week_start_after_week_end_rejected() -> None:
    with pytest.raises(ValidationError):
        _template(duration_weeks=8, phases=[_phase(0, 3, 0), _phase(1, 4, 7)])


def test_phase_indexes_must_be_contiguous_from_zero() -> None:
    with pytest.raises(ValidationError):
        _template(duration_weeks=8, phases=[_phase(0, 0, 3), _phase(2, 4, 7)])


def test_phase_indexes_must_start_at_zero() -> None:
    with pytest.raises(ValidationError):
        _template(duration_weeks=8, phases=[_phase(1, 0, 3), _phase(2, 4, 7)])


@pytest.mark.parametrize("bad_key", ["Long_Run", "long-run", "long run", ""])
def test_weekly_item_key_pattern(bad_key: str) -> None:
    with pytest.raises(ValidationError):
        _weekly_item(key=bad_key)


@pytest.mark.parametrize("minutes", [4, 301])
def test_weekly_item_duration_bounds(minutes: int) -> None:
    with pytest.raises(ValidationError):
        _weekly_item(duration_minutes=minutes)


@pytest.mark.parametrize("times", [0, 8])
def test_weekly_item_times_per_week_bounds(times: int) -> None:
    with pytest.raises(ValidationError):
        _weekly_item(times_per_week=times)


def test_weekly_item_defaults() -> None:
    item = _weekly_item()
    assert item.times_per_week == 1
    item_no_desc = WeeklyItem(
        key="rest",
        title="休息",
        task_type="rest",
        day_hint="any",
        slot_hint="any",
        duration_minutes=30,
    )
    assert item_no_desc.description == ""


def test_success_criteria_and_phases_min_length() -> None:
    with pytest.raises(ValidationError):
        _template(success_criteria=[])
    with pytest.raises(ValidationError):
        _template(phases=[])
    with pytest.raises(ValidationError):
        _template(weekly_template=[])


def test_title_max_length() -> None:
    with pytest.raises(ValidationError):
        _template(title="x" * 41)


def test_plan_template_output_wraps_template() -> None:
    out = PlanTemplateOutput(template=_template())
    assert out.template.duration_weeks == 8
