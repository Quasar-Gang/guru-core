"""Read one plan in full: its structure, its progress, and its export state (PRD 3.5 / 5)."""

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, Field

from packages.repo import Plan, PlanExportRepo, PlanRepo, PlanTask, PlanTaskRepo
from services.api.application.get_plan_session import completion_rate
from services.api.domain.errors import NotFound
from services.api.domain.markdown_export import PhaseData

__all__ = [
    "CheckpointStatus",
    "ExportStatusView",
    "GetPlan",
    "PhaseRate",
    "PlanDetail",
    "PlanProgress",
]

_TASK_STATUSES = ("pending", "done", "missed", "skipped")
_CHECKPOINT_TASK_TYPE = "checkpoint"


class PhaseRate(BaseModel):
    """How far one phase of the plan has been worked through."""

    phase_index: int
    name: str
    done: int
    total: int
    rate: float


class CheckpointStatus(BaseModel):
    """One phase milestone, as scheduled into a `checkpoint` task."""

    phase_index: int
    title: str
    metric: str
    due_at: datetime
    status: str


class PlanProgress(BaseModel):
    total: int
    done: int
    missed: int
    skipped: int
    pending: int
    completion_rate: float
    phase_rates: list[PhaseRate] = Field(default_factory=list)
    checkpoints: list[CheckpointStatus] = Field(default_factory=list)


class ExportStatusView(BaseModel):
    """One row of `plan_exports`, plus how many task changes are still unsynced."""

    target: str
    status: str
    external_calendar_id: str | None
    last_synced_at: datetime | None
    error: str | None
    pending_changes: int


class PlanDetail(BaseModel):
    id: UUID
    session_id: UUID
    title: str
    difficulty: str
    status: str
    goal_statement: str
    duration_weeks: int
    start_date: date
    deadline: date
    phases: list[PhaseData] = Field(default_factory=list)
    success_criteria: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    progress: PlanProgress
    exports: list[ExportStatusView] = Field(default_factory=list)


class GetPlan:
    """Assemble a `PlanDetail`; also the single place the other plan use cases render from."""

    def __init__(self, plans: PlanRepo, plan_tasks: PlanTaskRepo, exports: PlanExportRepo) -> None:
        self._plans = plans
        self._plan_tasks = plan_tasks
        self._exports = exports

    async def __call__(self, user_id: UUID, plan_id: UUID) -> PlanDetail:
        return await self.detail(await self.load(user_id, plan_id))

    async def load(self, user_id: UUID, plan_id: UUID) -> Plan:
        """Fetch a plan owned by `user_id`; another user's plan is indistinguishable from none."""
        plan = await self._plans.get(user_id, plan_id)
        if plan is None:
            raise NotFound(f"plan not found: {plan_id}")
        return plan

    async def detail(self, plan: Plan) -> PlanDetail:
        tasks = await self._plan_tasks.list(plan.id, None, None)
        phases = [PhaseData.from_structure(raw) for raw in _phases(plan)]
        return PlanDetail(
            id=plan.id,
            session_id=plan.session_id,
            title=plan.title,
            difficulty=plan.difficulty,
            status=plan.status,
            goal_statement=plan.goal_statement,
            duration_weeks=plan.duration_weeks,
            start_date=plan.start_date,
            deadline=plan.deadline,
            phases=phases,
            success_criteria=_strings(plan, "success_criteria"),
            assumptions=_strings(plan, "assumptions"),
            progress=_progress(phases, tasks),
            exports=await self._export_views(plan.id),
        )

    async def _export_views(self, plan_id: UUID) -> list[ExportStatusView]:
        rows = await self._exports.list_for_plan(plan_id)
        if not rows:
            return []
        pending = len(await self._plan_tasks.list_dirty(plan_id))
        return [
            ExportStatusView(
                target=row.target,
                status=row.status,
                external_calendar_id=row.external_calendar_id,
                last_synced_at=row.last_synced_at,
                error=row.error,
                pending_changes=pending,
            )
            for row in rows
        ]


def _phases(plan: Plan) -> list[dict[str, object]]:
    raw = plan.structure.get("phases", [])
    return [item for item in raw if isinstance(item, dict)]


def _strings(plan: Plan, key: str) -> list[str]:
    raw = plan.structure.get(key, [])
    return [str(item) for item in raw] if isinstance(raw, list) else []


def _progress(phases: list[PhaseData], tasks: list[PlanTask]) -> PlanProgress:
    counts = dict.fromkeys(_TASK_STATUSES, 0)
    for task in tasks:
        if task.status in counts:
            counts[task.status] += 1
    return PlanProgress(
        total=len(tasks),
        done=counts["done"],
        missed=counts["missed"],
        skipped=counts["skipped"],
        pending=counts["pending"],
        completion_rate=completion_rate(counts),
        phase_rates=[_phase_rate(phase, tasks) for phase in phases],
        checkpoints=_checkpoints(phases, tasks),
    )


def _phase_rate(phase: PhaseData, tasks: list[PlanTask]) -> PhaseRate:
    """`done / total` over the phase's own tasks; a phase with no task scores 0.0."""
    of_phase = [t for t in tasks if t.phase_index == phase.index]
    done = sum(1 for t in of_phase if t.status == "done")
    return PhaseRate(
        phase_index=phase.index,
        name=phase.name,
        done=done,
        total=len(of_phase),
        rate=done / len(of_phase) if of_phase else 0.0,
    )


def _checkpoints(phases: list[PhaseData], tasks: list[PlanTask]) -> list[CheckpointStatus]:
    """Derived from the scheduled `checkpoint` tasks, which carry the milestone verbatim.

    `due_at` is the task's start: a checkpoint is an all-day task on the last day of its phase.
    """
    metrics = {phase.index: phase.milestone_metric for phase in phases}
    found = [t for t in tasks if t.task_type == _CHECKPOINT_TASK_TYPE]
    found.sort(key=lambda t: (t.phase_index, t.start_at))
    return [
        CheckpointStatus(
            phase_index=task.phase_index,
            title=task.title,
            metric=task.description or metrics.get(task.phase_index, ""),
            due_at=task.start_at,
            status=task.status,
        )
        for task in found
    ]
