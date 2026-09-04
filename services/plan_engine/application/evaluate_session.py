"""Decide whether a session has enough information to plan, and ask for what is missing.

Handles both `plan.generate` (the first pass) and `plan.continue` (after the user answered a
round of follow-up questions); the two differ only in which queue delivered them, so they
share one implementation (PRD 3.1, 3.2, 3.4).
"""

from __future__ import annotations

from uuid import UUID

from packages.cache.ports import CachePort
from packages.llm.ports import LLMPort, Purpose
from packages.llm.validation import complete_validated
from packages.queue.jobs import PlanContinueJobV1, PlanGenerateJobV1
from packages.repo.ports import FollowupRoundRepo, PlanSessionRepo
from services.plan_engine.application.context_builder import ContextBuilder
from services.plan_engine.application.generate_plans import GeneratePlans
from services.plan_engine.domain.readiness import (
    ReadinessConfig,
    ReadinessOutput,
    readiness_rules,
)
from services.plan_engine.domain.session import SessionStatus, assert_transition, is_terminal

__all__ = ["EvaluateSession"]

#: `plan_sessions.status` is the authority; Redis only serves the polling endpoint.
STATUS_CACHE_TTL_SECONDS = 3600


def status_cache_key(session_id: UUID) -> str:
    return f"session:{session_id}:status"


class EvaluateSession:
    """The `evaluating` step of the session state machine."""

    def __init__(
        self,
        sessions: PlanSessionRepo,
        followups: FollowupRoundRepo,
        context_builder: ContextBuilder,
        llm: LLMPort,
        readiness: ReadinessConfig,
        generate_plans: GeneratePlans,
        cache: CachePort,
        max_attempts: int,
    ) -> None:
        self._sessions = sessions
        self._followups = followups
        self._context_builder = context_builder
        self._llm = llm
        self._readiness = readiness
        self._generate_plans = generate_plans
        self._cache = cache
        self._max_attempts = max_attempts

    async def __call__(self, job: PlanGenerateJobV1 | PlanContinueJobV1) -> None:
        session_id = job.session_id
        session = await self._sessions.get_unscoped(session_id)
        if session is None:
            raise LookupError(f"unknown plan session {session_id}")
        if is_terminal(SessionStatus(session.status)):
            return  # idempotent: a redelivered job must not restart a finished session

        try:
            await self._move(session_id, SessionStatus(session.status), SessionStatus.evaluating)

            context = await self._context_builder.build(session_id, Purpose.evaluate)
            await self._sessions.set_context_snapshot(session_id, context.model_dump(mode="json"))

            outcome = await complete_validated(
                self._llm,
                "evaluate_readiness",
                context.to_prompt_context()
                | {
                    "max_questions": self._readiness.max_questions_per_round,
                    "options_per_question": self._readiness.options_per_question,
                    "domain_probe_max_items": self._readiness.domain_probe.max_items,
                },
                ReadinessOutput,
                Purpose.evaluate,
                max_attempts=self._max_attempts,
                rules=readiness_rules(self._readiness, set(context.asked_metric_ids)),
                # A degraded evaluation counts as ready: we would rather plan on conservative
                # assumptions than trap the user in a loop of questions the model cannot form.
                # generate_plans records that in the plan's assumptions.
                fallback=lambda _violations: ReadinessOutput(ready=True, missing=[], questions=[]),
            )
            readiness = outcome.value

            rounds_exhausted = session.round >= self._readiness.max_followup_rounds
            if readiness.ready or rounds_exhausted:
                await self._move(session_id, SessionStatus.evaluating, SessionStatus.generating)
                await self._generate_plans(
                    session_id,
                    forced_missing=readiness.missing,
                    degraded=outcome.degraded,
                )
                # generate_plans owns the generating -> done move; mirror its result.
                await self._mirror(session_id)
                return

            await self._followups.create(
                session_id,
                session.round,
                [question.model_dump(mode="json") for question in readiness.questions],
            )
            await self._sessions.bump_round(session_id)
            await self._move(session_id, SessionStatus.evaluating, SessionStatus.questioning)
        except Exception as exc:
            await self._fail(session_id, exc)
            raise  # let ARQ record the failure

    async def _move(self, session_id: UUID, current: SessionStatus, target: SessionStatus) -> None:
        assert_transition(current, target)
        await self._sessions.set_status(session_id, target.value)
        await self._cache.set(status_cache_key(session_id), target.value, STATUS_CACHE_TTL_SECONDS)

    async def _mirror(self, session_id: UUID) -> None:
        """Copy whatever status the database now holds into the cache."""
        session = await self._sessions.get_unscoped(session_id)
        if session is None:
            return
        await self._cache.set(
            status_cache_key(session_id), session.status, STATUS_CACHE_TTL_SECONDS
        )

    async def _fail(self, session_id: UUID, exc: Exception) -> None:
        """Mark the session failed, unless it already reached a terminal state."""
        session = await self._sessions.get_unscoped(session_id)
        if session is None:
            return
        if not is_terminal(SessionStatus(session.status)):
            await self._sessions.set_status(session_id, SessionStatus.failed.value, str(exc))
        await self._mirror(session_id)
