"""Plan task -> Google Calendar event mapping (plan Task 34, PRD 4.3.4)."""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from packages.repo.entities import PlanTask
from services.api.domain.calendar_mapping import (
    ColorMap,
    load_color_map,
    should_export,
    to_calendar_event,
)

START = datetime(2026, 9, 8, 11, 30, tzinfo=UTC)
PLAN_ID = UUID("11111111-1111-1111-1111-111111111111")

COLORS = ColorMap(
    default="8",
    by_task_type={"session": "9", "habit": "2", "rest": "8"},
    by_template_key={"long_run": "5"},
)


def _task(**overrides: Any) -> PlanTask:
    fields: dict[str, Any] = {
        "id": uuid4(),
        "plan_id": PLAN_ID,
        "template_key": "easy_run",
        "week_index": 0,
        "phase_index": 0,
        "occurrence": 0,
        "task_type": "session",
        "title": "easy run",
        "description": "conversational pace",
        "start_at": START,
        "end_at": START + timedelta(minutes=30),
        "all_day": False,
        "status": "pending",
        "completed_at": None,
        "missed_reason": None,
        "external_ref": None,
        "synced_at": None,
        "sort_order": 0,
    }
    fields.update(overrides)
    return PlanTask(**fields)


# --- summary ----------------------------------------------------------------


def test_done_task_summary_gets_check_prefix() -> None:
    event = to_calendar_event(_task(status="done", title="easy run"), "P", COLORS)

    assert event.summary == "✓ easy run"


def test_missed_task_summary_gets_cross_prefix() -> None:
    event = to_calendar_event(_task(status="missed", title="easy run"), "P", COLORS)

    assert event.summary == "✗ easy run"


def test_pending_task_summary_is_the_plain_title() -> None:
    event = to_calendar_event(_task(status="pending", title="easy run"), "P", COLORS)

    assert event.summary == "easy run"


# --- description ------------------------------------------------------------


def test_description_has_provenance_line() -> None:
    event = to_calendar_event(_task(week_index=0), "P", COLORS)

    assert event.description.startswith("conversational pace")
    assert event.description.endswith("來自 guru-core · P · 第 1 週")


def test_description_is_provenance_only_when_the_task_has_none() -> None:
    event = to_calendar_event(_task(description="", week_index=2), "P", COLORS)

    assert event.description == "來自 guru-core · P · 第 3 週"


# --- ids and times ----------------------------------------------------------


def test_private_props_carry_ids() -> None:
    task = _task()

    event = to_calendar_event(task, "P", COLORS)

    assert event.private_props == {
        "guru_task_id": str(task.id),
        "guru_plan_id": str(PLAN_ID),
    }


def test_times_are_copied_verbatim() -> None:
    task = _task()

    event = to_calendar_event(task, "P", COLORS)

    assert (event.start_at, event.end_at) == (task.start_at, task.end_at)


def test_all_day_task_keeps_the_all_day_flag() -> None:
    event = to_calendar_event(_task(all_day=True), "P", COLORS)

    assert event.all_day is True


# --- colors -----------------------------------------------------------------


def test_color_by_task_type() -> None:
    event = to_calendar_event(_task(task_type="habit"), "P", COLORS)

    assert event.color_id == "2"


def test_color_by_template_key_wins_over_task_type() -> None:
    event = to_calendar_event(_task(template_key="long_run", task_type="session"), "P", COLORS)

    assert event.color_id == "5"


def test_color_falls_back_to_the_default() -> None:
    event = to_calendar_event(_task(template_key="unknown", task_type="unknown"), "P", COLORS)

    assert event.color_id == "8"


def test_shipped_color_map_covers_the_task_types() -> None:
    color_map = load_color_map()

    assert color_map.color_for("anything", "checkpoint") == "11"
    assert color_map.color_for("anything", "unknown") == color_map.default


# --- should_export ----------------------------------------------------------


def test_rest_excluded_by_default() -> None:
    assert should_export(_task(task_type="rest"), include_rest=False) is False


def test_rest_included_when_the_user_asked_for_it() -> None:
    assert should_export(_task(task_type="rest"), include_rest=True) is True


def test_every_other_task_type_is_exported() -> None:
    assert should_export(_task(task_type="session"), include_rest=False) is True
