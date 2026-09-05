"""Catalog domain errors."""


class CatalogError(RuntimeError):
    """Base class for every catalogue failure."""


class InvalidTag(CatalogError):
    """A tag broke the controlled vocabulary."""


class InvalidTemplate(CatalogError):
    """A Role Model was submitted without everything a template must state."""


class TemplateNotFound(CatalogError):
    """No Role Model with that id or code."""
