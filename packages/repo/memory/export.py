"""InMemoryPlanExportRepo — in-memory implementation for tests."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from uuid import UUID

from packages.repo.entities import PlanExport


class InMemoryPlanExportRepo:
    """Keeps plan_exports in memory, keyed uniquely by (plan_id, target)."""

    def __init__(self) -> None:
        self._exports: dict[tuple[UUID, str], PlanExport] = {}

    async def get(self, plan_id: UUID, target: str) -> PlanExport | None:
        return self._exports.get((plan_id, target))

    async def list_for_plan(self, plan_id: UUID) -> list[PlanExport]:
        return [e for e in self._exports.values() if e.plan_id == plan_id]

    async def upsert(
        self,
        plan_id: UUID,
        target: str,
        status: str,
        external_calendar_id: str | None,
        last_synced_at: datetime | None,
        error: str | None,
    ) -> PlanExport:
        existing = self._exports.get((plan_id, target))
        export = PlanExport(
            id=existing.id if existing else uuid.uuid4(),
            plan_id=plan_id,
            target=target,
            external_calendar_id=external_calendar_id,
            last_synced_at=last_synced_at,
            status=status,
            error=error,
            created_at=existing.created_at if existing else datetime.now(UTC),
        )
        self._exports[(plan_id, target)] = export
        return export

    async def delete(self, plan_id: UUID, target: str) -> None:
        self._exports.pop((plan_id, target), None)
