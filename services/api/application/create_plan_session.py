"""Open a plan session and hand it to the Plan Engine (PRD 3.2)."""

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from pydantic import BaseModel

from packages.queue import PlanGenerateJobV1, QueuePort
from packages.repo import ImportRepo, OAuthConnectionRepo, PlanSessionRepo
from services.api.domain.errors import InvalidInput

__all__ = ["CreatePlanSession", "CreateSessionResult"]

#: Only a parsed import has a document behind it, so only a parsed import can feed a plan.
IMPORT_STATUS_PARSED = "parsed"
CALENDAR_PROVIDER = "google"


class CreateSessionResult(BaseModel):
    """What both `POST /plan-sessions` and `POST /plan-sessions/{id}/answers` return."""

    session_id: UUID
    job_id: str


class CreatePlanSession:
    """Validate the intake, persist the session, then enqueue `plan.generate`."""

    def __init__(
        self,
        sessions: PlanSessionRepo,
        imports: ImportRepo,
        oauth_connections: OAuthConnectionRepo,
        queue: QueuePort,
    ) -> None:
        self._sessions = sessions
        self._imports = imports
        self._oauth_connections = oauth_connections
        self._queue = queue

    async def __call__(
        self,
        user_id: UUID,
        goal: str,
        intake: dict[str, Any],
        import_ids: Sequence[UUID],
        trait_role_model_id: UUID | None,
        persona_role_model_id: UUID | None,
    ) -> CreateSessionResult:
        if not goal.strip():
            raise InvalidInput("goal must not be empty")
        await self._assert_imports_usable(user_id, import_ids)

        session = await self._sessions.create(
            user_id=user_id,
            goal=goal,
            intake=intake,
            import_ids=list(import_ids),
            use_calendar=await self._has_calendar(user_id),
            trait_role_model_id=trait_role_model_id,
            persona_role_model_id=persona_role_model_id,
        )
        handle = await self._queue.enqueue(PlanGenerateJobV1(session_id=session.id))
        return CreateSessionResult(session_id=session.id, job_id=handle.job_id)

    async def _assert_imports_usable(self, user_id: UUID, import_ids: Sequence[UUID]) -> None:
        """Every import must belong to this user and already be parsed."""
        for import_id in import_ids:
            record = await self._imports.get(user_id, import_id)
            if record is None:
                raise InvalidInput(f"unknown import: {import_id}")
            if record.status != IMPORT_STATUS_PARSED:
                raise InvalidInput(f"import {import_id} is not parsed yet")

    async def _has_calendar(self, user_id: UUID) -> bool:
        """The session may read the user's calendar only while the connection is live."""
        connection = await self._oauth_connections.get(user_id, CALENDAR_PROVIDER)
        return connection is not None and connection.revoked_at is None
