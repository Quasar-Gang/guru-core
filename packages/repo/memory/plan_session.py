"""InMemoryPlanSessionRepo — 測試用的記憶體實作。"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from packages.repo.entities import PlanSession


class InMemoryPlanSessionRepo:
    """把 plan_sessions 放在 process 記憶體中的 PlanSessionRepo 實作。"""

    def __init__(self) -> None:
        self._sessions: dict[UUID, PlanSession] = {}

    async def create(
        self,
        user_id: UUID,
        goal: str,
        intake: dict[str, Any],
        import_ids: list[UUID],
        use_calendar: bool,
        trait_role_model_id: UUID | None,
        persona_role_model_id: UUID | None,
    ) -> PlanSession:
        now = datetime.now(UTC)
        session = PlanSession(
            id=uuid.uuid4(),
            user_id=user_id,
            trait_role_model_id=trait_role_model_id,
            persona_role_model_id=persona_role_model_id,
            goal=goal,
            intake=dict(intake),
            import_ids=list(import_ids),
            use_calendar=use_calendar,
            status="collecting",
            round=0,
            context_snapshot=None,
            error=None,
            created_at=now,
            updated_at=now,
        )
        self._sessions[session.id] = session
        return session

    async def get(self, user_id: UUID, session_id: UUID) -> PlanSession | None:
        session = self._sessions.get(session_id)
        return session if session is not None and session.user_id == user_id else None

    async def get_unscoped(self, session_id: UUID) -> PlanSession | None:
        return self._sessions.get(session_id)

    async def set_status(self, session_id: UUID, status: str, error: str | None = None) -> None:
        self._update(session_id, {"status": status, "error": error})

    async def bump_round(self, session_id: UUID) -> int:
        session = self._sessions.get(session_id)
        if session is None:
            raise KeyError(session_id)
        next_round = session.round + 1
        self._update(session_id, {"round": next_round})
        return next_round

    async def set_context_snapshot(self, session_id: UUID, snapshot: dict[str, Any]) -> None:
        self._update(session_id, {"context_snapshot": dict(snapshot)})

    def _update(self, session_id: UUID, fields: dict[str, Any]) -> None:
        session = self._sessions.get(session_id)
        if session is None:
            raise KeyError(session_id)
        self._sessions[session_id] = session.model_copy(
            update={**fields, "updated_at": datetime.now(UTC)}
        )
