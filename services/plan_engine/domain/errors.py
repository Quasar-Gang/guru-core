"""Error types for the Plan Engine domain."""


class PlanEngineDomainError(ValueError):
    """Base class for every Plan Engine domain error."""


class IllegalTransition(PlanEngineDomainError):
    """A transition the session state machine does not allow."""
