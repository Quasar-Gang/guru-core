"""The Fit Verdict: one Role Model held against one user's evidence.

Four invariants live here, and all four are enforced as LLM business rules rather than
documented as hopes:

1. exactly five evidence items;
2. at least one `for` and at least one `against` — a verdict that only agrees with the user
   is a compliment, not a diagnosis;
3. every item cites a Report that this run actually produced. An uncited claim is not
   evidence, and an uncited verdict cannot be argued with, which would defeat the reason
   for having Reports at all;
4. every verdict carries exactly one Probe, and the Probe states its own cost.

Note what the five items are *not*: a score. Even the best-fitting shape gets items against
it, and the worst-fitting gets items for it. The verdict is designed to be argued with.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from services.engine.domain.dimensions import Dimension

__all__ = [
    "EVIDENCE_ITEMS",
    "Citation",
    "Evidence",
    "Fit",
    "FitVerdictDraft",
    "FitVerdictSet",
    "FitVerdictSetOutput",
    "Probe",
    "Stance",
    "verdict_violations",
]

#: Exactly five. Fewer reads as a summary, more reads as a report card.
EVIDENCE_ITEMS = 5

Stance = Literal["for", "against"]

Fit = Literal[
    "strongly_consistent",
    "partly_consistent",
    "moderate_gap",
    "large_gap",
    "largest_gap",
    "runs_opposite",
]


class Citation(BaseModel):
    """Where an evidence item got its fact. `dimension` must name a Report from this run."""

    model_config = ConfigDict(extra="forbid")

    dimension: Dimension
    fact: str = Field(min_length=1, max_length=200)


class Evidence(BaseModel):
    """One of the five items. Marked for or against, and always sourced."""

    model_config = ConfigDict(extra="forbid")

    stance: Stance
    text: str = Field(min_length=1, max_length=400)
    cites: Citation


class Probe(BaseModel):
    """The one cheap test attached to this verdict, sized to a single quarter.

    `cost` is required for the same reason a Role Model's is: a test whose price is unstated
    is a test nobody runs. A test whose failure is survivable is a test that gets run — that
    is the entire selection criterion.
    """

    model_config = ConfigDict(extra="forbid")

    statement: str = Field(min_length=1, max_length=400)
    cost: str = Field(min_length=1, max_length=200)


class FitVerdictDraft(BaseModel):
    """The Recommender's output for one Role Model, keyed by the template's code."""

    model_config = ConfigDict(extra="forbid")

    role_model_code: str = Field(min_length=1, max_length=16)
    fit: Fit
    verdict: str = Field(min_length=1, max_length=300)
    note: str = Field(min_length=1)
    evidence: list[Evidence]
    probe: Probe


class FitVerdictSet(BaseModel):
    """Every Role Model scored in one call. The Recommender never narrows to one."""

    model_config = ConfigDict(extra="forbid")

    verdicts: list[FitVerdictDraft] = Field(min_length=1)


class FitVerdictSetOutput(BaseModel):
    """LLM `output_schema` wrapper for the `score_role_models` prompt."""

    recommendation: FitVerdictSet


def verdict_violations(
    recommendation: FitVerdictSet,
    *,
    expected_codes: Sequence[str],
    available_dimensions: Sequence[str],
) -> list[str]:
    """Check the four invariants and phrase each breach for the retry.

    Returned messages are fed straight back to the model as `_violations`, so they name the
    verdict they belong to and say what a correct answer looks like.
    """
    dimensions = set(available_dimensions)
    scored = [draft.role_model_code for draft in recommendation.verdicts]
    violations = [
        f"a verdict for role model {code!r} is required"
        for code in expected_codes
        if code not in scored
    ]
    violations += [
        f"role model {code!r} is not in the catalogue for this user"
        for code in scored
        if code not in set(expected_codes)
    ]
    if len(scored) != len(set(scored)):
        violations.append("each role model may be scored at most once")

    for draft in recommendation.verdicts:
        prefix = f"verdict for {draft.role_model_code!r}"
        if len(draft.evidence) != EVIDENCE_ITEMS:
            violations.append(
                f"{prefix} has {len(draft.evidence)} evidence items, "
                f"and must have exactly {EVIDENCE_ITEMS}"
            )
        stances = {item.stance for item in draft.evidence}
        if "for" not in stances or "against" not in stances:
            violations.append(
                f"{prefix} must carry at least one 'for' and at least one 'against' item"
            )
        violations += [
            f"{prefix} cites the '{item.cites.dimension}' dimension, "
            "which has no report in this run"
            for item in draft.evidence
            if item.cites.dimension not in dimensions
        ]
    return violations
