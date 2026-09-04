"""Ports (Protocols) for the Plan Engine application layer.

Use cases depend only on these Protocols and on the ports from ``packages/*``; they never
see fastapi, sqlalchemy, arq, redis or any SDK type.
"""

from datetime import datetime
from typing import Any, Protocol

from packages.llm.ports import Purpose

__all__ = ["ClockPort", "NullRoleModelRenderer", "RoleModelRendererPort"]


class ClockPort(Protocol):
    """Current time; always timezone-aware UTC."""

    def now(self) -> datetime: ...


class RoleModelRendererPort(Protocol):
    """Turn ``role_models.content`` into a purpose-specific markdown block (PRD 12.6).

    The Role Model service owns the real implementation
    (``services/role_model/domain/renderer.py``), but services must not import each other,
    so the Plan Engine declares its own port here. The two sides are bound by the shape of
    ``role_models.content``, exactly as ``Pacing`` is duplicated in the domain layer.
    Task 29 wires an adapter that satisfies this port; until then the container injects
    ``NullRoleModelRenderer``.
    """

    def to_context(
        self,
        kind: str,
        name: str,
        content: dict[str, Any],
        purpose: Purpose,
        budget_tokens: int,
    ) -> str: ...


class NullRoleModelRenderer:
    """Default implementation: no role model context at all.

    Deliberately a full no-op rather than duck-typing onto the Role Model implementation:
    injecting ``services.role_model.domain.renderer.RoleModelRenderer`` here would break the
    "services must not import each other" contract.
    """

    def to_context(
        self,
        kind: str,
        name: str,
        content: dict[str, Any],
        purpose: Purpose,
        budget_tokens: int,
    ) -> str:
        return ""
