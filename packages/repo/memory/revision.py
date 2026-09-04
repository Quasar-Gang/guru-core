"""InMemoryPlanRevisionRepo — 測試用的記憶體實作。"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from packages.repo.entities import PlanRevision

OPEN_STATUSES = ("pending", "proposed")


class InMemoryPlanRevisionRepo:
    """把 plan_revisions 放在 process 記憶體中的 PlanRevisionRepo 實作。"""

    def __init__(self) -> None:
        self._revisions: dict[UUID, PlanRevision] = {}

    async def create(self, plan_id: UUID, strategy: str, note: str | None) -> PlanRevision:
        revision = PlanRevision(
            id=uuid.uuid4(),
            plan_id=plan_id,
            trigger="manual",
            strategy=strategy,
            trigger_detail=None,
            proposed_tasks=None,
            diff=None,
            rationale=note,
            status="pending",
            created_at=datetime.now(UTC),
            decided_at=None,
        )
        self._revisions[revision.id] = revision
        return revision

    async def get(self, plan_id: UUID, revision_id: UUID) -> PlanRevision | None:
        revision = self._revisions.get(revision_id)
        return revision if revision is not None and revision.plan_id == plan_id else None

    async def get_unscoped(self, revision_id: UUID) -> PlanRevision | None:
        return self._revisions.get(revision_id)

    async def list_for_plan(self, plan_id: UUID) -> list[PlanRevision]:
        found = [r for r in self._revisions.values() if r.plan_id == plan_id]
        found.sort(key=lambda r: r.created_at)
        return found

    async def has_open(self, plan_id: UUID) -> bool:
        return any(
            r.plan_id == plan_id and r.status in OPEN_STATUSES for r in self._revisions.values()
        )

    async def set_proposal(
        self,
        revision_id: UUID,
        proposed_tasks: list[dict[str, Any]],
        diff: list[dict[str, Any]],
        rationale: str,
    ) -> None:
        self._update(
            revision_id,
            {
                "proposed_tasks": list(proposed_tasks),
                "diff": list(diff),
                "rationale": rationale,
            },
        )

    async def set_status(self, revision_id: UUID, status: str, decided_at: datetime | None) -> None:
        self._update(revision_id, {"status": status, "decided_at": decided_at})

    def _update(self, revision_id: UUID, fields: dict[str, Any]) -> None:
        revision = self._revisions.get(revision_id)
        if revision is None:
            raise KeyError(revision_id)
        self._revisions[revision_id] = revision.model_copy(update=fields)
