"""Render one plan as Markdown, store it, and hand back a download link (PRD 4.3.5).

Synchronous by design: the document is cheap to build and the client wants the text back
in the same response, so this never goes through the queue.
"""

from uuid import UUID

from pydantic import BaseModel

from packages.repo import PlanTaskRepo, ProfileRepo
from packages.repo.entities import PlanTask
from packages.storage import StoragePort
from services.api.application.get_plan import GetPlan, PlanDetail
from services.api.application.list_plan_tasks import resolve_timezone
from services.api.application.ports import ClockPort
from services.api.domain.markdown_export import (
    MarkdownOptions,
    PlanExportData,
    PlanTaskExportData,
    render_markdown,
)

__all__ = ["ExportMarkdown", "MarkdownExportResult"]

CONTENT_TYPE = "text/markdown; charset=utf-8"

#: Long enough for the user to hit save, short enough that a leaked link goes stale.
DOWNLOAD_TTL_SECONDS = 15 * 60


class MarkdownExportResult(BaseModel):
    """The rendered document, both inline and as a stored object."""

    content: str
    download_url: str
    storage_key: str


class ExportMarkdown:
    """Reads the plan through `GetPlan`, so ownership and structure parsing live in one place."""

    def __init__(
        self,
        get_plan: GetPlan,
        plan_tasks: PlanTaskRepo,
        profiles: ProfileRepo,
        storage: StoragePort,
        clock: ClockPort,
    ) -> None:
        self._get_plan = get_plan
        self._plan_tasks = plan_tasks
        self._profiles = profiles
        self._storage = storage
        self._clock = clock

    async def __call__(
        self, user_id: UUID, plan_id: UUID, options: MarkdownOptions
    ) -> MarkdownExportResult:
        plan = await self._get_plan.load(user_id, plan_id)
        detail = await self._get_plan.detail(plan)
        tasks = await self._plan_tasks.list(plan_id, None, None)

        profile = await self._profiles.get(plan.user_id)
        timezone = str(resolve_timezone(profile.timezone if profile is not None else None))
        content = render_markdown(
            _plan_data(detail), [_task_data(task) for task in tasks], options, timezone
        )

        key = self._key(user_id, plan_id)
        await self._storage.put(key, content.encode("utf-8"), CONTENT_TYPE)
        url = await self._storage.presign_get(key, DOWNLOAD_TTL_SECONDS)
        return MarkdownExportResult(content=content, download_url=url, storage_key=key)

    def _key(self, user_id: UUID, plan_id: UUID) -> str:
        stamp = self._clock.now().strftime("%Y%m%dT%H%M%SZ")
        return f"exports/{user_id}/{plan_id}/{stamp}.md"


def _plan_data(detail: PlanDetail) -> PlanExportData:
    return PlanExportData(
        title=detail.title,
        goal_statement=detail.goal_statement,
        difficulty=detail.difficulty,
        duration_weeks=detail.duration_weeks,
        start_date=detail.start_date,
        deadline=detail.deadline,
        success_criteria=detail.success_criteria,
        assumptions=detail.assumptions,
        phases=detail.phases,
    )


def _task_data(task: PlanTask) -> PlanTaskExportData:
    return PlanTaskExportData(
        week_index=task.week_index,
        title=task.title,
        description=task.description,
        start_at=task.start_at,
        end_at=task.end_at,
        all_day=task.all_day,
        status=task.status,
        sort_order=task.sort_order,
    )
