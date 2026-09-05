"""The Station-1 run state machine.

One `DirectionRun` covers steps 3-8a of the concept model: read the Profile, write the
Reports, then score every Role Model into a Fit Verdict. The two model calls are separate
states because they fail for different reasons and the client polls between them — the
Reports screen is shown before any verdict exists.
"""

from enum import StrEnum

from services.engine.domain.errors import IllegalTransition

__all__ = ["RunStatus", "TRANSITIONS", "assert_transition", "is_terminal"]


class RunStatus(StrEnum):
    pending = "pending"
    analyzing = "analyzing"
    recommending = "recommending"
    ready = "ready"
    failed = "failed"


TRANSITIONS: dict[RunStatus, frozenset[RunStatus]] = {
    RunStatus.pending: frozenset({RunStatus.analyzing, RunStatus.failed}),
    RunStatus.analyzing: frozenset({RunStatus.recommending, RunStatus.failed}),
    RunStatus.recommending: frozenset({RunStatus.ready, RunStatus.failed}),
    RunStatus.ready: frozenset(),
    RunStatus.failed: frozenset(),
}


def assert_transition(current: RunStatus, target: RunStatus) -> None:
    """Raise `IllegalTransition` if the move is not allowed."""
    if target not in TRANSITIONS[current]:
        raise IllegalTransition(f"cannot move run from {current} to {target}")


def is_terminal(status: RunStatus) -> bool:
    """A terminal status has no outgoing transitions."""
    return not TRANSITIONS[status]
