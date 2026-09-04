"""Candidate scoring for role model recommendation (PRD 12.5).

The SQL hard filter (``kind``/``active``/``domain:``/excluded ``constraint:``)
happens in the repo layer; this module ranks whatever survives it so the LLM
only sees the top handful of candidates.
"""

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from services.role_model.domain.content import Applicability
from services.role_model.domain.tags import parse_tag

# tag namespace -> points awarded when the candidate matches the user's signal
_GOAL_WEIGHT = 4
_METHOD_WEIGHT = 3
_LEVEL_WEIGHT = 2
_CADENCE_WEIGHT = 1
_HORIZON_WEIGHT = 1


class RoleModelRow(BaseModel):
    """One ``role_models`` row as read by the repo, before scoring."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    kind: str
    name: str
    tags: list[str] = []
    content: dict[str, Any] = {}


class UserSignals(BaseModel):
    """What the user's goal and profile imply, in tag-value terms."""

    model_config = ConfigDict(extra="forbid")

    domains: list[str] = []
    goals: list[str] = []
    methods: list[str] = []
    level: str | None = None
    cadence: str | None = None
    horizon: str | None = None
    excluded_constraints: list[str] = []


class ScoredCandidate(BaseModel):
    """A ranked candidate, trimmed down to what the recommendation prompt needs."""

    model_config = ConfigDict(extra="forbid")

    role_model_id: UUID
    name: str
    tags: list[str] = []
    summary: str = ""
    applicability: Applicability = Applicability()
    score: int


def _tag_values(tags: Sequence[str]) -> dict[str, set[str]]:
    """Group ``namespace:value`` tags into ``{namespace: {values}}``, skipping malformed ones."""
    grouped: dict[str, set[str]] = {}
    for tag in tags:
        try:
            namespace, value = parse_tag(tag)
        except ValueError:
            continue
        grouped.setdefault(namespace, set()).add(value)
    return grouped


def _score(grouped: dict[str, set[str]], signals: UserSignals) -> int:
    score = len(grouped.get("goal", set()) & set(signals.goals)) * _GOAL_WEIGHT
    score += len(grouped.get("method", set()) & set(signals.methods)) * _METHOD_WEIGHT
    for namespace, wanted, weight in (
        ("level", signals.level, _LEVEL_WEIGHT),
        ("cadence", signals.cadence, _CADENCE_WEIGHT),
        ("horizon", signals.horizon, _HORIZON_WEIGHT),
    ):
        if wanted is not None and wanted in grouped.get(namespace, set()):
            score += weight
    return score


def _applicability(content: dict[str, Any]) -> Applicability:
    sections = content.get("sections")
    raw = sections.get("applicability") if isinstance(sections, dict) else None
    if not isinstance(raw, dict):
        return Applicability()
    return Applicability.model_validate(raw)


def score_candidates(
    candidates: Sequence[RoleModelRow],
    signals: UserSignals,
    limit: int = 8,
) -> list[ScoredCandidate]:
    """Rank ``candidates`` by tag overlap with ``signals`` and return the top ``limit``.

    Candidates carrying any excluded ``constraint:`` are dropped outright; the
    rest are ordered by descending score, ties broken by name.
    """
    excluded = set(signals.excluded_constraints)
    scored: list[ScoredCandidate] = []
    for row in candidates:
        grouped = _tag_values(row.tags)
        if grouped.get("constraint", set()) & excluded:
            continue
        summary = row.content.get("summary", "")
        scored.append(
            ScoredCandidate(
                role_model_id=row.id,
                name=row.name,
                tags=list(row.tags),
                summary=summary if isinstance(summary, str) else "",
                applicability=_applicability(row.content),
                score=_score(grouped, signals),
            )
        )
    scored.sort(key=lambda c: (-c.score, c.name))
    return scored[:limit]
