"""Queue adapters: widen the Plan Engine use cases to the handler signature ARQ expects."""

from packages.queue import JobPayload, PlanContinueJobV1, PlanGenerateJobV1, PlanReviseJobV1
from services.plan_engine.application.evaluate_session import EvaluateSession
from services.plan_engine.application.revise_plan import RevisePlan

__all__ = ["EvaluateSessionConsumer", "PlanReviseConsumer"]


class EvaluateSessionConsumer:
    """Handles both `plan.generate` and `plan.continue`.

    The two queues carry the same work — evaluate the session, then either ask another round
    of questions or generate — so one consumer serves both, exactly as `EvaluateSession` does.
    """

    def __init__(self, evaluate_session: EvaluateSession) -> None:
        self._evaluate_session = evaluate_session

    async def __call__(self, payload: JobPayload) -> None:
        if not isinstance(payload, PlanGenerateJobV1 | PlanContinueJobV1):
            raise TypeError(
                f"expected PlanGenerateJobV1 or PlanContinueJobV1, got {type(payload).__name__}"
            )
        await self._evaluate_session(payload)


class PlanReviseConsumer:
    """Handles `plan.revise`: propose a revision of a running plan (PRD 3.8)."""

    def __init__(self, revise_plan: RevisePlan) -> None:
        self._revise_plan = revise_plan

    async def __call__(self, payload: JobPayload) -> None:
        if not isinstance(payload, PlanReviseJobV1):
            raise TypeError(f"expected PlanReviseJobV1, got {type(payload).__name__}")
        await self._revise_plan(payload)
