"""`reconcile.run` — Station 3, at the review date stamped on the Hypothesis.

Everything comparable is computed first and only then narrated. That order is the point: a
number the model produced could always have been produced to fit the story, and the whole
station exists to make the story answer to the numbers instead.

The job stops one step short of a decision. `outcome` stays null until the user answers the
question the note ends on — holds, revise, or replace. The system reads, shows the evidence,
and hands the decision back.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from packages.llm.ports import LLMPort, Purpose
from packages.llm.validation import complete_validated
from packages.repo.entities import DirectionHypothesis, Report
from packages.repo.ports import (
    DirectionHypothesisRepo,
    DirectionRunRepo,
    FitVerdictRepo,
    PlanRepo,
    PlanTreeRepo,
    QuestionAnswerRepo,
    ReconciliationRepo,
    ReportRepo,
    RoleModelRepo,
)
from services.engine.domain.diff import TaskSnapshotWithKey, diff_tasks
from services.engine.domain.dimensions import DIMENSIONS
from services.engine.domain.reconciliation import (
    Comparison,
    ReconciliationNoteOutput,
    classify_revision,
    compare,
)

__all__ = ["Reconcile"]

_Q2 = "q2"


class Reconcile:
    """One quarter, held against one Direction Hypothesis."""

    def __init__(
        self,
        reconciliations: ReconciliationRepo,
        hypotheses: DirectionHypothesisRepo,
        verdicts: FitVerdictRepo,
        role_models: RoleModelRepo,
        runs: DirectionRunRepo,
        reports: ReportRepo,
        plans: PlanRepo,
        tree: PlanTreeRepo,
        answers: QuestionAnswerRepo,
        llm: LLMPort,
        max_attempts: int,
    ) -> None:
        self._reconciliations = reconciliations
        self._hypotheses = hypotheses
        self._verdicts = verdicts
        self._role_models = role_models
        self._runs = runs
        self._reports = reports
        self._plans = plans
        self._tree = tree
        self._answers = answers
        self._llm = llm
        self._max_attempts = max_attempts

    async def __call__(self, reconciliation_id: UUID) -> None:
        row = await self._reconciliations.get_unscoped(reconciliation_id)
        if row is None:
            raise LookupError(f"unknown reconciliation {reconciliation_id}")
        try:
            hypothesis = await self._hypotheses.get_unscoped(row.hypothesis_id)
            if hypothesis is None:
                raise LookupError(f"unknown hypothesis {row.hypothesis_id}")
            comparison = await self._compare(hypothesis)
            revision_kind = classify_revision(comparison)
            narrative = await self._narrate(hypothesis, comparison, revision_kind)
            await self._reconciliations.complete(
                reconciliation_id,
                comparison.model_dump(mode="json"),
                narrative,
                revision_kind,
            )
        except Exception as exc:
            await self._reconciliations.fail(reconciliation_id, str(exc))
            raise

    # -------------------------------------------------------------------- the numbers

    async def _compare(self, hypothesis: DirectionHypothesis) -> Comparison:
        plan = await self._plans.get_by_hypothesis(hypothesis.id)
        status_counts = await self._tree.counts_by_status(plan.id) if plan is not None else {}
        baseline = _baseline(plan.structure if plan is not None else {})
        current = (
            [
                TaskSnapshotWithKey(
                    key=row.task.key,
                    week_index=row.task.week_index,
                    occurrence=row.task.occurrence,
                    title=row.task.title,
                    start_at=row.slot.start_at,
                    end_at=row.slot.end_at,
                    all_day=row.slot.all_day,
                )
                for row in await self._tree.list_scheduled(plan.id)
            ]
            if plan is not None
            else []
        )
        return compare(
            status_counts=status_counts,
            before_shares=await self._shares_at_hypothesis(hypothesis),
            after_shares=await self._shares_now(hypothesis.user_id),
            schedule_changes=[
                entry for entry in diff_tasks(baseline, current) if entry.kind != "unchanged"
            ],
            dimensions=list(DIMENSIONS),
        )

    async def _shares_at_hypothesis(self, hypothesis: DirectionHypothesis) -> dict[str, float]:
        verdict = await self._verdicts.get(hypothesis.user_id, hypothesis.fit_verdict_id)
        if verdict is None:
            return {}
        return _shares(await self._reports.list_for_run(verdict.run_id))

    async def _shares_now(self, user_id: UUID) -> dict[str, float]:
        """The latest analysis. When none has been re-run, every delta is honestly zero."""
        run = await self._runs.latest(user_id)
        if run is None:
            return {}
        return _shares(await self._reports.list_for_run(run.id))

    # ------------------------------------------------------------------ the narration

    async def _narrate(
        self,
        hypothesis: DirectionHypothesis,
        comparison: Comparison,
        revision_kind: str | None,
    ) -> str:
        role_model = await self._role_models.get(hypothesis.role_model_id)
        answered = await self._answers.list_for_user(hypothesis.user_id)
        q2 = next(
            (row.answer for row in answered if row.question_key == _Q2 and not row.skipped), None
        )
        outcome = await complete_validated(
            self._llm,
            "narrate_reconciliation",
            {
                "hypothesis": {
                    "version": hypothesis.version,
                    "created_at": hypothesis.created_at.date().isoformat(),
                    "review_date": hypothesis.review_date.isoformat(),
                    "drop_first": hypothesis.drop_first,
                },
                "role_model": _role_model_context(role_model),
                "comparison": comparison.model_dump(mode="json"),
                "revision_kind": revision_kind,
                "q2_answer": q2,
            },
            ReconciliationNoteOutput,
            Purpose.analyze,
            max_attempts=self._max_attempts,
        )
        note = outcome.value.note
        return "\n".join([note.summary, *note.observations, note.question])


def _role_model_context(role_model: Any) -> dict[str, str]:
    if role_model is None:
        return {"code": "", "name": "", "vision": "", "cost": ""}
    return {
        "code": role_model.code,
        "name": role_model.name,
        "vision": role_model.vision,
        "cost": role_model.cost,
    }


def _baseline(structure: dict[str, Any]) -> list[TaskSnapshotWithKey]:
    """The Schedule as first computed, read back from the Plan's own structure."""
    return [
        TaskSnapshotWithKey.model_validate(entry)
        for entry in structure.get("baseline_schedule", [])
    ]


def _shares(reports: list[Report]) -> dict[str, float]:
    return {report.dimension: float(report.metrics.get("share", 0.0)) for report in reports}
