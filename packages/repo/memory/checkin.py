"""InMemoryCheckinRepo — 測試用的記憶體實作。"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

from packages.repo.entities import Checkin


class InMemoryCheckinRepo:
    """把 checkins 放在記憶體中，以 (plan_id, checkin_date) 為唯一鍵。"""

    def __init__(self) -> None:
        self._checkins: dict[tuple[UUID, date], Checkin] = {}

    async def upsert(
        self,
        plan_id: UUID,
        checkin_date: date,
        task_results: list[dict[str, Any]],
        note: str | None,
    ) -> Checkin:
        existing = self._checkins.get((plan_id, checkin_date))
        checkin = Checkin(
            id=existing.id if existing else uuid.uuid4(),
            plan_id=plan_id,
            checkin_date=checkin_date,
            task_results=list(task_results),
            note=note,
            created_at=existing.created_at if existing else datetime.now(UTC),
        )
        self._checkins[(plan_id, checkin_date)] = checkin
        return checkin

    async def list_for_plan(self, plan_id: UUID) -> list[Checkin]:
        found = [c for c in self._checkins.values() if c.plan_id == plan_id]
        found.sort(key=lambda c: c.checkin_date)
        return found
