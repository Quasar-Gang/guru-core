"""`direction.run` — steps 3 to 8a: read the Profile, write the Reports, score the shapes.

Two model calls, in this order and never merged. Handing a whole Profile to a model and
asking *which shape fits this person* yields one unexplainable leap. Going through Reports
first gives the Recommender intermediate, inspectable evidence to reason over — better
precision, and a verdict the user can argue with. It is also what makes the citation rule
enforceable: every evidence item points at a Report row that exists.

The two calls are separate states as well as separate prompts, because the Reports screen is
shown before any verdict exists, and because they fail for different reasons.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from packages.llm.ports import LLMPort, Purpose
from packages.llm.validation import BusinessRule, complete_validated
from packages.repo.entities import NewFitVerdict, NewReport, Report, RoleModel
from packages.repo.ports import (
    DirectionRunRepo,
    DocumentRepo,
    FitVerdictRepo,
    ImportRepo,
    ProfileRepo,
    QuestionAnswerRepo,
    ReportRepo,
    RoleModelRepo,
)
from services.engine.application.documents import load_uploads
from services.engine.application.ports import ClockPort
from services.engine.domain.dimensions import Dimension, ReportDimensionsConfig
from services.engine.domain.errors import EngineError
from services.engine.domain.profile import (
    Coverage,
    DimensionMetrics,
    ProfileSignals,
    compute_metrics,
    window,
)
from services.engine.domain.report import (
    ReadOuts,
    ReportDraft,
    ReportSet,
    ReportSetOutput,
    missing_dimensions,
)
from services.engine.domain.run import RunStatus, assert_transition
from services.engine.domain.verdict import (
    FitVerdictSetOutput,
    verdict_violations,
)

__all__ = ["RunDirection"]


class RunDirection:
    """The Station-1 pipeline, as one queue job the client polls."""

    def __init__(
        self,
        runs: DirectionRunRepo,
        profiles: ProfileRepo,
        imports: ImportRepo,
        documents: DocumentRepo,
        reports: ReportRepo,
        verdicts: FitVerdictRepo,
        role_models: RoleModelRepo,
        answers: QuestionAnswerRepo,
        llm: LLMPort,
        dimensions: ReportDimensionsConfig,
        clock: ClockPort,
        max_attempts: int,
    ) -> None:
        self._runs = runs
        self._profiles = profiles
        self._imports = imports
        self._documents = documents
        self._reports = reports
        self._verdicts = verdicts
        self._role_models = role_models
        self._answers = answers
        self._llm = llm
        self._dimensions = dimensions
        self._clock = clock
        self._max_attempts = max_attempts

    async def __call__(self, run_id: UUID) -> None:
        run = await self._runs.get_unscoped(run_id)
        if run is None:
            raise LookupError(f"unknown direction run {run_id}")
        try:
            assert_transition(RunStatus(run.status), RunStatus.analyzing)
            await self._runs.set_status(run_id, RunStatus.analyzing.value)
            stored = await self._analyze(run.user_id, run_id)

            assert_transition(RunStatus.analyzing, RunStatus.recommending)
            await self._runs.set_status(run_id, RunStatus.recommending.value)
            await self._recommend(run.user_id, run_id, stored)

            assert_transition(RunStatus.recommending, RunStatus.ready)
            await self._runs.set_status(run_id, RunStatus.ready.value)
        except Exception as exc:
            await self._fail(run_id, exc)
            raise

    # ------------------------------------------------------------------ 02 Analyzer

    async def _analyze(self, user_id: UUID, run_id: UUID) -> list[Report]:
        profile = await self._profiles.get(user_id)
        if profile is None:
            raise EngineError("no profile yet: upload something before asking for an analysis")
        coverage = Coverage.model_validate(profile.coverage)
        signals = ProfileSignals.model_validate(profile.signals or {})
        uploads = await load_uploads(self._imports, self._documents, user_id)

        today = self._clock.now().date()
        window_start, window_end = window(coverage.period_end, self._dimensions.window_weeks, today)
        metrics = compute_metrics(
            uploads.document, signals, window_start=window_start, window_end=window_end
        )
        required = self._dimensions.required(frozenset(coverage.sources))

        outcome = await complete_validated(
            self._llm,
            "create_reports",
            self._analysis_context(coverage, signals, metrics, required)
            | {"answers": await self._answers_context(user_id)},
            ReportSetOutput,
            Purpose.analyze,
            max_attempts=self._max_attempts,
            rules=[_reports_rule(required)],
            fallback=lambda _violations: ReportSetOutput(
                analysis=_bare_analysis(metrics, required)
            ),
        )
        analysis = outcome.value.analysis
        await self._runs.set_period(run_id, window_start, window_end)
        await self._runs.set_readouts(run_id, analysis.readouts.model_dump(mode="json"))
        return await self._reports.replace_for_run(
            user_id,
            run_id,
            [
                NewReport(
                    dimension=draft.dimension,
                    period_start=window_start,
                    period_end=window_end,
                    metrics=_metrics_of(metrics, draft.dimension),
                    findings=draft.model_dump(mode="json", exclude={"dimension"}),
                )
                for draft in analysis.reports
            ],
        )

    # --------------------------------------------------------------- 03 Recommender

    async def _recommend(self, user_id: UUID, run_id: UUID, reports: list[Report]) -> None:
        catalogue = await self._role_models.list(author_user_id=user_id)
        if not catalogue:
            raise EngineError("the role model catalogue is empty; seed it before running")
        dimensions = [report.dimension for report in reports]
        by_code = {model.code: model for model in catalogue}

        outcome = await complete_validated(
            self._llm,
            "score_role_models",
            {
                "reports": [
                    {
                        "dimension": report.dimension,
                        "metrics": report.metrics,
                        **report.findings,
                    }
                    for report in reports
                ],
                "readouts": (await self._readouts(run_id)),
                "role_models": [_template_context(model) for model in catalogue],
                "dimensions": dimensions,
                "answers": await self._answers_context(user_id),
            },
            FitVerdictSetOutput,
            Purpose.verdict,
            max_attempts=self._max_attempts,
            rules=[_verdicts_rule(list(by_code), dimensions)],
        )
        await self._verdicts.replace_for_run(
            user_id,
            run_id,
            [
                NewFitVerdict(
                    role_model_id=by_code[draft.role_model_code].id,
                    fit=draft.fit,
                    verdict=draft.verdict,
                    note=draft.note,
                    evidence=[item.model_dump(mode="json") for item in draft.evidence],
                    probe=draft.probe.model_dump(mode="json"),
                )
                for draft in outcome.value.recommendation.verdicts
            ],
        )

    # ---------------------------------------------------------------------- helpers

    async def _readouts(self, run_id: UUID) -> dict[str, Any]:
        run = await self._runs.get_unscoped(run_id)
        return run.readouts if run is not None else {}

    async def _answers_context(self, user_id: UUID) -> list[dict[str, str]]:
        rows = await self._answers.list_for_user(user_id)
        return [
            {"question": row.question_key, "text": row.answer} for row in rows if not row.skipped
        ]

    def _analysis_context(
        self,
        coverage: Coverage,
        signals: ProfileSignals,
        metrics: list[DimensionMetrics],
        required: list[Dimension],
    ) -> dict[str, Any]:
        return {
            "coverage": coverage.model_dump(mode="json"),
            "metrics": [row.as_dict() for row in metrics],
            "dimensions": [spec.model_dump() for spec in self._dimensions.dimensions],
            "skills": [skill.model_dump() for skill in signals.skills],
            "roles": [role.model_dump() for role in signals.roles],
            "required": list(required),
        }

    async def _fail(self, run_id: UUID, exc: Exception) -> None:
        run = await self._runs.get_unscoped(run_id)
        if run is None or run.status in (RunStatus.ready, RunStatus.failed):
            return
        await self._runs.set_status(run_id, RunStatus.failed.value, str(exc))


def _metrics_of(metrics: list[DimensionMetrics], dimension: str) -> dict[str, Any]:
    found = next((row for row in metrics if row.dimension == dimension), None)
    return found.as_dict() if found is not None else {}


def _template_context(model: RoleModel) -> dict[str, str]:
    return {
        "code": model.code,
        "name": model.name,
        "vision": model.vision,
        "five_year_path": model.five_year_path,
        "must_accumulate": model.must_accumulate,
        "cost": model.cost,
    }


def _reports_rule(required: list[Dimension]) -> BusinessRule:
    def rule(output: Any) -> list[str]:
        if not isinstance(output, ReportSetOutput):
            return []
        return missing_dimensions(output.analysis, required)

    return rule


def _verdicts_rule(codes: list[str], dimensions: list[str]) -> BusinessRule:
    def rule(output: Any) -> list[str]:
        if not isinstance(output, FitVerdictSetOutput):
            return []
        return verdict_violations(
            output.recommendation, expected_codes=codes, available_dimensions=dimensions
        )

    return rule


def _bare_analysis(metrics: list[DimensionMetrics], required: list[Dimension]) -> ReportSet:
    """The degraded path: state the numbers and say nothing more.

    A Report that only reports is still honest. What it must never do is fabricate a
    read-out, because a Fit Verdict would then cite something nobody measured.
    """
    unmeasured = "not enough data to say"
    return ReportSet(
        readouts=ReadOuts(
            trajectory=unmeasured,
            skills=[],
            continuity=unmeasured,
            voids=[],
            signals=[],
            unclassified=unmeasured,
        ),
        reports=[
            ReportDraft(
                dimension=dimension,
                headline=f"{dimension}: {_metrics_of(metrics, dimension).get('hours', 0)} hours",
                observations=[unmeasured],
            )
            for dimension in required
        ],
    )
