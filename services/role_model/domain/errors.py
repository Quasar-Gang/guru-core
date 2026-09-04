"""Domain errors for the role model service."""


class InvalidTag(ValueError):
    """A tag violates the vocabulary rules (PRD 12.3)."""


class InvalidContent(ValueError):
    """A ``content`` payload does not match its ``kind`` schema (PRD 12.4)."""
