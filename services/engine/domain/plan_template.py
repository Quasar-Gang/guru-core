"""The Plan template: a Milestone tree and the flat Tasks hanging off it.

This is the only thing the model produces for Station 2, and it is entirely *relative* —
day hints, slot hints, durations and week ranges. Turning that into dates is arithmetic,
and arithmetic belongs in `scheduler.py`.

The two shape rules are enforced here, not merely documented:

* **Milestones nest.** A Milestone may contain Milestones; decomposition has to go
  somewhere, and this is where it goes.
* **Tasks do not.** A Task never contains a Task, and every Task names exactly one
  Milestone. Anything needing further breakdown is a sub-Milestone.

The payoff is that "done" always means the same thing. The moment Tasks nest, completion
becomes a weighted-average argument and every progress number becomes a negotiation.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

__all__ = [
    "MAX_DEPTH",
    "Area",
    "DayHint",
    "FlatMilestone",
    "MilestoneNode",
    "PlanTemplate",
    "PlanTemplateOutput",
    "SlotHint",
    "TaskSpec",
    "TaskType",
    "flatten",
]

DayHint = Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun", "any", "weekend", "weekday"]
SlotHint = Literal["morning", "noon", "evening", "any"]
TaskType = Literal["session", "habit", "checkpoint", "rest"]

#: The three things Q-3 forces a ranking over. Every Task belongs to exactly one, which is
#: what lets the Quota's cut order mean something concrete.
Area = Literal["career", "relationships", "health"]

#: Deep enough for a quarter's decomposition, shallow enough to stay readable on a screen.
MAX_DEPTH = 3


class MilestoneNode(BaseModel):
    """A checkpoint, and possibly a subtree of smaller ones."""

    model_config = ConfigDict(extra="forbid")

    key: str = Field(pattern=r"^[a-z0-9_]{1,48}$")
    title: str = Field(min_length=1, max_length=200)
    metric: str = Field(min_length=1, max_length=300)
    target_week: int = Field(ge=0)
    children: list[MilestoneNode] = Field(default_factory=list)


class TaskSpec(BaseModel):
    """One repeating unit of work under a Milestone, still without a date."""

    model_config = ConfigDict(extra="forbid")

    key: str = Field(pattern=r"^[a-z0-9_]{1,48}$")
    milestone_key: str = Field(pattern=r"^[a-z0-9_]{1,48}$")
    title: str = Field(min_length=1, max_length=200)
    description: str = ""
    task_type: TaskType
    area: Area
    day_hint: DayHint
    slot_hint: SlotHint
    duration_minutes: int = Field(ge=5, le=300)
    times_per_week: int = Field(default=1, ge=1, le=7)
    week_start: int = Field(ge=0)
    week_end: int = Field(ge=0)


class PlanTemplate(BaseModel):
    """What the Plan Engine's single model call returns."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=80)
    duration_weeks: int = Field(ge=1, le=104)
    assumptions: list[str] = Field(default_factory=list)
    success_criteria: list[str] = Field(min_length=1, max_length=6)
    milestones: list[MilestoneNode] = Field(min_length=1, max_length=8)
    tasks: list[TaskSpec] = Field(min_length=1, max_length=16)

    @model_validator(mode="after")
    def shape_rules(self) -> PlanTemplate:
        flat = flatten(self.milestones)
        keys = [item.key for item in flat]
        duplicates = sorted({key for key in keys if keys.count(key) > 1})
        if duplicates:
            raise ValueError(f"milestone keys must be unique, repeated: {', '.join(duplicates)}")

        for item in flat:
            if item.depth >= MAX_DEPTH:
                raise ValueError(
                    f"milestone {item.key!r} nests {item.depth + 1} deep, "
                    f"and the tree may go at most {MAX_DEPTH} deep"
                )
            if item.target_week >= self.duration_weeks:
                raise ValueError(
                    f"milestone {item.key!r} targets week {item.target_week}, "
                    f"beyond the plan's {self.duration_weeks} weeks"
                )

        known = set(keys)
        for task in self.tasks:
            if task.milestone_key not in known:
                raise ValueError(
                    f"task {task.key!r} hangs off unknown milestone {task.milestone_key!r}"
                )
            if task.week_start > task.week_end:
                raise ValueError(
                    f"task {task.key!r} has week_start {task.week_start} "
                    f"after week_end {task.week_end}"
                )
            if task.week_end >= self.duration_weeks:
                raise ValueError(
                    f"task {task.key!r} runs to week {task.week_end}, "
                    f"beyond the plan's {self.duration_weeks} weeks"
                )

        task_keys = [task.key for task in self.tasks]
        if len(task_keys) != len(set(task_keys)):
            raise ValueError("task keys must be unique")
        return self


class PlanTemplateOutput(BaseModel):
    """LLM `output_schema` wrapper for the `build_plan` prompt."""

    plan: PlanTemplate


class FlatMilestone(BaseModel):
    """A tree node with its place in the tree made explicit, ready for the repository."""

    model_config = ConfigDict(extra="forbid")

    key: str
    parent_key: str | None
    title: str
    metric: str
    target_week: int
    depth: int
    position: int


def flatten(nodes: list[MilestoneNode]) -> list[FlatMilestone]:
    """Depth-first walk of the tree; `position` counts siblings, `depth` counts levels."""
    return list(_walk(nodes, parent_key=None, depth=0))


def _walk(
    nodes: list[MilestoneNode], *, parent_key: str | None, depth: int
) -> Iterator[FlatMilestone]:
    for position, node in enumerate(nodes):
        yield FlatMilestone(
            key=node.key,
            parent_key=parent_key,
            title=node.title,
            metric=node.metric,
            target_week=node.target_week,
            depth=depth,
            position=position,
        )
        yield from _walk(node.children, parent_key=node.key, depth=depth + 1)
