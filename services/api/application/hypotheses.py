"""The Direction Hypothesis — append-only, and the only way into Station 2.

This is not a vision. It is a borrowed shape, stamped with its date and its source and left
alone. Never overwritten is the point: a hypothesis you can quietly edit can never be
falsified, because you would simply rewrite it to match whatever you ended up doing and
learn nothing. So there is no update route here, and no repository method behind one.

Creating a hypothesis also creates its Plan, in status `generating`. One Plan per
Hypothesis, no variants — the shape has been chosen, and the plan is what testing it looks
like.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any
from uuid import UUID

from pydantic import BaseModel

from packages.queue import PlanGenerateJobV1, QueuePort
from packages.repo import (
    DirectionHypothesisRepo,
    FitVerdictRepo,
    PlanRepo,
    QuestionAnswerRepo,
    QuotaRepo,
    RoleModelRepo,
)
from packages.repo.entities import DirectionHypothesis
from services.api.application.ports import ClockPort
from services.api.domain.errors import InvalidInput, NotFound

__all__ = ["CreateHypothesis", "GetHypothesis", "HypothesisView", "ListHypotheses"]

#: One quarter. Short enough that a wrong direction costs a season instead of five years,
#: long enough that behaviour has time to say something.
REVIEW_AFTER_DAYS = 91


class HypothesisView(BaseModel):
    """A hypothesis as the app shows it, with the plan it produced."""

    id: UUID
    version: int
    role_model_id: UUID
    role_model_code: str
    role_model_name: str
    fit_verdict_id: UUID
    source: str
    evidence_snapshot: dict[str, Any]
    drop_first: str | None
    answers_count: int
    review_date: date
    created_at: datetime
    plan_id: UUID | None = None


class CreateHypothesis:
    """Settle on one shape, and start the plan that tests it."""

    def __init__(
        self,
        hypotheses: DirectionHypothesisRepo,
        verdicts: FitVerdictRepo,
        role_models: RoleModelRepo,
        quotas: QuotaRepo,
        answers: QuestionAnswerRepo,
        plans: PlanRepo,
        queue: QueuePort,
        clock: ClockPort,
    ) -> None:
        self._hypotheses = hypotheses
        self._verdicts = verdicts
        self._role_models = role_models
        self._quotas = quotas
        self._answers = answers
        self._plans = plans
        self._queue = queue
        self._clock = clock

    async def __call__(self, user_id: UUID, fit_verdict_id: UUID) -> HypothesisView:
        verdict = await self._verdicts.get(user_id, fit_verdict_id)
        if verdict is None:
            raise NotFound(f"fit verdict not found: {fit_verdict_id}")
        role_model = await self._role_models.get(verdict.role_model_id)
        if role_model is None:
            raise InvalidInput("that verdict points at a role model that no longer exists")

        quota = await self._quotas.get(user_id)
        answered = [row for row in await self._answers.list_for_user(user_id) if not row.skipped]
        created = await self._hypotheses.append(
            user_id=user_id,
            role_model_id=role_model.id,
            fit_verdict_id=verdict.id,
            source=f"{role_model.code} + your own data",
            # The evidence is copied, not referenced. A verdict can be re-run; what this
            # hypothesis was built on must stay readable exactly as it was.
            evidence_snapshot={
                "fit": verdict.fit,
                "verdict": verdict.verdict,
                "evidence": list(verdict.evidence),
                "probe": dict(verdict.probe),
                "cost": role_model.cost,
            },
            drop_first=quota.drop_first if quota is not None else None,
            answers_count=len(answered),
            review_date=self._clock.now().date() + timedelta(days=REVIEW_AFTER_DAYS),
        )
        plan = await self._plans.create(user_id, created.id)
        await self._queue.enqueue(PlanGenerateJobV1(plan_id=plan.id))
        return _view(created, role_model.code, role_model.name, plan.id)


class ListHypotheses:
    """Every version, oldest first. v0 stays readable forever as the thing predicted."""

    def __init__(
        self,
        hypotheses: DirectionHypothesisRepo,
        role_models: RoleModelRepo,
        plans: PlanRepo,
    ) -> None:
        self._hypotheses = hypotheses
        self._role_models = role_models
        self._plans = plans

    async def __call__(self, user_id: UUID) -> list[HypothesisView]:
        rows = await self._hypotheses.list_for_user(user_id)
        return [await _hydrate(row, self._role_models, self._plans) for row in rows]


class GetHypothesis:
    def __init__(
        self,
        hypotheses: DirectionHypothesisRepo,
        role_models: RoleModelRepo,
        plans: PlanRepo,
    ) -> None:
        self._hypotheses = hypotheses
        self._role_models = role_models
        self._plans = plans

    async def __call__(self, user_id: UUID, hypothesis_id: UUID) -> HypothesisView:
        row = await self._hypotheses.get(user_id, hypothesis_id)
        if row is None:
            raise NotFound(f"hypothesis not found: {hypothesis_id}")
        return await _hydrate(row, self._role_models, self._plans)


async def _hydrate(
    row: DirectionHypothesis, role_models: RoleModelRepo, plans: PlanRepo
) -> HypothesisView:
    role_model = await role_models.get(row.role_model_id)
    plan = await plans.get_by_hypothesis(row.id)
    return _view(
        row,
        role_model.code if role_model is not None else "",
        role_model.name if role_model is not None else "",
        plan.id if plan is not None else None,
    )


def _view(row: DirectionHypothesis, code: str, name: str, plan_id: UUID | None) -> HypothesisView:
    return HypothesisView(
        id=row.id,
        version=row.version,
        role_model_id=row.role_model_id,
        role_model_code=code,
        role_model_name=name,
        fit_verdict_id=row.fit_verdict_id,
        source=row.source,
        evidence_snapshot=row.evidence_snapshot,
        drop_first=row.drop_first,
        answers_count=row.answers_count,
        review_date=row.review_date,
        created_at=row.created_at,
        plan_id=plan_id,
    )
