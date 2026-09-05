"""In-memory repo for Station 3."""

from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID, uuid4

from packages.repo.entities import Reconciliation
from packages.repo.memory.identity import now

__all__ = ["InMemoryReconciliationRepo"]


class InMemoryReconciliationRepo:
    def __init__(self) -> None:
        self._rows: dict[UUID, Reconciliation] = {}

    async def create(
        self, user_id: UUID, hypothesis_id: UUID, period_start: date, period_end: date
    ) -> Reconciliation:
        moment = now()
        row = Reconciliation(
            id=uuid4(),
            user_id=user_id,
            hypothesis_id=hypothesis_id,
            status="pending",
            period_start=period_start,
            period_end=period_end,
            comparison={},
            narrative="",
            outcome=None,
            revision_kind=None,
            error=None,
            created_at=moment,
            updated_at=moment,
        )
        self._rows[row.id] = row
        return row

    async def get(self, user_id: UUID, reconciliation_id: UUID) -> Reconciliation | None:
        row = self._rows.get(reconciliation_id)
        return row if row is not None and row.user_id == user_id else None

    async def get_unscoped(self, reconciliation_id: UUID) -> Reconciliation | None:
        return self._rows.get(reconciliation_id)

    async def list_for_hypothesis(self, hypothesis_id: UUID) -> list[Reconciliation]:
        rows = [row for row in self._rows.values() if row.hypothesis_id == hypothesis_id]
        return sorted(rows, key=lambda row: row.created_at)

    async def complete(
        self,
        reconciliation_id: UUID,
        comparison: dict[str, Any],
        narrative: str,
        revision_kind: str | None,
    ) -> None:
        self._update(
            reconciliation_id,
            {
                "status": "done",
                "comparison": comparison,
                "narrative": narrative,
                "revision_kind": revision_kind,
                "error": None,
            },
        )

    async def decide(self, reconciliation_id: UUID, outcome: str) -> None:
        self._update(reconciliation_id, {"outcome": outcome})

    async def fail(self, reconciliation_id: UUID, error: str) -> None:
        self._update(reconciliation_id, {"status": "failed", "error": error})

    def _update(self, reconciliation_id: UUID, fields: dict[str, Any]) -> None:
        row = self._rows.get(reconciliation_id)
        if row is not None:
            self._rows[reconciliation_id] = row.model_copy(update={**fields, "updated_at": now()})
