"""Diff a plan's existing tasks against a revision's proposal (PRD 3.8 / 4.3.6).

Pure and deterministic. Tasks are aligned on the stable key
``(template_key, week_index, occurrence)`` produced by the scheduler, so a revision that
only shifts a task's time reports it as ``moved`` instead of a removal plus an addition.
The resulting entries are stored in ``plan_revisions.diff`` and rendered by the app as-is,
never described by the LLM.
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

#: ``reduced`` belongs to the ``reduce`` revision strategy (PRD 3.8.1), which lowers the
#: goal itself rather than moving tasks around. ``diff_tasks`` never emits it: it compares
#: schedules, and the strategy layer marks the goal change.
DiffKind = Literal[
    "added",
    "moved",
    "removed",
    "shortened",
    "lengthened",
    "reduced",
    "unchanged",
]


class _TaskLike(Protocol):
    """What ``diff_tasks`` needs from a task: the alignment key plus its time window.

    Satisfied by both ``ScheduledTask`` (a freshly scheduled proposal) and
    ``TaskSnapshotWithKey`` (a row read back from ``plan_tasks``).
    """

    @property
    def template_key(self) -> str: ...

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
    """One side of a diff entry: how a task looks before or after the revision."""

    model_config = ConfigDict(extra="forbid")

    title: str
    start_at: datetime
    end_at: datetime
    all_day: bool


class TaskSnapshotWithKey(BaseModel):
    """An existing ``plan_tasks`` row, carrying the key it is aligned on."""

    model_config = ConfigDict(extra="forbid")

    template_key: str
    week_index: int
    occurrence: int
    title: str
    start_at: datetime
    end_at: datetime
    all_day: bool


class TaskDiffEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    template_key: str
    week_index: int
    occurrence: int
    kind: DiffKind
    title: str
    before: TaskSnapshot | None
    after: TaskSnapshot | None


_Key = tuple[str, int, int]


def diff_tasks(
    before: Sequence[_TaskLike],
    after: Sequence[_TaskLike],
) -> list[TaskDiffEntry]:
    """Compare two task lists, one entry per ``(template_key, week_index, occurrence)``.

    Both sides accept ``ScheduledTask`` and ``TaskSnapshotWithKey``. Entries come back
    sorted by ``week_index``, then ``template_key``, then ``occurrence``.
    """
    old = {_key(task): task for task in before}
    new = {_key(task): task for task in after}

    entries = [
        _entry(key, old.get(key), new.get(key)) for key in sorted(old.keys() | new.keys(), key=_ord)
    ]
    return entries


def _key(task: _TaskLike) -> _Key:
    return task.template_key, task.week_index, task.occurrence


def _ord(key: _Key) -> tuple[int, str, int]:
    template_key, week_index, occurrence = key
    return week_index, template_key, occurrence


def _entry(key: _Key, old: _TaskLike | None, new: _TaskLike | None) -> TaskDiffEntry:
    template_key, week_index, occurrence = key
    # One of the two sides is always present: the key came from one of the lists.
    title = new.title if new is not None else (old.title if old is not None else "")
    return TaskDiffEntry(
        template_key=template_key,
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
        title=task.title,
        start_at=task.start_at,
        end_at=task.end_at,
        all_day=task.all_day,
    )
