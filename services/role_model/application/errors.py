"""Application-layer errors for the Role Model Service.

Deliberately not shared with other services: services must not import each other, so each
one defines its own copy of these concepts and its adapter maps them to HTTP status codes.
"""


class RoleModelError(Exception):
    """Base class for Role Model Service application errors."""


class NotFound(RoleModelError):
    """The requested role model does not exist."""


class InvalidInput(RoleModelError):
    """The tags or the content payload are invalid (PRD 12.3 / 12.4)."""


class Unauthorized(RoleModelError):
    """The X-API-Key header is missing or wrong."""
