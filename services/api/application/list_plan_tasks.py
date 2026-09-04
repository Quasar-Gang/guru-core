"""The built-in calendar / todo view: list a plan's tasks over a local date range (PRD 4.3.6)."""

from datetime import UTC, date, datetime, time, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel

from packages.repo import PlanRepo, PlanTaskRepo, ProfileRepo
from packages.repo.entities import PlanTask
from services.api.domain.errors import NotFound

__all__ = ["ListPlanTasks", "PlanTaskList", "PlanTaskView", "task_view"]

DEFAULT_TIMEZONE = "UTC"


class PlanTaskView(BaseModel):
    """One plan task as the client sees it."""

    id: UUID
    template_key: str
    week_index: int
    phase_index: int
    occurrence: int
    task_type: str
    title: str
    description: str
    start_at: datetime
    end_at: datetime
    all_day: bool
    status: str
    completed_at: datetime | None
    missed_reason: str | None
    synced: bool


class PlanTaskList(BaseModel):
    items: list[PlanTaskView]
    total: int


def task_view(task: PlanTask) -> PlanTaskView:
    """Project a stored task, deriving `synced` from the export bookkeeping columns."""
    return PlanTaskView(
        id=task.id,
        template_key=task.template_key,
        week_index=task.week_index,
        phase_index=task.phase_index,
        occurrence=task.occurrence,
        task_type=task.task_type,
        title=task.title,
        description=task.description,
        start_at=task.start_at,
        end_at=task.end_at,
        all_day=task.all_day,
        status=task.status,
        completed_at=task.completed_at,
        missed_reason=task.missed_reason,
        synced=_is_synced(task),
    )


def _is_synced(task: PlanTask) -> bool:
    """Exported and untouched since: plan_tasks has no updated_at, so completed_at stands in."""
    if task.external_ref is None or task.synced_at is None:
        return False
    return task.completed_at is None or task.completed_at <= task.synced_at


def resolve_timezone(name: str | None) -> ZoneInfo:
    """A profile's IANA timezone; anything unusable degrades to UTC rather than failing a read."""
    if not name:
        return ZoneInfo(DEFAULT_TIMEZONE)
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo(DEFAULT_TIMEZONE)


def _day_start(day: date, tz: ZoneInfo) -> datetime:
    return datetime.combine(day, time.min, tzinfo=tz).astimezone(UTC)


class ListPlanTasks:
    """`from` / `to` are local calendar dates in the plan owner's timezone, both inclusive."""

    def __init__(self, plans: PlanRepo, plan_tasks: PlanTaskRepo, profiles: ProfileRepo) -> None:
        self._plans = plans
        self._plan_tasks = plan_tasks
        self._profiles = profiles

    async def __call__(
        self, user_id: UUID, plan_id: UUID, from_: date | None, to: date | None
    ) -> PlanTaskList:
        plan = await self._plans.get(user_id, plan_id)
        if plan is None:
            raise NotFound(f"plan not found: {plan_id}")

        profile = await self._profiles.get(plan.user_id)
        tz = resolve_timezone(profile.timezone if profile is not None else None)
        start_from = _day_start(from_, tz) if from_ is not None else None
        start_to = _day_start(to + timedelta(days=1), tz) if to is not None else None

        tasks = await self._plan_tasks.list(plan_id, start_from, start_to)
        items = [task_view(task) for task in tasks]
        return PlanTaskList(items=items, total=len(items))
