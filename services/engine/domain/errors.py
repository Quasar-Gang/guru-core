"""Engine domain errors. Framework-free by contract — see `.importlinter`."""


class EngineError(RuntimeError):
    """Base class for every Engine domain failure."""


class IllegalTransition(EngineError):
    """A state machine was asked for a move it does not allow."""


class InvalidTree(EngineError):
    """A Milestone tree broke one of the two shape rules."""
