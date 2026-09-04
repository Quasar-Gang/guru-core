"""Plan session state machine (PRD 3.1)."""

from enum import StrEnum

from services.plan_engine.domain.errors import IllegalTransition


class SessionStatus(StrEnum):
    collecting = "collecting"
    evaluating = "evaluating"
    questioning = "questioning"
    generating = "generating"
    done = "done"
    failed = "failed"


TRANSITIONS: dict[SessionStatus, frozenset[SessionStatus]] = {
    SessionStatus.collecting: frozenset({SessionStatus.evaluating, SessionStatus.failed}),
    SessionStatus.evaluating: frozenset(
        {SessionStatus.questioning, SessionStatus.generating, SessionStatus.failed}
    ),
    SessionStatus.questioning: frozenset({SessionStatus.evaluating, SessionStatus.failed}),
    SessionStatus.generating: frozenset({SessionStatus.done, SessionStatus.failed}),
    SessionStatus.done: frozenset(),
    SessionStatus.failed: frozenset(),
}


def assert_transition(current: SessionStatus, target: SessionStatus) -> None:
    """Raise ``IllegalTransition`` if the move is not allowed."""
    if target not in TRANSITIONS[current]:
        raise IllegalTransition(f"cannot move session from {current} to {target}")


def is_terminal(status: SessionStatus) -> bool:
    """A terminal status has no outgoing transitions."""
    return not TRANSITIONS[status]
