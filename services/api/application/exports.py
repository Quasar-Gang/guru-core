"""Pushing the Schedule onto the calendar the user already reads.

A plan nobody sees is a plan nobody runs, so the Schedule goes where the rest of their week
already lives. Each plan gets its own secondary calendar, which makes hiding or deleting the
whole thing one click rather than an archaeology exercise.

The database stays authoritative: `schedule_slots.external_ref` records where a slot landed,
`synced_at` records when, and a task that changed since is simply dirty. Losing the calendar
loses nothing.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from packages.queue import ExportJobV1, QueuePort
from packages.repo import PlanExportRepo, PlanRepo, PlanTreeRepo
from packages.repo.entities import ScheduledTaskRow
from services.api.application.google_access_token import GoogleAccessTokenProvider
from services.api.application.ports import CalendarEventWrite, CalendarPort, ClockPort
from services.api.domain.calendar_mapping import ColorMap, should_export, to_calendar_event
from services.api.domain.errors import Conflict, DomainError, InvalidInput, NotFound, ReauthRequired

__all__ = [
    "CALENDAR_TITLE_PREFIX",
    "ExportStatusView",
    "GetExportStatus",
    "PushExport",
    "RequestExport",
    "UnexportPlan",
    "enqueue_incremental_export",
]

#: Every plan gets its own secondary calendar.
CALENDAR_TITLE_PREFIX = "guru - "

GOOGLE_CALENDAR = "google_calendar"
_TARGETS = (GOOGLE_CALENDAR,)

STATUS_QUEUED = "queued"
STATUS_SYNCED = "synced"
STATUS_FAILED = "failed"
ERROR_REAUTH_REQUIRED = "reauth_required"


class ExportStatusView(BaseModel):
    target: str
    status: str
    external_calendar_id: str | None
    last_synced_at: datetime | None
    error: str | None
    pending_changes: int = 0


class ExportRequestResult(BaseModel):
    target: str
    mode: str
    job_id: str


async def enqueue_incremental_export(
    exports: PlanExportRepo, queue: QueuePort, plan_id: UUID
) -> None:
    """Push what changed, but only where a calendar already exists to push it to."""
    for record in await exports.list_for_plan(plan_id):
        if record.external_calendar_id:
            await queue.enqueue(
                ExportJobV1(plan_id=plan_id, target=record.target, mode="incremental")
            )


class RequestExport:
    """Only an active plan is exported: a draft is still a proposal."""

    def __init__(
        self,
        plans: PlanRepo,
        exports: PlanExportRepo,
        queue: QueuePort,
        tokens: GoogleAccessTokenProvider,
    ) -> None:
        self._plans = plans
        self._exports = exports
        self._queue = queue
        self._tokens = tokens

    async def __call__(self, user_id: UUID, plan_id: UUID, target: str) -> ExportRequestResult:
        plan = await self._plans.get(user_id, plan_id)
        if plan is None:
            raise NotFound(f"plan not found: {plan_id}")
        if plan.status != "active":
            raise Conflict(f"only an active plan can be exported; this one is {plan.status}")
        if target not in _TARGETS:
            raise InvalidInput(f"unknown export target: {target}")

        # Fails fast with ReauthRequired when Google is not connected, so the client can ask
        # for the connection instead of watching a queued job fail.
        await self._tokens.get(user_id)

        record = await self._exports.get(plan_id, target)
        calendar_id = record.external_calendar_id if record is not None else None
        mode = "incremental" if calendar_id else "full"
        await self._exports.upsert(
            plan_id,
            target,
            STATUS_QUEUED,
            calendar_id,
            record.last_synced_at if record is not None else None,
            None,
        )
        handle = await self._queue.enqueue(
            ExportJobV1.model_validate({"plan_id": plan_id, "target": target, "mode": mode})
        )
        return ExportRequestResult(target=target, mode=mode, job_id=handle.job_id)


class GetExportStatus:
    """`pending_changes` is the dirty count: exactly what the next push will send."""

    def __init__(self, plans: PlanRepo, exports: PlanExportRepo, tree: PlanTreeRepo) -> None:
        self._plans = plans
        self._exports = exports
        self._tree = tree

    async def __call__(self, user_id: UUID, plan_id: UUID) -> list[ExportStatusView]:
        if await self._plans.get(user_id, plan_id) is None:
            raise NotFound(f"plan not found: {plan_id}")
        dirty = len(await self._tree.list_dirty(plan_id))
        return [
            ExportStatusView(
                target=record.target,
                status=record.status,
                external_calendar_id=record.external_calendar_id,
                last_synced_at=record.last_synced_at,
                error=record.error,
                pending_changes=dirty,
            )
            for record in await self._exports.list_for_plan(plan_id)
        ]


class UnexportPlan:
    """Take the plan off the calendar: delete the calendar, forget every event id."""

    def __init__(
        self,
        plans: PlanRepo,
        tree: PlanTreeRepo,
        exports: PlanExportRepo,
        calendar: CalendarPort,
        tokens: GoogleAccessTokenProvider,
    ) -> None:
        self._plans = plans
        self._tree = tree
        self._exports = exports
        self._calendar = calendar
        self._tokens = tokens

    async def __call__(self, user_id: UUID, plan_id: UUID, target: str) -> None:
        if await self._plans.get(user_id, plan_id) is None:
            raise NotFound(f"plan not found: {plan_id}")
        record = await self._exports.get(plan_id, target)
        if record is None:
            raise NotFound(f"plan {plan_id} was never exported to {target}")
        if record.external_calendar_id:
            access_token = await self._tokens.get(user_id)
            await self._calendar.delete_calendar(access_token, record.external_calendar_id)
        for row in await self._tree.list_scheduled(plan_id):
            await self._tree.mark_synced(row.task.id, external_ref=None, synced_at=None)
        await self._exports.delete(plan_id, target)


class PushExport:
    """The `export.push` worker handler.

    `full` builds the plan's calendar from scratch; `incremental` replays only what changed.
    A handler never raises: whatever goes wrong ends up on the `plan_exports` row, which is
    what the client polls.
    """

    def __init__(
        self,
        plans: PlanRepo,
        tree: PlanTreeRepo,
        exports: PlanExportRepo,
        calendar: CalendarPort,
        tokens: GoogleAccessTokenProvider,
        colors: ColorMap,
        clock: ClockPort,
    ) -> None:
        self._plans = plans
        self._tree = tree
        self._exports = exports
        self._calendar = calendar
        self._tokens = tokens
        self._colors = colors
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
            rows = await self._tree.list_scheduled(job.plan_id)
        else:
            record = await self._exports.get(job.plan_id, job.target)
            if record is None or record.external_calendar_id is None:
                raise DomainError("incremental export needs a calendar; run a full export first")
            calendar_id = record.external_calendar_id
            rows = await self._tree.list_dirty(job.plan_id)

        now = self._clock.now()
        for row in rows:
            await self._sync(access_token, calendar_id, plan.title, row, now, replace=full)
        await self._exports.upsert(job.plan_id, job.target, STATUS_SYNCED, calendar_id, now, None)

    async def _sync(
        self,
        access_token: str,
        calendar_id: str,
        plan_title: str,
        row: ScheduledTaskRow,
        now: datetime,
        replace: bool,
    ) -> None:
        """`replace` means the old calendar is gone, so any stored event id is stale."""
        external_ref = None if replace else row.slot.external_ref

        if not should_export(row):
            # A slot that left the export takes its event with it; marking it synced keeps
            # it out of the next dirty list.
            if external_ref is not None:
                await self._calendar.delete_event(access_token, calendar_id, external_ref)
            await self._tree.mark_synced(row.task.id, external_ref=None, synced_at=now)
            return

        event = CalendarEventWrite(**to_calendar_event(row, self._colors, plan_title).model_dump())
        if external_ref is None:
            external_ref = await self._calendar.create_event(access_token, calendar_id, event)
        else:
            await self._calendar.update_event(access_token, calendar_id, external_ref, event)
        await self._tree.mark_synced(row.task.id, external_ref=external_ref, synced_at=now)

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
