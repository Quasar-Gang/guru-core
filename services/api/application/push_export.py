"""The `export.push` worker handler: write a plan into Google Calendar (PRD 3.5 / 4.3.4).

`full` builds the plan's own secondary calendar from scratch; `incremental` replays only
the tasks that changed since the last push. A handler never raises: whatever goes wrong
ends up on the `plan_exports` row, which is what the client polls.
"""

from datetime import datetime

from packages.queue import ExportJobV1
from packages.repo import PlanExportRepo, PlanRepo, PlanTaskRepo
from packages.repo.entities import PlanTask
from services.api.application.google_access_token import GoogleAccessTokenProvider
from services.api.application.ports import CalendarEventWrite, CalendarPort, ClockPort
from services.api.domain.calendar_mapping import ColorMap, should_export, to_calendar_event
from services.api.domain.errors import DomainError, NotFound, ReauthRequired

__all__ = ["CALENDAR_TITLE_PREFIX", "PushExport"]

#: Every plan gets its own secondary calendar, so hiding or deleting it is one click.
CALENDAR_TITLE_PREFIX = "guru · "

STATUS_SYNCED = "synced"
STATUS_FAILED = "failed"
ERROR_REAUTH_REQUIRED = "reauth_required"

#: MVP: rest days are never pushed. The switch is here for when the export options grow.
INCLUDE_REST = False


class PushExport:
    """One plan, one target, one pass; partial progress is kept in `plan_tasks`."""

    def __init__(
        self,
        plans: PlanRepo,
        plan_tasks: PlanTaskRepo,
        exports: PlanExportRepo,
        calendar: CalendarPort,
        tokens: GoogleAccessTokenProvider,
        color_map: ColorMap,
        clock: ClockPort,
    ) -> None:
        self._plans = plans
        self._plan_tasks = plan_tasks
        self._exports = exports
        self._calendar = calendar
        self._tokens = tokens
        self._color_map = color_map
        self._clock = clock

    async def __call__(self, job: ExportJobV1) -> None:
        try:
            await self._run(job)
        except ReauthRequired:
            await self._fail(job, ERROR_REAUTH_REQUIRED)
        except Exception as exc:  # a worker handler reports failure, it never propagates it
            await self._fail(job, str(exc) or type(exc).__name__)

    async def _run(self, job: ExportJobV1) -> None:
        plan = await self._plans.get_unscoped(job.plan_id)
        if plan is None:
            raise NotFound(f"plan not found: {job.plan_id}")
        access_token = await self._tokens.get(plan.user_id)

        full = job.mode == "full"
        if full:
            calendar_id = await self._calendar.create_calendar(
                access_token, f"{CALENDAR_TITLE_PREFIX}{plan.title}"
            )
            tasks = await self._plan_tasks.list(job.plan_id, None, None)
        else:
            record = await self._exports.get(job.plan_id, job.target)
            if record is None or record.external_calendar_id is None:
                raise DomainError("incremental export needs a calendar; run a full export first")
            calendar_id = record.external_calendar_id
            tasks = await self._plan_tasks.list_dirty(job.plan_id)

        now = self._clock.now()
        for task in tasks:
            await self._sync(access_token, calendar_id, plan.title, task, now, replace=full)
        await self._exports.upsert(job.plan_id, job.target, STATUS_SYNCED, calendar_id, now, None)

    async def _sync(
        self,
        access_token: str,
        calendar_id: str,
        plan_title: str,
        task: PlanTask,
        now: datetime,
        replace: bool,
    ) -> None:
        """`replace` means the old calendar is gone, so any stored event id is stale."""
        external_ref = None if replace else task.external_ref

        if not should_export(task, INCLUDE_REST):
            # A task that left the export (a rest day, or one a revision reshaped) takes its
            # event with it; marking it synced keeps it out of the next dirty list.
            if external_ref is not None:
                await self._calendar.delete_event(access_token, calendar_id, external_ref)
            await self._touch(task, external_ref=None, now=now)
            return

        event = CalendarEventWrite(
            **to_calendar_event(task, plan_title, self._color_map).model_dump()
        )
        if external_ref is None:
            external_ref = await self._calendar.create_event(access_token, calendar_id, event)
        else:
            await self._calendar.update_event(access_token, calendar_id, external_ref, event)
        await self._touch(task, external_ref=external_ref, now=now)

    async def _touch(self, task: PlanTask, external_ref: str | None, now: datetime) -> None:
        await self._plan_tasks.update_fields(task.id, external_ref=external_ref, synced_at=now)

    async def _fail(self, job: ExportJobV1, error: str) -> None:
        record = await self._exports.get(job.plan_id, job.target)
        await self._exports.upsert(
            job.plan_id,
            job.target,
            STATUS_FAILED,
            record.external_calendar_id if record is not None else None,
            record.last_synced_at if record is not None else None,
            error,
        )
