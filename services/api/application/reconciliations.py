"""Station 3 over HTTP: open a review, read what it found, and answer its question.

The system computes the comparison and narrates it. It does not decide. `outcome` stays
null until the user says whether the shape still counts — and answering `revise` is what
writes the next version of the hypothesis, which is why that answer lives here rather than
in the worker.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from packages.queue import QueuePort, ReconcileJobV1
from packages.repo import (
    DirectionHypothesisRepo,
    QuestionAnswerRepo,
    QuotaRepo,
    ReconciliationRepo,
)
from packages.repo.entities import Reconciliation
from services.api.application.ports import ClockPort
from services.api.domain.errors import Conflict, NotFound

__all__ = [
    "DecideReconciliation",
    "GetReconciliation",
    "Outcome",
    "ReconciliationView",
    "StartReconciliation",
]

Outcome = Literal["holds", "revise", "replace"]

_OPEN = ("pending", "running")


class ReconciliationView(BaseModel):
    id: UUID
    hypothesis_id: UUID
    status: str
    period_start: date
    period_end: date
    comparison: dict[str, Any] = Field(default_factory=dict)
    narrative: str = ""
    outcome: str | None = None
    revision_kind: str | None = None
    error: str | None = None
    next_hypothesis_id: UUID | None = None


class StartReconciliation:
    """Open the quarterly review of one hypothesis. The review date is a prompt, not a gate.

    A user who wants to look early is allowed to: the point of the station is to make the
    comparison available, not to withhold it until a date passes.
    """

    def __init__(
        self,
        reconciliations: ReconciliationRepo,
        hypotheses: DirectionHypothesisRepo,
        queue: QueuePort,
        clock: ClockPort,
    ) -> None:
        self._reconciliations = reconciliations
        self._hypotheses = hypotheses
        self._queue = queue
        self._clock = clock

    async def __call__(self, user_id: UUID, hypothesis_id: UUID) -> ReconciliationView:
        hypothesis = await self._hypotheses.get(user_id, hypothesis_id)
        if hypothesis is None:
            raise NotFound(f"hypothesis not found: {hypothesis_id}")
        existing = await self._reconciliations.list_for_hypothesis(hypothesis_id)
        if any(row.status in _OPEN for row in existing):
            raise Conflict("a reconciliation for that hypothesis is already running")
        created = await self._reconciliations.create(
            user_id,
            hypothesis_id,
            period_start=hypothesis.created_at.date(),
            period_end=self._clock.now().date(),
        )
        await self._queue.enqueue(ReconcileJobV1(reconciliation_id=created.id))
        return _view(created)


class GetReconciliation:
    def __init__(self, reconciliations: ReconciliationRepo) -> None:
        self._reconciliations = reconciliations

    async def __call__(self, user_id: UUID, reconciliation_id: UUID) -> ReconciliationView:
        row = await self._reconciliations.get(user_id, reconciliation_id)
        if row is None:
            raise NotFound(f"reconciliation not found: {reconciliation_id}")
        return _view(row)


class DecideReconciliation:
    """The user's answer to the one question the review ends on.

    `revise` appends the next version of the hypothesis, carrying the same shape forward
    with a new date and a new review. `v0` is not touched — it never is.
    """

    def __init__(
        self,
        reconciliations: ReconciliationRepo,
        hypotheses: DirectionHypothesisRepo,
        quotas: QuotaRepo,
        answers: QuestionAnswerRepo,
        clock: ClockPort,
    ) -> None:
        self._reconciliations = reconciliations
        self._hypotheses = hypotheses
        self._quotas = quotas
        self._answers = answers
        self._clock = clock

    async def __call__(
        self, user_id: UUID, reconciliation_id: UUID, outcome: Outcome
    ) -> ReconciliationView:
        row = await self._reconciliations.get(user_id, reconciliation_id)
        if row is None:
            raise NotFound(f"reconciliation not found: {reconciliation_id}")
        if row.status != "done":
            raise Conflict(f"this reconciliation is {row.status}; there is nothing to answer yet")
        if row.outcome is not None:
            raise Conflict(f"this reconciliation was already answered {row.outcome!r}")

        await self._reconciliations.decide(reconciliation_id, outcome)
        next_id: UUID | None = None
        if outcome == "revise":
            next_id = await self._append_next_version(user_id, row)
        decided = await self._reconciliations.get(user_id, reconciliation_id)
        assert decided is not None
        return _view(decided, next_hypothesis_id=next_id)

    async def _append_next_version(self, user_id: UUID, row: Reconciliation) -> UUID:
        previous = await self._hypotheses.get(user_id, row.hypothesis_id)
        if previous is None:
            raise NotFound(f"hypothesis not found: {row.hypothesis_id}")
        quota = await self._quotas.get(user_id)
        answered = [item for item in await self._answers.list_for_user(user_id) if not item.skipped]
        created = await self._hypotheses.append(
            user_id=user_id,
            role_model_id=previous.role_model_id,
            fit_verdict_id=previous.fit_verdict_id,
            source=f"revised after the review of v{previous.version}",
            evidence_snapshot={
                "previous_version": previous.version,
                "comparison": row.comparison,
                "revision_kind": row.revision_kind,
            },
            drop_first=quota.drop_first if quota is not None else previous.drop_first,
            answers_count=len(answered),
            review_date=self._clock.now().date()
            + (previous.review_date - previous.created_at.date()),
        )
        return created.id


def _view(row: Reconciliation, next_hypothesis_id: UUID | None = None) -> ReconciliationView:
    return ReconciliationView(
        id=row.id,
        hypothesis_id=row.hypothesis_id,
        status=row.status,
        period_start=row.period_start,
        period_end=row.period_end,
        comparison=row.comparison,
        narrative=row.narrative,
        outcome=row.outcome,
        revision_kind=row.revision_kind,
        error=row.error,
        next_hypothesis_id=next_hypothesis_id,
    )
