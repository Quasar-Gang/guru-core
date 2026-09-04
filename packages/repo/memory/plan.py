"""InMemoryPlanRepo — 測試用的記憶體實作。"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from packages.repo.entities import NewPlan, Plan


class InMemoryPlanRepo:
    """把 plans 放在 process 記憶體中的 PlanRepo 實作。"""

    def __init__(self) -> None:
        self._plans: dict[UUID, Plan] = {}

    async def create_many(self, plans: Sequence[NewPlan]) -> list[Plan]:
        now = datetime.now(UTC)
        created: list[Plan] = []
        for new_plan in plans:
            plan = Plan(
                id=uuid.uuid4(),
                activated_at=None,
                archived_at=None,
                created_at=now,
                updated_at=now,
                **new_plan.model_dump(),
            )
            self._plans[plan.id] = plan
            created.append(plan)
        return created

    async def get(self, user_id: UUID, plan_id: UUID) -> Plan | None:
        plan = self._plans.get(plan_id)
        return plan if plan is not None and plan.user_id == user_id else None

    async def get_unscoped(self, plan_id: UUID) -> Plan | None:
        return self._plans.get(plan_id)

    async def list_for_user(self, user_id: UUID, status: str | None) -> list[Plan]:
        found = [p for p in self._plans.values() if p.user_id == user_id]
        if status is not None:
            found = [p for p in found if p.status == status]
        found.sort(key=lambda p: p.created_at)
        return found

    async def list_for_session(self, session_id: UUID) -> list[Plan]:
        found = [p for p in self._plans.values() if p.session_id == session_id]
        found.sort(key=lambda p: p.created_at)
        return found

    async def update_fields(self, plan_id: UUID, **fields: Any) -> Plan:
        plan = self._plans.get(plan_id)
        if plan is None:
            raise KeyError(plan_id)
        updated = plan.model_copy(update={**fields, "updated_at": datetime.now(UTC)})
        self._plans[plan_id] = updated
        return updated

    async def set_status_for_session(
        self, session_id: UUID, status: str, exclude_plan_id: UUID
    ) -> None:
        now = datetime.now(UTC)
        for plan in list(self._plans.values()):
            if plan.session_id == session_id and plan.id != exclude_plan_id:
                self._plans[plan.id] = plan.model_copy(update={"status": status, "updated_at": now})

    async def delete(self, plan_id: UUID) -> None:
        self._plans.pop(plan_id, None)
