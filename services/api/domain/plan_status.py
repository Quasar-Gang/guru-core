"""The plan lifecycle state machine (PRD 3.5).

Pure Python: an enum, an explicit transition table, and the guard the use cases call
before writing a new status. No IO, no framework, no repository.
"""

from enum import StrEnum

from services.api.domain.errors import Conflict, InvalidInput

__all__ = [
    "PLAN_TRANSITIONS",
    "IllegalTransition",
    "PlanStatus",
    "assert_plan_transition",
    "parse_plan_status",
]


class IllegalTransition(Conflict):
    """The requested status change is not part of the lifecycle (PRD 3.5)."""


class PlanStatus(StrEnum):
    draft = "draft"
    active = "active"
    archived = "archived"


#: Every edge of the PRD 3.5 state diagram. A status is never a target of itself:
#: re-applying the current status is a no-op the caller should not ask for.
PLAN_TRANSITIONS: dict[PlanStatus, frozenset[PlanStatus]] = {
    PlanStatus.draft: frozenset({PlanStatus.active, PlanStatus.archived}),
    PlanStatus.active: frozenset({PlanStatus.draft, PlanStatus.archived}),
    PlanStatus.archived: frozenset({PlanStatus.active}),
}


def assert_plan_transition(current: PlanStatus, target: PlanStatus) -> None:
    """Raise `IllegalTransition` unless `current -> target` is an edge of PLAN_TRANSITIONS."""
    if target not in PLAN_TRANSITIONS[current]:
        raise IllegalTransition(f"a plan cannot go from {current.value} to {target.value}")


def parse_plan_status(value: str) -> PlanStatus:
    """Turn an untrusted string into a `PlanStatus`, or raise `InvalidInput`."""
    try:
        return PlanStatus(value)
    except ValueError:
        raise InvalidInput(f"unknown plan status: {value}") from None
