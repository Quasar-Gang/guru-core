"""Ask the Plan Engine for a revision (PRD 3.8: `POST /plans/{id}/revisions`)."""

from typing import Literal, cast
from uuid import UUID

from pydantic import BaseModel

from packages.queue import PlanReviseJobV1, QueuePort
from packages.repo import PlanRevisionRepo
from services.api.application.get_plan import GetPlan
from services.api.domain.errors import Conflict, InvalidInput
from services.api.domain.plan_status import PlanStatus

__all__ = ["STRATEGIES", "CreateRevision", "CreateRevisionResult"]

#: The two strategies of PRD 3.8.1; the same values `PlanReviseJobV1.strategy` accepts.
STRATEGIES = ("postpone", "reduce")


class CreateRevisionResult(BaseModel):
    """202 body: the revision exists, but its proposal is computed by the engine."""

    revision_id: UUID
    job_id: str


class CreateRevision:
    """Only a running plan can be revised, and only one revision may be open at a time."""

    def __init__(self, revisions: PlanRevisionRepo, queue: QueuePort, get_plan: GetPlan) -> None:
        self._revisions = revisions
        self._queue = queue
        self._get_plan = get_plan

    async def __call__(
        self, user_id: UUID, plan_id: UUID, strategy: str, note: str | None
    ) -> CreateRevisionResult:
        plan = await self._get_plan.load(user_id, plan_id)
        if strategy not in STRATEGIES:
            raise InvalidInput(f"unknown revision strategy: {strategy}")
        if plan.status != PlanStatus.active.value:
            raise Conflict(f"only an active plan can be revised, this one is {plan.status}")
        if await self._revisions.has_open(plan_id):
            raise Conflict("this plan already has an open revision")

        revision = await self._revisions.create(plan_id, strategy, note)
        handle = await self._queue.enqueue(
            PlanReviseJobV1(
                plan_id=plan_id,
                revision_id=revision.id,
                strategy=cast(Literal["postpone", "reduce"], strategy),
            )
        )
        return CreateRevisionResult(revision_id=revision.id, job_id=handle.job_id)
