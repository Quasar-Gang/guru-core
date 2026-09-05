"""Compare two Schedules, occurrence by occurrence. Pure and deterministic.

Tasks are aligned on the stable key `(key, week_index, occurrence)` produced by the
scheduler, so a Task that only moved reports as `moved` rather than as a removal plus an
addition. Station 3 renders these entries as they are; the model never describes them.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict

__all__ = [
    "DiffKind",
    "TaskDiffEntry",
    "TaskSnapshot",
    "TaskSnapshotWithKey",
    "diff_tasks",
]

DiffKind = Literal["added", "moved", "removed", "shortened", "lengthened", "unchanged"]


class _TaskLike(Protocol):
    """What a diff needs from a task: the alignment key plus its time window.

    Satisfied by both `ScheduledTask` (a freshly computed schedule) and
    `TaskSnapshotWithKey` (rows read back from the database).
    """

    @property
    def key(self) -> str: ...

    @property
    def week_index(self) -> int: ...

    @property
    def occurrence(self) -> int: ...

    @property
    def title(self) -> str: ...

    @property
    def start_at(self) -> datetime: ...

    @property
    def end_at(self) -> datetime: ...

    @property
    def all_day(self) -> bool: ...


class TaskSnapshot(BaseModel):
    """One side of a diff entry: how a task looked before or after."""

    model_config = ConfigDict(extra="forbid")

    title: str
    start_at: datetime
    end_at: datetime
    all_day: bool


class TaskSnapshotWithKey(BaseModel):
    """A stored task joined to its slot, carrying the key it is aligned on."""

    model_config = ConfigDict(extra="forbid")

    key: str
    week_index: int
    occurrence: int
    title: str
    start_at: datetime
    end_at: datetime
    all_day: bool


class TaskDiffEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    week_index: int
    occurrence: int
    kind: DiffKind
    title: str
    before: TaskSnapshot | None
    after: TaskSnapshot | None


_Key = tuple[str, int, int]


def diff_tasks(before: Sequence[_TaskLike], after: Sequence[_TaskLike]) -> list[TaskDiffEntry]:
    """One entry per `(key, week_index, occurrence)`, sorted by week, key, occurrence."""
    old = {_align(task): task for task in before}
    new = {_align(task): task for task in after}
    return [
        _entry(key, old.get(key), new.get(key)) for key in sorted(old.keys() | new.keys(), key=_ord)
    ]


def _align(task: _TaskLike) -> _Key:
    return task.key, task.week_index, task.occurrence


def _ord(key: _Key) -> tuple[int, str, int]:
    task_key, week_index, occurrence = key
    return week_index, task_key, occurrence


def _entry(key: _Key, old: _TaskLike | None, new: _TaskLike | None) -> TaskDiffEntry:
    task_key, week_index, occurrence = key
    title = new.title if new is not None else (old.title if old is not None else "")
    return TaskDiffEntry(
        key=task_key,
        week_index=week_index,
        occurrence=occurrence,
        kind=_kind(old, new),
        title=title,
        before=_snapshot(old),
        after=_snapshot(new),
    )


def _kind(old: _TaskLike | None, new: _TaskLike | None) -> DiffKind:
    """Classify one aligned pair; a move outranks a duration change."""
    if old is None:
        return "added"
    if new is None:
        return "removed"
    # An all-day flip changes when the task sits in the day just as a start shift does.
    if old.start_at != new.start_at or old.all_day != new.all_day:
        return "moved"
    old_duration = old.end_at - old.start_at
    new_duration = new.end_at - new.start_at
    if new_duration < old_duration:
        return "shortened"
    if new_duration > old_duration:
        return "lengthened"
    return "unchanged"


def _snapshot(task: _TaskLike | None) -> TaskSnapshot | None:
    if task is None:
        return None
    return TaskSnapshot(
        title=task.title, start_at=task.start_at, end_at=task.end_at, all_day=task.all_day
    )
