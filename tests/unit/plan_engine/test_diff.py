"""Revision diff aligned on (template_key, week_index, occurrence) (PRD 3.8 / 4.3.6)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from services.plan_engine.domain.diff import (
    TaskDiffEntry,
    TaskSnapshot,
    TaskSnapshotWithKey,
    diff_tasks,
)
from services.plan_engine.domain.scheduler import ScheduledTask

BASE = datetime(2026, 9, 7, 18, 0, tzinfo=UTC)


# --------------------------------------------------------------------------- helpers


def _snap(
    key: str = "easy_run",
    *,
    week_index: int = 0,
    occurrence: int = 0,
    title: str = "Easy run",
    start_at: datetime = BASE,
    minutes: int = 30,
    all_day: bool = False,
) -> TaskSnapshotWithKey:
    return TaskSnapshotWithKey(
        template_key=key,
        week_index=week_index,
        occurrence=occurrence,
        title=title,
        start_at=start_at,
        end_at=start_at + timedelta(minutes=minutes),
        all_day=all_day,
    )


def _task(
    key: str = "easy_run",
    *,
    week_index: int = 0,
    occurrence: int = 0,
    title: str = "Easy run",
    start_at: datetime = BASE,
    minutes: int = 30,
    all_day: bool = False,
) -> ScheduledTask:
    return ScheduledTask(
        template_key=key,
        week_index=week_index,
        phase_index=0,
        occurrence=occurrence,
        task_type="session",
        title=title,
        description=f"desc of {key}",
        start_at=start_at,
        end_at=start_at + timedelta(minutes=minutes),
        all_day=all_day,
        sort_order=0,
    )


def _kinds(entries: list[TaskDiffEntry]) -> list[str]:
    return [entry.kind for entry in entries]


# ------------------------------------------------------------------------ each kind


def test_task_only_in_after_is_added() -> None:
    (entry,) = diff_tasks([], [_task()])

    assert entry.kind == "added"
    assert entry.before is None
    assert entry.after == TaskSnapshot(
        title="Easy run",
        start_at=BASE,
        end_at=BASE + timedelta(minutes=30),
        all_day=False,
    )
    assert (entry.template_key, entry.week_index, entry.occurrence) == ("easy_run", 0, 0)
    assert entry.title == "Easy run"


def test_task_only_in_before_is_removed() -> None:
    (entry,) = diff_tasks([_snap()], [])

    assert entry.kind == "removed"
    assert entry.after is None
    assert entry.before is not None
    assert entry.before.start_at == BASE
    assert entry.title == "Easy run"


def test_different_start_at_is_moved() -> None:
    later = BASE + timedelta(hours=2)

    (entry,) = diff_tasks([_snap()], [_task(start_at=later)])

    assert entry.kind == "moved"
    assert entry.before is not None
    assert entry.after is not None
    assert entry.before.start_at == BASE
    assert entry.after.start_at == later


def test_same_start_and_shorter_duration_is_shortened() -> None:
    (entry,) = diff_tasks([_snap(minutes=45)], [_task(minutes=30)])

    assert entry.kind == "shortened"


def test_same_start_and_longer_duration_is_lengthened() -> None:
    (entry,) = diff_tasks([_snap(minutes=30)], [_task(minutes=45)])

    assert entry.kind == "lengthened"


def test_identical_task_is_unchanged() -> None:
    (entry,) = diff_tasks([_snap()], [_task()])

    assert entry.kind == "unchanged"


def test_moved_wins_when_the_task_is_also_shortened() -> None:
    later = BASE + timedelta(hours=2)

    (entry,) = diff_tasks([_snap(minutes=45)], [_task(start_at=later, minutes=30)])

    assert entry.kind == "moved"
    assert entry.before is not None
    assert entry.after is not None
    assert entry.before.end_at - entry.before.start_at == timedelta(minutes=45)
    assert entry.after.end_at - entry.after.start_at == timedelta(minutes=30)


def test_all_day_change_is_moved() -> None:
    before = _snap(all_day=True)
    after = _task(all_day=False)

    (entry,) = diff_tasks([before], [after])

    assert entry.kind == "moved"


# -------------------------------------------------------------------------- ordering


def test_entries_are_sorted_by_week_then_key_then_occurrence() -> None:
    after = [
        _task("stretch", week_index=1, occurrence=1),
        _task("easy_run", week_index=1, occurrence=0),
        _task("stretch", week_index=1, occurrence=0),
        _task("long_run", week_index=0, occurrence=0),
    ]

    entries = diff_tasks([], after)

    assert [(e.week_index, e.template_key, e.occurrence) for e in entries] == [
        (0, "long_run", 0),
        (1, "easy_run", 0),
        (1, "stretch", 0),
        (1, "stretch", 1),
    ]


# ----------------------------------------------------------------------- edge inputs


def test_empty_before_makes_everything_added() -> None:
    after = [_task("easy_run"), _task("long_run"), _task("stretch")]

    entries = diff_tasks([], after)

    assert _kinds(entries) == ["added", "added", "added"]


def test_empty_after_makes_everything_removed() -> None:
    before = [_snap("easy_run"), _snap("long_run"), _snap("stretch")]

    entries = diff_tasks(before, [])

    assert _kinds(entries) == ["removed", "removed", "removed"]


def test_scheduled_tasks_are_accepted_on_both_sides() -> None:
    later = BASE + timedelta(hours=1)

    entries = diff_tasks([_task()], [_task(start_at=later)])

    assert _kinds(entries) == ["moved"]


def test_snapshots_with_key_are_accepted_on_both_sides() -> None:
    entries = diff_tasks([_snap(minutes=30)], [_snap(minutes=60)])

    assert _kinds(entries) == ["lengthened"]


def test_mixed_kinds_are_reported_together() -> None:
    before = [_snap("easy_run"), _snap("long_run", week_index=1)]
    after = [_task("easy_run"), _task("stretch", week_index=1)]

    entries = diff_tasks(before, after)

    assert [(e.template_key, e.kind) for e in entries] == [
        ("easy_run", "unchanged"),
        ("long_run", "removed"),
        ("stretch", "added"),
    ]
