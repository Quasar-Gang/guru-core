"""Check-in history plus the completion-rate curve the progress screen draws (PRD 3.7)."""

from datetime import date
from uuid import UUID

from pydantic import BaseModel

from packages.repo import CheckinRepo, PlanRepo
from services.api.application.submit_checkin import CheckinView, checkin_view
from services.api.domain.errors import NotFound

__all__ = ["CheckinHistory", "DailyRate", "ListCheckins"]


class DailyRate(BaseModel):
    date: date
    done: int
    total: int
    rate: float


class CheckinHistory(BaseModel):
    items: list[CheckinView]
    daily_rates: list[DailyRate]


class ListCheckins:
    """One `DailyRate` per check-in: `done / total` over what that day's submission covered."""

    def __init__(self, plans: PlanRepo, checkins: CheckinRepo) -> None:
        self._plans = plans
        self._checkins = checkins

    async def __call__(self, user_id: UUID, plan_id: UUID) -> CheckinHistory:
        if await self._plans.get(user_id, plan_id) is None:
            raise NotFound(f"plan not found: {plan_id}")

        items = [checkin_view(c) for c in await self._checkins.list_for_plan(plan_id)]
        rates = [
            DailyRate(
                date=item.checkin_date,
                done=_done(item),
                total=len(item.results),
                rate=_done(item) / len(item.results) if item.results else 0.0,
            )
            for item in items
        ]
        return CheckinHistory(items=items, daily_rates=rates)


def _done(item: CheckinView) -> int:
    return sum(1 for result in item.results if result.status == "done")
