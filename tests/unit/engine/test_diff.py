"""Aligning two schedules on a stable key is what stops a move reading as a delete."""

from datetime import UTC, datetime, timedelta

from services.engine.domain.diff import TaskSnapshotWithKey, diff_tasks

START = datetime(2026, 1, 5, 11, 0, tzinfo=UTC)


def snapshot(
    key: str = "work",
    week: int = 0,
    occurrence: int = 0,
    start: datetime = START,
    minutes: int = 60,
    all_day: bool = False,
) -> TaskSnapshotWithKey:
    return TaskSnapshotWithKey(
        key=key,
        week_index=week,
        occurrence=occurrence,
        title=key.title(),
        start_at=start,
        end_at=start + timedelta(minutes=minutes),
        all_day=all_day,
    )


def kinds(before, after) -> list[str]:
    return [entry.kind for entry in diff_tasks(before, after)]


def test_an_unchanged_task_reports_unchanged():
    assert kinds([snapshot()], [snapshot()]) == ["unchanged"]


def test_a_shifted_task_is_a_move_not_a_delete_plus_an_add():
    moved = snapshot(start=START + timedelta(days=1))
    assert kinds([snapshot()], [moved]) == ["moved"]


def test_duration_changes_are_named():
    assert kinds([snapshot()], [snapshot(minutes=30)]) == ["shortened"]
    assert kinds([snapshot()], [snapshot(minutes=90)]) == ["lengthened"]


def test_an_all_day_flip_counts_as_a_move():
    assert kinds([snapshot()], [snapshot(all_day=True)]) == ["moved"]


def test_additions_and_removals():
    assert kinds([], [snapshot()]) == ["added"]
    assert kinds([snapshot()], []) == ["removed"]


def test_entries_come_back_in_a_stable_order():
    before = [snapshot("b", week=1), snapshot("a", week=0), snapshot("a", week=0, occurrence=1)]
    entries = diff_tasks(before, [])
    assert [(e.week_index, e.key, e.occurrence) for e in entries] == [
        (0, "a", 0),
        (0, "a", 1),
        (1, "b", 0),
    ]


def test_a_move_outranks_a_duration_change():
    moved_and_shortened = snapshot(start=START + timedelta(hours=2), minutes=30)
    assert kinds([snapshot()], [moved_and_shortened]) == ["moved"]
