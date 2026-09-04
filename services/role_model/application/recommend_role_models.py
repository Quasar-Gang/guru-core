"""Recommend up to three persona role models for one user (PRD 3.9 / 12.5).

This is the only LLM call the Role Model Service makes. The pipeline is: a SQL hard
filter (persona + active + ``domain:`` tags), then program-side scoring, then one LLM
call that ranks the survivors. Traits never take part: users pick those themselves.
"""

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from packages.llm.ports import LLMPort, Purpose
from packages.llm.validation import BusinessRule, complete_validated
from packages.repo import RoleModelRepo
from services.role_model.domain import (
    RoleModelRenderer,
    RoleModelRow,
    ScoredCandidate,
    UserSignals,
    score_candidates,
)

__all__ = [
    "RecommendInput",
    "RecommendOutput",
    "RecommendRoleModels",
    "Recommendation",
]

PROMPT_NAME = "recommend_role_model"
MAX_RECOMMENDATIONS = 3

#: Reason attached to a degraded (LLM-less) recommendation. User-facing product copy, so
#: it stays in the product language, like the rendered role model blocks (PRD 12.6).
FALLBACK_REASON = "依你的目標與節奏偏好，這張角色卡的契合度分數最高。"


class RecommendInput(BaseModel):
    """What the API service knows about the user when it asks for a recommendation."""

    model_config = ConfigDict(extra="forbid")

    goal: str
    intake: dict[str, Any] = {}
    profile_answers: dict[str, Any] = {}
    domains: list[str] = []
    """``domain:`` tag values; when empty the LLM infers the domain from the goal."""
    excluded_constraints: list[str] = []
    """``constraint:`` tag values the user does not meet; those candidates are dropped."""


class Recommendation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role_model_id: UUID
    name: str
    reason: str = Field(max_length=120)


class RecommendOutput(BaseModel):
    """The LLM output schema; the length cap is part of the contract, not a business rule."""

    model_config = ConfigDict(extra="forbid")

    recommendations: list[Recommendation] = Field(default=[], max_length=MAX_RECOMMENDATIONS)


class RecommendRoleModels:
    SQL_LIMIT = 30
    SCORE_LIMIT = 8

    def __init__(
        self,
        repo: RoleModelRepo,
        llm: LLMPort,
        renderer: RoleModelRenderer,
        max_attempts: int,
    ) -> None:
        self._repo = repo
        self._llm = llm
        # Part of the published constructor signature so the container wiring stays stable.
        # Candidates reach the prompt already flattened by `score_candidates`, so nothing
        # here needs the markdown rendering the Plan Engine relies on.
        self._renderer = renderer
        self._max_attempts = max_attempts

    async def __call__(self, payload: RecommendInput) -> list[Recommendation]:
        candidates = await self._candidates(payload)
        if not candidates:
            return []
        allowed = {candidate.role_model_id for candidate in candidates}
        rules: list[BusinessRule] = [_ids_must_be_in_candidates(allowed), _no_duplicates]
        outcome = await complete_validated(
            self._llm,
            PROMPT_NAME,
            _context(payload, candidates),
            RecommendOutput,
            Purpose.recommend,
            max_attempts=self._max_attempts,
            rules=rules,
            fallback=lambda _violations: _top_scored(candidates),
        )
        return list(outcome.value.recommendations)

    async def _candidates(self, payload: RecommendInput) -> list[ScoredCandidate]:
        domain_tags = [f"domain:{value}" for value in payload.domains]
        rows = await self._repo.list(
            kind="persona",
            tags_any=domain_tags or None,
            tags_all=None,
            active_only=True,
            limit=self.SQL_LIMIT,
        )
        return score_candidates(
            [
                RoleModelRow(
                    id=row.id,
                    kind=row.kind,
                    name=row.name,
                    tags=list(row.tags),
                    content=dict(row.content),
                )
                for row in rows
            ],
            _signals(payload),
            limit=self.SCORE_LIMIT,
        )


def _as_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str)]
    return []


def _as_value(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _signals(payload: RecommendInput) -> UserSignals:
    """Read the tag-shaped answers out of the profile and the session intake."""
    answers: dict[str, Any] = {**payload.profile_answers, **payload.intake}
    return UserSignals(
        domains=list(payload.domains),
        goals=_as_list(answers.get("goals")),
        methods=_as_list(answers.get("methods")),
        level=_as_value(answers.get("level")),
        cadence=_as_value(answers.get("cadence")),
        horizon=_as_value(answers.get("horizon")),
        excluded_constraints=list(payload.excluded_constraints),
    )


def _profile_summary(answers: dict[str, Any]) -> str:
    return "\n".join(f"{key}: {value}" for key, value in sorted(answers.items()))


def _context(payload: RecommendInput, candidates: Sequence[ScoredCandidate]) -> dict[str, Any]:
    """The jinja variables `packages/llm/prompts/recommend_role_model.md` expects."""
    return {
        "goal": payload.goal,
        "intake": payload.intake,
        "profile_summary": _profile_summary(payload.profile_answers),
        "candidates": [
            {
                "id": str(candidate.role_model_id),
                "name": candidate.name,
                "tags": list(candidate.tags),
                "summary": candidate.summary,
                "applicability": candidate.applicability.model_dump(),
            }
            for candidate in candidates
        ],
        "max_recommendations": MAX_RECOMMENDATIONS,
    }


def _ids_must_be_in_candidates(allowed: set[UUID]) -> BusinessRule:
    def rule(output: Any) -> list[str]:
        return [
            f"role_model_id {item.role_model_id} is not in the candidate list"
            for item in output.recommendations
            if item.role_model_id not in allowed
        ]

    return rule


def _no_duplicates(output: Any) -> list[str]:
    ids = [item.role_model_id for item in output.recommendations]
    if len(set(ids)) == len(ids):
        return []
    return ["the same role model was recommended more than once"]


def _top_scored(candidates: Sequence[ScoredCandidate]) -> RecommendOutput:
    """Degraded answer: the highest scoring candidates with a canned reason (PRD 7.5)."""
    return RecommendOutput(
        recommendations=[
            Recommendation(
                role_model_id=candidate.role_model_id,
                name=candidate.name,
                reason=FALLBACK_REASON,
            )
            for candidate in candidates[:MAX_RECOMMENDATIONS]
        ]
    )
