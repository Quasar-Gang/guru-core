"""Station 3 computes before it narrates, and classifies rather than grades."""

from datetime import UTC, datetime, timedelta

from services.engine.domain.diff import TaskDiffEntry, TaskSnapshot
from services.engine.domain.reconciliation import classify_revision, compare

START = datetime(2026, 1, 5, 11, 0, tzinfo=UTC)
DIMENSIONS = ["work", "learning", "unclassified"]


def entry(kind: str, key: str = "work") -> TaskDiffEntry:
    snapshot = TaskSnapshot(
        title="Work", start_at=START, end_at=START + timedelta(hours=1), all_day=False
    )
    return TaskDiffEntry(
        key=key,
        week_index=0,
        occurrence=0,
        kind=kind,  # type: ignore[arg-type]
        title="Work",
        before=snapshot if kind != "added" else None,
        after=snapshot if kind != "removed" else None,
    )


def comparison(counts: dict[str, int], changes: list[TaskDiffEntry]):
    return compare(
        status_counts=counts,
        before_shares={"work": 0.62, "unclassified": 0.16},
        after_shares={"work": 0.55, "unclassified": 0.24},
        schedule_changes=changes,
        dimensions=DIMENSIONS,  # type: ignore[arg-type]
    )


def test_execution_is_counted_from_the_task_statuses():
    result = comparison({"done": 6, "missed": 3, "skipped": 1, "pending": 0}, [])
    assert result.execution.planned == 10
    assert result.execution.done == 6
    assert result.execution.completion == 0.6


def test_shares_are_reported_as_a_movement_not_a_snapshot():
    result = comparison({"done": 1}, [])
    work = next(shift for shift in result.shifts if shift.dimension == "work")
    assert (work.before, work.after) == (0.62, 0.55)
    assert work.delta == -0.07


def test_unclassified_gets_its_own_line_because_that_is_the_sharpest_signal():
    result = comparison({"done": 1}, [])
    assert result.unclassified_delta == 0.08


def test_a_dimension_with_no_report_on_either_side_is_simply_zero():
    result = comparison({"done": 1}, [])
    learning = next(shift for shift in result.shifts if shift.dimension == "learning")
    assert (learning.before, learning.after, learning.delta) == (0.0, 0.0, 0.0)


def test_an_empty_plan_does_not_divide_by_zero():
    assert comparison({}, []).execution.completion == 0.0


class TestClassification:
    """Scope that moved because something was learned is not the same as scope that fled."""

    def test_a_plan_that_never_changed_is_not_classified_at_all(self):
        assert classify_revision(comparison({"done": 5, "missed": 5}, [])) is None

    def test_shrinking_while_the_work_was_not_being_done_is_avoidance(self):
        changes = [entry("removed"), entry("removed", "walk")]
        assert classify_revision(comparison({"done": 2, "missed": 8}, changes)) == "avoidance"

    def test_shrinking_with_the_work_being_done_is_a_redesign(self):
        changes = [entry("removed"), entry("removed", "walk")]
        assert classify_revision(comparison({"done": 8, "missed": 2}, changes)) == "growth"

    def test_growing_is_growth_regardless_of_completion(self):
        changes = [entry("added"), entry("added", "walk")]
        assert classify_revision(comparison({"done": 1, "missed": 9}, changes)) == "growth"

    def test_a_pure_reshuffle_is_growth_rather_than_a_verdict_on_the_person(self):
        assert classify_revision(comparison({"done": 5, "missed": 5}, [entry("moved")])) == "growth"
