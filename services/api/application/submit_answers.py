"""Record the user's answers to a follow-up round and resume the engine (PRD 3.2)."""

from collections.abc import Sequence
from uuid import UUID

from pydantic import BaseModel

from packages.queue import PlanContinueJobV1, QueuePort
from packages.repo import FollowupRoundRepo, PlanSessionRepo
from services.api.application.create_plan_session import CreateSessionResult
from services.api.application.ports import ClockPort
from services.api.domain.errors import Conflict, NotFound

__all__ = ["AnswerInput", "SubmitAnswers"]

STATUS_QUESTIONING = "questioning"


class AnswerInput(BaseModel):
    """One answer: a picked option, a free-text reply, or an explicit skip."""

    question_id: str
    choice: str | None = None
    custom: str | None = None
    skipped: bool = False


class SubmitAnswers:
    """Answers are only accepted while the session is waiting for them."""

    def __init__(
        self,
        sessions: PlanSessionRepo,
        followups: FollowupRoundRepo,
        queue: QueuePort,
        clock: ClockPort,
    ) -> None:
        self._sessions = sessions
        self._followups = followups
        self._queue = queue
        self._clock = clock

    async def __call__(
        self, user_id: UUID, session_id: UUID, answers: Sequence[AnswerInput]
    ) -> CreateSessionResult:
        session = await self._sessions.get(user_id, session_id)
        if session is None:
            raise NotFound(f"plan session not found: {session_id}")
        if session.status != STATUS_QUESTIONING:
            raise Conflict(f"session {session_id} is not asking questions ({session.status})")

        latest = await self._followups.latest(session_id)
        if latest is None:
            raise Conflict(f"session {session_id} has no follow-up round to answer")

        await self._followups.record_answers(
            latest.id,
            [answer.model_dump(mode="json") for answer in answers],
            self._clock.now(),
        )
        handle = await self._queue.enqueue(PlanContinueJobV1(session_id=session_id))
        return CreateSessionResult(session_id=session_id, job_id=handle.job_id)
