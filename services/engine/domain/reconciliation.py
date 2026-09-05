"""Station 3: what was actually done, held against what the Hypothesis predicted.

Three properties define this station, and all three are structural rather than editorial.

**The output is a question, not a score.** Nothing here grades anyone. The comparison is
arithmetic and the narration explains it; the decision — does this Role Model still hold? —
is the user's, and no field on this module can make it for them.

**Unclassified time is where it earns its keep.** In Station 1 it was merely flagged. Here
it has a baseline: time that fits no named dimension, in a quarter with a stated direction,
is the sharpest available signal about the gap between the described life and the executed
one.

**A changed plan is classified, not punished.** That is what Q-2 was for. Scope that
changed because something was learned is growth; scope that shrank at the first resistance
is avoidance. Naming which one happened is the whole point — and both are computed from the
numbers before anything is narrated.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from services.engine.domain.diff import TaskDiffEntry
from services.engine.domain.dimensions import Dimension

__all__ = [
    "Comparison",
    "DimensionShift",
    "Execution",
    "Outcome",
    "ReconciliationNote",
    "ReconciliationNoteOutput",
    "RevisionKind",
    "classify_revision",
    "compare",
]

Outcome = Literal["holds", "revise", "replace"]
RevisionKind = Literal["growth", "avoidance"]

#: Below this share of planned work, a shrinking plan reads as retreat rather than redesign.
_AVOIDANCE_COMPLETION = 0.5


class Execution(BaseModel):
    """What the Plan asked for and what happened. Counted, never estimated."""

    model_config = ConfigDict(extra="forbid")

    planned: int = 0
    done: int = 0
    missed: int = 0
    skipped: int = 0
    completion: float = 0.0


class DimensionShift(BaseModel):
    """How one dimension's share of the time moved across the quarter."""

    model_config = ConfigDict(extra="forbid")

    dimension: Dimension
    before: float = 0.0
    after: float = 0.0
    delta: float = 0.0


class Comparison(BaseModel):
    """The whole computed picture, handed to the model only to be put into words."""

    model_config = ConfigDict(extra="forbid")

    execution: Execution
    shifts: list[DimensionShift] = Field(default_factory=list)
    schedule_changes: list[TaskDiffEntry] = Field(default_factory=list)
    unclassified_delta: float = 0.0


class ReconciliationNote(BaseModel):
    """The model's only job here: say what the numbers mean, and ask the question."""

    model_config = ConfigDict(extra="forbid")

    summary: str = Field(min_length=1, max_length=600)
    observations: list[str] = Field(min_length=1, max_length=5)
    question: str = Field(min_length=1, max_length=300)


class ReconciliationNoteOutput(BaseModel):
    """LLM `output_schema` wrapper for the `narrate_reconciliation` prompt."""

    note: ReconciliationNote


def compare(
    *,
    status_counts: dict[str, int],
    before_shares: dict[str, float],
    after_shares: dict[str, float],
    schedule_changes: Sequence[TaskDiffEntry],
    dimensions: Sequence[Dimension],
) -> Comparison:
    """Build the comparison from counted facts alone. No model call, no judgement."""
    done = status_counts.get("done", 0)
    missed = status_counts.get("missed", 0)
    skipped = status_counts.get("skipped", 0)
    planned = sum(status_counts.values())
    shifts = [
        DimensionShift(
            dimension=dimension,
            before=round(before_shares.get(dimension, 0.0), 4),
            after=round(after_shares.get(dimension, 0.0), 4),
            delta=round(after_shares.get(dimension, 0.0) - before_shares.get(dimension, 0.0), 4),
        )
        for dimension in dimensions
    ]
    unclassified = next((shift.delta for shift in shifts if shift.dimension == "unclassified"), 0.0)
    return Comparison(
        execution=Execution(
            planned=planned,
            done=done,
            missed=missed,
            skipped=skipped,
            completion=round(done / planned, 4) if planned else 0.0,
        ),
        shifts=shifts,
        schedule_changes=list(schedule_changes),
        unclassified_delta=unclassified,
    )


def classify_revision(comparison: Comparison) -> RevisionKind | None:
    """Name what a mid-quarter plan change was, or `None` if the plan never changed.

    The test is not whether the plan shrank — plans should shrink when something is learned
    — but whether it shrank *while the work was not being done*. Scope cut alongside a
    healthy completion rate is a redesign; scope cut with most of it left undone is a
    retreat, and that is the pattern Q-2 asked the user to recognise in advance.
    """
    removed = sum(1 for entry in comparison.schedule_changes if entry.kind == "removed")
    added = sum(1 for entry in comparison.schedule_changes if entry.kind == "added")
    changed = sum(1 for entry in comparison.schedule_changes if entry.kind != "unchanged")
    if changed == 0:
        return None
    shrank = removed > added
    if shrank and comparison.execution.completion < _AVOIDANCE_COMPLETION:
        return "avoidance"
    return "growth"
