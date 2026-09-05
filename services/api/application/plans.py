"""Station 2 over HTTP: the Plan, its Milestone tree, its Tasks and their Schedule.

Reading a Plan returns the tree as a tree. Reading its Tasks returns them flat, with the
slot each was placed in. That asymmetry is the domain's, not the API's: Milestones nest so
decomposition has somewhere to go, and Tasks do not so that "done" always means the same
thing.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from packages.queue import QueuePort
from packages.repo import PlanExportRepo, PlanRepo, PlanTreeRepo
from packages.repo.entities import Milestone, Plan, ScheduledTaskRow
from services.api.application.exports import enqueue_incremental_export
from services.api.application.ports import ClockPort
from services.api.domain.errors import Conflict, NotFound

__all__ = [
    "GetPlan",
    "ListPlanTasks",
    "ListPlans",
    "MilestoneView",
    "PlanDetail",
    "PlanSummary",
    "SetPlanStatus",
    "TaskView",
    "UpdateTaskStatus",
]

TaskStatus = Literal["pending", "done", "missed", "skipped"]

#: A plan may be started, or put away. It is never edited into something else — that is what
#: a new Hypothesis is for.
_ALLOWED_STATUS_MOVES: dict[str, frozenset[str]] = {
    "draft": frozenset({"active", "archived"}),
    "active": frozenset({"archived"}),
    "archived": frozenset(),
    "generating": frozenset(),
    "failed": frozenset(),
}


class MilestoneView(BaseModel):
    """One node of the tree; `children` is the tree, `key` is its stable identity."""

    id: UUID
    key: str
    title: str
    metric: str
    target_date: date | None
    status: str
    children: list[MilestoneView] = Field(default_factory=list)


class TaskView(BaseModel):
    """One task, flat, with where it landed."""

    id: UUID
    milestone_id: UUID
    key: str
    week_index: int
    occurrence: int
    area: str
    task_type: str
    title: str
    description: str
    duration_minutes: int
    status: str
    completed_at: datetime | None
    start_at: datetime
    end_at: datetime
    all_day: bool


class PlanSummary(BaseModel):
    id: UUID
    hypothesis_id: UUID
    title: str
    status: str
    start_date: date | None
    duration_weeks: int
    error: str | None
    task_counts: dict[str, int] = Field(default_factory=dict)


class PlanDetail(PlanSummary):
    """The summary plus the tree and everything the plan had to assume."""

    structure: dict[str, Any] = Field(default_factory=dict)
    milestones: list[MilestoneView] = Field(default_factory=list)


class ListPlans:
    def __init__(self, plans: PlanRepo, tree: PlanTreeRepo) -> None:
        self._plans = plans
        self._tree = tree

    async def __call__(self, user_id: UUID, status: str | None = None) -> list[PlanSummary]:
        rows = await self._plans.list_for_user(user_id, status)
        return [_summary(row, await self._tree.counts_by_status(row.id)) for row in rows]


class GetPlan:
    """The single place a plan is loaded and ownership is checked."""

    def __init__(self, plans: PlanRepo, tree: PlanTreeRepo) -> None:
        self._plans = plans
        self._tree = tree

    async def load(self, user_id: UUID, plan_id: UUID) -> Plan:
        found = await self._plans.get(user_id, plan_id)
        if found is None:
            raise NotFound(f"plan not found: {plan_id}")
        return found

    async def __call__(self, user_id: UUID, plan_id: UUID) -> PlanDetail:
        plan = await self.load(user_id, plan_id)
        counts = await self._tree.counts_by_status(plan_id)
        milestones = await self._tree.list_milestones(plan_id)
        return PlanDetail(
            **_summary(plan, counts).model_dump(),
            structure=plan.structure,
            milestones=_tree(milestones),
        )


class ListPlanTasks:
    """The flat list, optionally windowed — this is what a day or a week view reads."""

    def __init__(self, get_plan: GetPlan, tree: PlanTreeRepo) -> None:
        self._get_plan = get_plan
        self._tree = tree

    async def __call__(
        self,
        user_id: UUID,
        plan_id: UUID,
        start_from: datetime | None = None,
        start_to: datetime | None = None,
    ) -> list[TaskView]:
        await self._get_plan.load(user_id, plan_id)
        rows = await self._tree.list_scheduled(plan_id, start_from, start_to)
        return [_task_view(row) for row in rows]


class SetPlanStatus:
    """Start a plan, or put it away. Nothing else moves a plan between states."""

    def __init__(self, plans: PlanRepo, get_plan: GetPlan, clock: ClockPort) -> None:
        self._plans = plans
        self._get_plan = get_plan
        self._clock = clock

    async def __call__(self, user_id: UUID, plan_id: UUID, status: str) -> PlanSummary:
        plan = await self._get_plan.load(user_id, plan_id)
        if status not in _ALLOWED_STATUS_MOVES[plan.status]:
            raise Conflict(f"a {plan.status} plan cannot become {status}")
        now = self._clock.now()
        stamp = {"activated_at": now} if status == "active" else {"archived_at": now}
        updated = await self._plans.update_fields(plan_id, status=status, **stamp)
        return _summary(updated, {})


class UpdateTaskStatus:
    """Tick one task off. Completion lives here; the calendar is only a projection of it."""

    def __init__(
        self,
        get_plan: GetPlan,
        tree: PlanTreeRepo,
        exports: PlanExportRepo,
        queue: QueuePort,
        clock: ClockPort,
    ) -> None:
        self._get_plan = get_plan
        self._tree = tree
        self._exports = exports
        self._queue = queue
        self._clock = clock

    async def __call__(
        self, user_id: UUID, plan_id: UUID, task_id: UUID, status: TaskStatus
    ) -> TaskView:
        await self._get_plan.load(user_id, plan_id)
        if await self._tree.get_task(plan_id, task_id) is None:
            raise NotFound(f"task not found: {task_id}")
        completed_at = self._clock.now() if status == "done" else None
        await self._tree.set_task_status(task_id, status, completed_at)
        # The slot is now out of date wherever it was pushed; mark it for the next sync.
        await self._tree.mark_dirty(task_id)
        await enqueue_incremental_export(self._exports, self._queue, plan_id)
        row = await self._tree.find_task(task_id)
        if row is None:
            raise NotFound(f"task not found: {task_id}")
        return _task_view(row)


# ------------------------------------------------------------------------ view models


def _summary(plan: Plan, counts: dict[str, int]) -> PlanSummary:
    return PlanSummary(
        id=plan.id,
        hypothesis_id=plan.hypothesis_id,
        title=plan.title,
        status=plan.status,
        start_date=plan.start_date,
        duration_weeks=plan.duration_weeks,
        error=plan.error,
        task_counts=counts,
    )


def _task_view(row: ScheduledTaskRow) -> TaskView:
    return TaskView(
        id=row.task.id,
        milestone_id=row.task.milestone_id,
        key=row.task.key,
        week_index=row.task.week_index,
        occurrence=row.task.occurrence,
        area=row.task.area,
        task_type=row.task.task_type,
        title=row.task.title,
        description=row.task.description,
        duration_minutes=row.task.duration_minutes,
        status=row.task.status,
        completed_at=row.task.completed_at,
        start_at=row.slot.start_at,
        end_at=row.slot.end_at,
        all_day=row.slot.all_day,
    )


def _tree(rows: list[Milestone]) -> list[MilestoneView]:
    """Rebuild the tree from flat rows. They arrive shallowest first, so one pass is enough."""
    views = {row.id: _milestone_view(row) for row in rows}
    roots: list[MilestoneView] = []
    for row in rows:
        view = views[row.id]
        parent = views.get(row.parent_id) if row.parent_id is not None else None
        if parent is None:
            roots.append(view)
        else:
            parent.children.append(view)
    return roots


def _milestone_view(row: Milestone) -> MilestoneView:
    return MilestoneView(
        id=row.id,
        key=row.key,
        title=row.title,
        metric=row.metric,
        target_date=row.target_date,
        status=row.status,
    )
