"""The Analyzer's output: one Report per dimension, plus the six read-outs.

The Analyzer is a separate step and the Recommender never sees the raw Profile. Going
through Reports first gives the Recommender intermediate, inspectable evidence to reason
over, and it is what makes the Fit Verdict's citation rule enforceable: every evidence item
points at a Report that exists.

The model writes only the meaning. The numbers come from `profile.compute_metrics` and are
attached to the Report afterwards, so no read-out can quietly disagree with the arithmetic.
"""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict, Field

from services.engine.domain.dimensions import Dimension

__all__ = [
    "ReadOuts",
    "ReportDraft",
    "ReportSet",
    "ReportSetOutput",
    "missing_dimensions",
]

_MAX_OBSERVATIONS = 5


class ReportDraft(BaseModel):
    """What the Analyzer says about one dimension. No score, no advice."""

    model_config = ConfigDict(extra="forbid")

    dimension: Dimension
    headline: str = Field(min_length=1, max_length=200)
    observations: list[str] = Field(min_length=1, max_length=_MAX_OBSERVATIONS)
    voids: list[str] = Field(default_factory=list, max_length=_MAX_OBSERVATIONS)
    signals: list[str] = Field(default_factory=list, max_length=_MAX_OBSERVATIONS)


class ReadOuts(BaseModel):
    """The six things that come off the Reports once they are all in front of you."""

    model_config = ConfigDict(extra="forbid")

    trajectory: str = Field(min_length=1)
    skills: list[str] = Field(default_factory=list)
    continuity: str = Field(min_length=1)
    voids: list[str] = Field(default_factory=list)
    signals: list[str] = Field(default_factory=list)
    unclassified: str = Field(min_length=1)


class ReportSet(BaseModel):
    """Every dimension in one model call — they are read against each other, not alone."""

    model_config = ConfigDict(extra="forbid")

    readouts: ReadOuts
    reports: list[ReportDraft] = Field(min_length=1)


class ReportSetOutput(BaseModel):
    """LLM `output_schema` wrapper for the `create_reports` prompt."""

    analysis: ReportSet


def missing_dimensions(analysis: ReportSet, required: Sequence[Dimension]) -> list[str]:
    """Which required dimensions the model skipped, phrased as violations for the retry."""
    produced = {report.dimension for report in analysis.reports}
    duplicates = len(analysis.reports) - len(produced)
    violations = [
        f"a report for the '{dimension}' dimension is required"
        for dimension in required
        if dimension not in produced
    ]
    if duplicates:
        violations.append("each dimension may appear at most once in reports[]")
    return violations
