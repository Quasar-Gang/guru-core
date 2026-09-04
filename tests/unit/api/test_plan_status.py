"""Plan lifecycle state machine (plan Task 30, PRD 3.5)."""

import pytest

from services.api.domain.errors import InvalidInput
from services.api.domain.plan_status import (
    PLAN_TRANSITIONS,
    IllegalTransition,
    PlanStatus,
    assert_plan_transition,
    parse_plan_status,
)


def test_archived_cannot_go_straight_to_draft():
    with pytest.raises(IllegalTransition):
        assert_plan_transition(PlanStatus.archived, PlanStatus.draft)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (current, target)
        for current, targets in PLAN_TRANSITIONS.items()
        for target in sorted(targets)
    ],
)
def test_every_allowed_transition_passes(current, target):
    assert_plan_transition(current, target)


def test_a_status_cannot_transition_to_itself():
    with pytest.raises(IllegalTransition):
        assert_plan_transition(PlanStatus.active, PlanStatus.active)


def test_unknown_status_is_invalid_input():
    with pytest.raises(InvalidInput):
        parse_plan_status("finished")
