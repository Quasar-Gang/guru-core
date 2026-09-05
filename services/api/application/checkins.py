"""The daily check-in: one row per plan and day, written straight through to the tasks.

A check-in is a bulk task update with a note attached. Keeping it as its own row is what
gives Station 3 something to read: the tasks say what state they ended in, the check-ins say
when the user actually said so.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

from packages.queue import QueuePort
from packages.repo import CheckinRepo, PlanExportRepo, PlanTreeRepo
from packages.repo.entities import Checkin, TaskStatusUpdate
from services.api.application.exports import enqueue_incremental_export
from services.api.application.plans import GetPlan
from services.api.application.ports import ClockPort
from services.api.domain.errors import InvalidInput

__all__ = [
    "CheckinHistory",
    "CheckinResultInput",
    "CheckinView",
    "DailyRate",
    "ListCheckins",
    "SubmitCheckin",
]


class CheckinResultInput(BaseModel):
    """What the user ticked for one task."""

    task_id: UUID
    status: Literal["done", "missed", "skipped"]


class CheckinView(BaseModel):
    id: UUID
    checkin_date: date
    results: list[CheckinResultInput]
    note: str | None
    created_at: datetime


class DailyRate(BaseModel):
    date: date
    done: int
    total: int
    rate: float


class CheckinHistory(BaseModel):
    items: list[CheckinView]
    daily_rates: list[DailyRate]


class SubmitCheckin:
    def __init__(
        self,
        get_plan: GetPlan,
        tree: PlanTreeRepo,
        checkins: CheckinRepo,
        exports: PlanExportRepo,
        queue: QueuePort,
        clock: ClockPort,
    ) -> None:
        self._get_plan = get_plan
        self._tree = tree
        self._checkins = checkins
        self._exports = exports
        self._queue = queue
        self._clock = clock

    async def __call__(
        self,
        user_id: UUID,
        plan_id: UUID,
        checkin_date: date,
        results: Sequence[CheckinResultInput],
        note: str | None,
    ) -> CheckinView:
        await self._get_plan.load(user_id, plan_id)
        for result in results:
            if await self._tree.get_task(plan_id, result.task_id) is None:
                raise InvalidInput(f"task {result.task_id} does not belong to plan {plan_id}")

        checkin = await self._checkins.upsert(
            plan_id, checkin_date, [row.model_dump(mode="json") for row in results], note
        )
        now = self._clock.now()
        await self._tree.bulk_set_status(
            plan_id,
            [
                TaskStatusUpdate(
                    task_id=result.task_id,
                    status=result.status,
                    completed_at=now if result.status == "done" else None,
                )
                for result in results
            ],
        )
        # A bulk status write does not touch the export bookkeeping, so mark them here.
        for result in results:
            await self._tree.mark_dirty(result.task_id)
        if results:
            await enqueue_incremental_export(self._exports, self._queue, plan_id)
        return _view(checkin)


class ListCheckins:
    """One `DailyRate` per check-in: `done / total` over what that day's submission covered."""

    def __init__(self, get_plan: GetPlan, checkins: CheckinRepo) -> None:
        self._get_plan = get_plan
        self._checkins = checkins

    async def __call__(self, user_id: UUID, plan_id: UUID) -> CheckinHistory:
        await self._get_plan.load(user_id, plan_id)
        items = [_view(row) for row in await self._checkins.list_for_plan(plan_id)]
        return CheckinHistory(
            items=items,
            daily_rates=[
                DailyRate(
                    date=item.checkin_date,
                    done=_done(item),
                    total=len(item.results),
                    rate=_done(item) / len(item.results) if item.results else 0.0,
                )
                for item in items
            ],
        )


def _view(checkin: Checkin) -> CheckinView:
    return CheckinView(
        id=checkin.id,
        checkin_date=checkin.checkin_date,
        results=[CheckinResultInput.model_validate(row) for row in checkin.task_results],
        note=checkin.note,
        created_at=checkin.created_at,
    )


def _done(item: CheckinView) -> int:
    return sum(1 for result in item.results if result.status == "done")
