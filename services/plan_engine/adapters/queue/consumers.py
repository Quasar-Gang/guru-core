"""Queue adapters: widen the Plan Engine use cases to the handler signature ARQ expects."""

from packages.queue import JobPayload, PlanContinueJobV1, PlanGenerateJobV1
from services.plan_engine.application.evaluate_session import EvaluateSession

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
    """Placeholder for `plan.revise` so the queue is registered from the start."""

    async def __call__(self, payload: JobPayload) -> None:
        # TODO(Task 36): delegate to RevisePlan once the revision use case exists.
        raise NotImplementedError("plan.revise is not implemented yet")
