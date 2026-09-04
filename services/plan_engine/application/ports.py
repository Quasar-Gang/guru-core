"""Ports (Protocols) for the Plan Engine application layer.

Use cases depend only on these Protocols and on the ports from ``packages/*``; they never
see fastapi, sqlalchemy, arq, redis or any SDK type.
"""

from datetime import datetime
from typing import Any, Protocol

from pydantic import ValidationError

from packages.llm.ports import Purpose
from services.plan_engine.domain.difficulty import Pacing

__all__ = [
    "ClockPort",
    "MarkdownRoleModelRenderer",
    "NullRoleModelRenderer",
    "RoleModelRendererPort",
]


class ClockPort(Protocol):
    """Current time; always timezone-aware UTC."""

    def now(self) -> datetime: ...


class RoleModelRendererPort(Protocol):
    """Turn ``role_models.content`` into a purpose-specific markdown block (PRD 12.6).

    The Role Model service owns the real implementation
    (``services/role_model/domain/renderer.py``), but services must not import each other,
    so the Plan Engine declares its own port here. The two sides are bound by the shape of
    ``role_models.content``, exactly as ``Pacing`` is duplicated in the domain layer.
    ``MarkdownRoleModelRenderer`` below is this side's implementation; the Role Model
    service ships a same-shaped one it uses to preview blocks. Change one, change the other.
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


# --- MarkdownRoleModelRenderer (PRD 12.6) ---------------------------------------------
#
# Deliberate duplicate of ``services/role_model/domain/renderer.py``, for the same reason
# ``Pacing`` is duplicated in ``domain/difficulty.py``: the two services must not import
# each other, so they meet at the JSON in ``role_models.content``. Rendering here also
# keeps the snapshot in ``plan_sessions.context_snapshot`` reproducible from this service
# alone, with no call to another service at generation time.

_BLOCK_SEPARATOR = "\n\n"

_MISSED_POLICY_TEXT = {
    "none": "不補",
    "same-week": "在同週補一次",
    "next-day": "隔日補",
}

_INTENSITY_TEXT = {"low": "低", "medium": "中等", "high": "高"}


def estimate_tokens(text: str) -> int:
    """Rough token count. Chinese runs about two characters per token."""
    return len(text) // 2


def _percent(rate: float) -> str:
    """``0.10`` -> ``"10"``, ``0.05`` -> ``"5"`` — no trailing zeros, no float noise."""
    return f"{rate * 100:.6g}"


def _pacing_sentence(pacing: Pacing) -> str:
    low_sessions, high_sessions = pacing.sessions_per_week
    low_minutes, high_minutes = pacing.session_minutes
    return (
        f"節奏約束：每週 {low_sessions}–{high_sessions} 次，"
        f"每次 {low_minutes}–{high_minutes} 分鐘，"
        f"至少休息 {pacing.rest_days_min} 天；"
        f"每兩週增量不超過 {_percent(pacing.progression_rate)}%；"
        f"漏做的任務{_MISSED_POLICY_TEXT[pacing.missed_policy]}；"
        f"預設強度{_INTENSITY_TEXT[pacing.intensity_bias]}。"
    )


def _revise_pacing_sentence(pacing: Pacing) -> str:
    return (
        f"節奏約束：每兩週增量不超過 {_percent(pacing.progression_rate)}%；"
        f"漏做的任務{_MISSED_POLICY_TEXT[pacing.missed_policy]}。"
    )


def _text(sections: dict[str, Any], key: str) -> str:
    value = sections.get(key)
    return value if isinstance(value, str) else ""


def _items(sections: dict[str, Any], key: str) -> list[str]:
    value = sections.get(key)
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _section(heading: str, body: str) -> str:
    return f"## {heading}\n{body}" if body else ""


def _bullets(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items)


def _fit(blocks: list[str], budget_tokens: int) -> str:
    """Join non-empty blocks, dropping whole blocks from the tail until they fit.

    A single block that is still over budget is returned as-is — a truncated sentence
    would be worse than a slightly oversized one.
    """
    kept = [block for block in blocks if block]
    while len(kept) > 1 and estimate_tokens(_BLOCK_SEPARATOR.join(kept)) > budget_tokens:
        kept.pop()
    return _BLOCK_SEPARATOR.join(kept)


class MarkdownRoleModelRenderer:
    """Turn ``role_models.content`` into the markdown block one purpose needs (PRD 12.6)."""

    def to_context(
        self,
        kind: str,
        name: str,
        content: dict[str, Any],
        purpose: Purpose,
        budget_tokens: int,
    ) -> str:
        # ``name`` is part of the port signature but is deliberately not rendered: the
        # prompt already names the role model, and a title line would eat into the budget.
        if kind == "trait":
            blocks = self._trait_blocks(content, purpose)
        elif kind == "persona":
            blocks = self._persona_blocks(content, purpose)
        else:
            blocks = []
        return _fit(blocks, budget_tokens)

    def _trait_blocks(self, content: dict[str, Any], purpose: Purpose) -> list[str]:
        raw = content.get("pacing")
        if not isinstance(raw, dict):
            return []
        try:
            pacing = Pacing.model_validate(raw)
        except ValidationError:
            return []
        if purpose is Purpose.evaluate:
            return [f"預設強度{_INTENSITY_TEXT[pacing.intensity_bias]}。"]
        if purpose is Purpose.revise:
            return [_revise_pacing_sentence(pacing)]
        return [_pacing_sentence(pacing)]

    def _persona_blocks(self, content: dict[str, Any], purpose: Purpose) -> list[str]:
        raw = content.get("sections")
        sections: dict[str, Any] = raw if isinstance(raw, dict) else {}
        summary = content.get("summary")
        summary = summary if isinstance(summary, str) else ""

        if purpose is Purpose.evaluate:
            raw_applicability = sections.get("applicability")
            applicability = raw_applicability if isinstance(raw_applicability, dict) else {}
            lines = []
            if _items(applicability, "good_for"):
                lines.append(f"適合：{'、'.join(_items(applicability, 'good_for'))}")
            if _items(applicability, "not_for"):
                lines.append(f"不適合：{'、'.join(_items(applicability, 'not_for'))}")
            return [summary, _section("適用性", "\n".join(lines))]
        if purpose is Purpose.revise:
            return [
                _section("常見失敗點", _bullets(_items(sections, "pitfalls"))),
                _section("每週結構", _text(sections, "weekly_structure")),
            ]
        return [
            _section("原則", _bullets(_items(sections, "principles"))),
            _section("每週結構", _text(sections, "weekly_structure")),
            _section("進度指標", _bullets(_items(sections, "progress_metrics"))),
            _section("常見失敗點", _bullets(_items(sections, "pitfalls"))),
            _section("里程碑範例", _bullets(_items(sections, "example_milestones"))),
        ]
