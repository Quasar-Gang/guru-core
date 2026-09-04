"""Candidate scoring for role model recommendation (PRD 12.5)."""

from typing import Any
from uuid import UUID, uuid4

from services.role_model.domain import (
    RoleModelRow,
    ScoredCandidate,
    UserSignals,
    score_candidates,
)


def _row(
    name: str = "candidate",
    tags: list[str] | None = None,
    content: dict[str, Any] | None = None,
    row_id: UUID | None = None,
) -> RoleModelRow:
    return RoleModelRow(
        id=row_id or uuid4(),
        kind="persona",
        name=name,
        tags=tags or [],
        content=content or {"summary": "a summary"},
    )


def test_goal_hit_scores_higher_than_method_hit():
    goal_row = _row(name="goal", tags=["domain:fitness", "goal:endurance"])
    method_row = _row(name="method", tags=["domain:fitness", "method:80-20"])
    signals = UserSignals(domains=["fitness"], goals=["endurance"], methods=["80-20"])

    out = score_candidates([method_row, goal_row], signals)

    assert [c.name for c in out] == ["goal", "method"]
    assert out[0].score == 4
    assert out[1].score == 3


def test_level_cadence_and_horizon_add_to_the_score():
    row = _row(
        tags=[
            "domain:fitness",
            "goal:endurance",
            "level:intermediate",
            "cadence:5x-week",
            "horizon:months",
        ]
    )
    signals = UserSignals(
        goals=["endurance"], level="intermediate", cadence="5x-week", horizon="months"
    )

    out = score_candidates([row], signals)

    assert out[0].score == 4 + 2 + 1 + 1


def test_excluded_constraint_removes_candidate():
    out = score_candidates(
        [_row(tags=["domain:fitness", "goal:x", "constraint:no-gym"])],
        UserSignals(domains=["fitness"], excluded_constraints=["no-gym"]),
    )

    assert out == []


def test_limit_is_respected():
    rows = [_row(name=f"c{i}", tags=["goal:endurance"]) for i in range(10)]

    out = score_candidates(rows, UserSignals(goals=["endurance"]), limit=3)

    assert len(out) == 3


def test_ties_broken_by_name():
    rows = [
        _row(name="bravo", tags=["goal:endurance"]),
        _row(name="alpha", tags=["goal:endurance"]),
        _row(name="charlie", tags=["goal:endurance"]),
    ]

    out = score_candidates(rows, UserSignals(goals=["endurance"]))

    assert [c.name for c in out] == sorted(["alpha", "bravo", "charlie"])


def test_scored_candidate_carries_summary_and_applicability():
    row = _row(
        tags=["goal:endurance"],
        content={
            "summary": "Eighty percent of training volume at an easy pace.",
            "sections": {
                "applicability": {
                    "good_for": ["first-time marathoners"],
                    "not_for": ["runners carrying an injury"],
                }
            },
        },
    )

    out = score_candidates([row], UserSignals(goals=["endurance"]))

    assert isinstance(out[0], ScoredCandidate)
    assert out[0].role_model_id == row.id
    assert out[0].summary == "Eighty percent of training volume at an easy pace."
    assert out[0].applicability.good_for == ["first-time marathoners"]
    assert out[0].applicability.not_for == ["runners carrying an injury"]


def test_zero_score_candidates_are_kept():
    out = score_candidates([_row(tags=["domain:fitness"])], UserSignals(domains=["fitness"]))

    assert [c.score for c in out] == [0]
