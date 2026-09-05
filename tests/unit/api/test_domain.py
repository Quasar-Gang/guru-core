"""The API service's own domain: the three questions and the calendar mapping."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from packages.repo.entities import ScheduledTaskRow, ScheduleSlot, Task
from services.api.domain.calendar_mapping import (
    ColorMap,
    load_color_map,
    should_export,
    to_calendar_event,
)
from services.api.domain.errors import InvalidInput
from services.api.domain.questions import QUESTIONS, parse_area, question

START = datetime(2026, 1, 5, 11, 0, tzinfo=UTC)


def row(task_type: str = "session", status: str = "pending", key: str = "work") -> ScheduledTaskRow:
    plan_id = uuid4()
    task = Task(
        id=uuid4(),
        plan_id=plan_id,
        milestone_id=uuid4(),
        key=key,
        week_index=0,
        occurrence=0,
        area="career",
        task_type=task_type,
        title="Writing block",
        description="One section, start to finish.",
        duration_minutes=60,
        status=status,
        completed_at=None,
        sort_order=0,
    )
    slot = ScheduleSlot(
        id=uuid4(),
        plan_id=plan_id,
        task_id=task.id,
        start_at=START,
        end_at=START + timedelta(hours=1),
        all_day=False,
        external_ref=None,
        synced_at=None,
    )
    return ScheduledTaskRow(task=task, slot=slot)


class TestTheThreeQuestions:
    def test_there_are_exactly_three_and_every_one_states_its_purpose(self):
        assert [item.key for item in QUESTIONS] == ["q1", "q2", "q3"]
        assert all(item.purpose for item in QUESTIONS)

    def test_only_q3_forces_a_choice(self):
        assert [bool(item.choices) for item in QUESTIONS] == [False, False, True]

    def test_an_unknown_key_is_rejected(self):
        with pytest.raises(InvalidInput, match="q1, q2, q3"):
            question("q4")

    @pytest.mark.parametrize("value", ["career", "  Health ", "RELATIONSHIPS"])
    def test_q3_accepts_the_three_areas_in_any_casing(self, value: str):
        assert parse_area(value) in ("career", "relationships", "health")

    def test_q3_rejects_prose(self):
        with pytest.raises(InvalidInput, match="career, relationships or health"):
            parse_area("I would rather not say")


class TestCalendarMapping:
    def test_the_shipped_colour_map_loads(self):
        colors = load_color_map()
        assert colors.color_for("anything", "session") != colors.default

    def test_the_most_specific_colour_wins(self):
        colors = ColorMap(default="1", by_task_type={"session": "9"}, by_key={"work": "5"})
        assert colors.color_for("work", "session") == "5"
        assert colors.color_for("other", "session") == "9"
        assert colors.color_for("other", "habit") == "1"

    def test_rest_markers_stay_off_the_calendar(self):
        assert should_export(row("session")) is True
        assert should_export(row("rest")) is False

    def test_an_event_carries_the_task_identity_so_a_second_push_updates(self):
        event = to_calendar_event(row(), load_color_map(), "A quarter")
        assert event.private_props["guru_task_id"]
        assert event.private_props["guru_plan_id"]

    def test_a_finished_task_reads_as_finished_in_the_calendar(self):
        colors = load_color_map()
        assert to_calendar_event(row(status="done"), colors, "Q").summary.startswith("[x]")
        assert to_calendar_event(row(status="missed"), colors, "Q").summary.startswith("[ ]")
        assert to_calendar_event(row(), load_color_map(), "Q").summary == "Writing block"

    def test_the_description_says_where_the_event_came_from(self):
        event = to_calendar_event(row(), load_color_map(), "One quarter to run the probe")
        assert "One quarter to run the probe" in event.description
