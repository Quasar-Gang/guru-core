"""Error types for the API service domain.

Plain Python with no knowledge of HTTP. The mapping to HTTP statuses lives in
`services/api/adapters/http/app.py` (`STATUS_BY_ERROR`).
"""

__all__ = [
    "Conflict",
    "DomainError",
    "Forbidden",
    "InvalidInput",
    "NotFound",
    "ReauthRequired",
    "Unauthorized",
]


class DomainError(Exception):
    """Base class for every API domain error."""


class NotFound(DomainError):
    """The requested resource does not exist, or does not belong to this user."""


class Forbidden(DomainError):
    """The user is authenticated but not allowed to perform this action."""


class Conflict(DomainError):
    """Conflicts with the current state: a duplicate create, or a disallowed state transition."""


class InvalidInput(DomainError):
    """The input is invalid."""


class Unauthorized(DomainError):
    """Missing or invalid credentials."""


class ReauthRequired(DomainError):
    """A third-party authorization has expired; the user must reconnect."""
