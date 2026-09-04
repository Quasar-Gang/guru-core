"""Plan session 狀態機。"""

import pytest

from services.plan_engine.domain import (
    TRANSITIONS,
    IllegalTransition,
    SessionStatus,
    assert_transition,
    is_terminal,
)


def test_legal_transition_passes() -> None:
    assert_transition(SessionStatus.evaluating, SessionStatus.questioning)


def test_illegal_transition_raises() -> None:
    with pytest.raises(IllegalTransition):
        assert_transition(SessionStatus.done, SessionStatus.evaluating)


def test_every_status_has_transition_entry() -> None:
    assert set(TRANSITIONS) == set(SessionStatus)


def test_terminal_states() -> None:
    assert is_terminal(SessionStatus.done)
    assert is_terminal(SessionStatus.failed)
    assert not is_terminal(SessionStatus.collecting)
    assert not is_terminal(SessionStatus.evaluating)
    assert not is_terminal(SessionStatus.questioning)
    assert not is_terminal(SessionStatus.generating)


def test_illegal_transition_is_value_error() -> None:
    assert issubclass(IllegalTransition, ValueError)


def test_self_transition_rejected() -> None:
    with pytest.raises(IllegalTransition):
        assert_transition(SessionStatus.collecting, SessionStatus.collecting)


def test_all_transition_targets_are_valid_statuses() -> None:
    for targets in TRANSITIONS.values():
        assert targets <= set(SessionStatus)


def test_every_non_terminal_can_fail() -> None:
    for status in SessionStatus:
        if not is_terminal(status):
            assert_transition(status, SessionStatus.failed)
