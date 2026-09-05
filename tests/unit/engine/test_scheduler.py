"""The scheduler carries the determinism promise, so it carries the heaviest coverage."""

from datetime import UTC, date, datetime

import pytest

from services.engine.domain.capacity import BusyBlock, Capacity
from services.engine.domain.plan_template import MilestoneNode, PlanTemplate, TaskSpec
from services.engine.domain.quota import Quota
from services.engine.domain.scheduler import SchedulerConfig, ScheduleResult, schedule

TIMEZONE = "Asia/Taipei"
START = date(2026, 1, 5)  # a Monday


def config() -> SchedulerConfig:
    return SchedulerConfig()


def task(**overrides: object) -> TaskSpec:
    base: dict[str, object] = {
        "key": "writing_block",
        "milestone_key": "probe",
        "title": "Writing block",
        "task_type": "session",
        "area": "career",
        "day_hint": "weekday",
        "slot_hint": "evening",
        "duration_minutes": 60,
        "times_per_week": 2,
        "week_start": 0,
        "week_end": 3,
    }
    return TaskSpec.model_validate(base | overrides)


def template(*tasks: TaskSpec, weeks: int = 4, target_week: int = 3) -> PlanTemplate:
    return PlanTemplate(
        title="A quarter",
        duration_weeks=weeks,
        success_criteria=["The probe is finished."],
        milestones=[
            MilestoneNode(
                key="probe", title="Run the probe", metric="Submitted", target_week=target_week
            )
        ],
        tasks=list(tasks) or [task()],
    )


def unlimited() -> Quota:
    return Quota(drop_first="career", weekly_minutes=100_000)


def test_same_inputs_produce_an_identical_schedule():
    """The whole design rests on this: a hypothesis is only falsifiable if the thing it
    predicted was computed the same way twice.
    """

    def run() -> ScheduleResult:
        return schedule(
            template(),
            start_date=START,
            capacity=Capacity.default(TIMEZONE),
            busy=[],
            quota=unlimited(),
            config=config(),
        )

    assert run().model_dump(mode="json") == run().model_dump(mode="json")


def test_occurrences_spread_evenly_over_the_allowed_days():
    result = schedule(
        template(task(times_per_week=3, day_hint="any")),
        start_date=START,
        capacity=Capacity.default(TIMEZONE),
        busy=[],
        quota=unlimited(),
        config=config(),
    )
    week_one = sorted(
        row.start_at for row in result.tasks if row.week_index == 0 and row.task_type == "session"
    )
    assert len(week_one) == 3
    # Monday, Thursday, Sunday: indices 0, 3 and 6 of seven candidate days.
    assert [moment.astimezone(UTC).date().weekday() for moment in week_one] == [0, 3, 6]


def test_a_task_that_fits_nowhere_is_reported_rather_than_dropped_silently():
    result = schedule(
        template(task(duration_minutes=300, slot_hint="noon")),
        start_date=START,
        capacity=Capacity.default(TIMEZONE),  # noon is a single hour
        busy=[],
        quota=unlimited(),
        config=config(),
    )
    assert result.unplaced == ["writing_block"]
    assert all(row.task_type != "session" for row in result.tasks)


def test_busy_blocks_are_avoided():
    capacity = Capacity.default(TIMEZONE)
    # 19:00-22:00 local on the first Monday, entirely taken.
    busy = [
        BusyBlock(
            start_at=datetime(2026, 1, 5, 11, 0, tzinfo=UTC),
            end_at=datetime(2026, 1, 5, 14, 0, tzinfo=UTC),
        )
    ]
    result = schedule(
        template(task(times_per_week=1, day_hint="mon")),
        start_date=START,
        capacity=capacity,
        busy=busy,
        quota=unlimited(),
        config=config(),
    )
    placed = [row for row in result.tasks if row.key == "writing_block" and row.week_index == 0]
    assert placed, "the task should shift rather than vanish"
    assert all(row.start_at >= busy[0].end_at for row in placed)


def test_every_milestone_gets_a_checkpoint_in_the_week_it_targets():
    result = schedule(
        template(target_week=2),
        start_date=START,
        capacity=Capacity.default(TIMEZONE),
        busy=[],
        quota=unlimited(),
        config=config(),
    )
    checkpoints = [row for row in result.tasks if row.task_type == "checkpoint"]
    assert [row.week_index for row in checkpoints] == [2]
    assert checkpoints[0].all_day is True
    assert checkpoints[0].milestone_key == "probe"


class TestTheQuota:
    """Capacity says what is possible; the quota says what has been allowed."""

    def _result(self, quota: Quota):
        return schedule(
            template(
                task(key="career_work", area="career", times_per_week=2, duration_minutes=60),
                task(
                    key="health_walk",
                    area="health",
                    times_per_week=2,
                    duration_minutes=60,
                    day_hint="any",
                    slot_hint="morning",
                ),
            ),
            start_date=START,
            capacity=Capacity.default(TIMEZONE),
            busy=[],
            quota=quota,
            config=config(),
        )

    def test_a_week_inside_the_ceiling_is_untouched(self):
        result = self._result(Quota(drop_first="career", weekly_minutes=240))
        assert result.trimmed == []

    def test_the_declared_area_is_cut_first(self):
        result = self._result(Quota(drop_first="career", weekly_minutes=180))
        assert {item.area for item in result.trimmed} == {"career"}
        assert all(item.key == "career_work" for item in result.trimmed)

    def test_the_other_ranking_cuts_the_other_way(self):
        result = self._result(Quota(drop_first="health", weekly_minutes=180))
        assert {item.area for item in result.trimmed} == {"health"}

    def test_a_trim_says_why_it_happened(self):
        result = self._result(Quota(drop_first="career", weekly_minutes=180))
        assert "quota" in result.trimmed[0].reason
        assert "career" in result.trimmed[0].reason

    def test_checkpoints_cost_nothing(self):
        """A checkpoint is a moment to look up, not work to fit in."""
        result = self._result(Quota(drop_first="career", weekly_minutes=0))
        assert [row.task_type for row in result.tasks] == ["checkpoint"]


@pytest.mark.parametrize("weeks", [1, 4, 12])
def test_a_task_is_placed_in_every_week_of_its_range(weeks: int):
    result = schedule(
        template(
            task(week_start=0, week_end=weeks - 1, times_per_week=1),
            weeks=weeks,
            target_week=weeks - 1,
        ),
        start_date=START,
        capacity=Capacity.default(TIMEZONE),
        busy=[],
        quota=unlimited(),
        config=config(),
    )
    sessions = [row for row in result.tasks if row.task_type == "session"]
    assert sorted(row.week_index for row in sessions) == list(range(weeks))
