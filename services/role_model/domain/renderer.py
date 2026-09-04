"""Render a role model into a markdown context block for the Plan Engine (PRD 12.6).

The Plan Engine never sees the raw JSON: it asks for the blocks that matter for
one ``Purpose`` and one token budget. Block order is fixed; when the budget is
exceeded whole blocks are dropped from the tail, never mid-sentence. The
rendered string is what lands in ``plan_sessions.context_snapshot``, so it must
be reproducible from ``content`` alone.
"""

from typing import Any

from pydantic import ValidationError

from packages.llm.ports import Purpose
from services.role_model.domain.content import Pacing, PersonaSections

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


def _section(heading: str, body: str) -> str:
    return f"## {heading}\n{body}" if body else ""


def _bullets(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items)


class RoleModelRenderer:
    """Turn ``role_models.content`` into a purpose-specific markdown block."""

    def to_context(
        self,
        kind: str,
        name: str,
        content: dict[str, Any],
        purpose: Purpose,
        budget_tokens: int,
    ) -> str:
        # ``name`` is part of the port signature but is deliberately not rendered:
        # the prompt already names the role model, and a title line would eat into
        # the (tight) evaluate budget.
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
        try:
            sections = PersonaSections.model_validate(raw if isinstance(raw, dict) else {})
        except ValidationError:
            sections = PersonaSections()
        summary = content.get("summary")
        summary = summary if isinstance(summary, str) else ""

        if purpose is Purpose.evaluate:
            applicability = sections.applicability
            lines = []
            if applicability.good_for:
                lines.append(f"適合：{'、'.join(applicability.good_for)}")
            if applicability.not_for:
                lines.append(f"不適合：{'、'.join(applicability.not_for)}")
            return [summary, _section("適用性", "\n".join(lines))]
        if purpose is Purpose.revise:
            return [
                _section("常見失敗點", _bullets(sections.pitfalls)),
                _section("每週結構", sections.weekly_structure),
            ]
        return [
            _section("原則", _bullets(sections.principles)),
            _section("每週結構", sections.weekly_structure),
            _section("進度指標", _bullets(sections.progress_metrics)),
            _section("常見失敗點", _bullets(sections.pitfalls)),
            _section("里程碑範例", _bullets(sections.example_milestones)),
        ]


class NullRoleModelRenderer:
    """Placeholder for callers that have no role model attached yet."""

    def to_context(self, *args: Any, **kwargs: Any) -> str:
        return ""


def _fit(blocks: list[str], budget_tokens: int) -> str:
    """Join non-empty blocks, dropping whole blocks from the tail until they fit.

    A single block that is still over budget is returned as-is — a truncated
    sentence would be worse than a slightly oversized one.
    """
    kept = [block for block in blocks if block]
    while len(kept) > 1 and estimate_tokens(_BLOCK_SEPARATOR.join(kept)) > budget_tokens:
        kept.pop()
    return _BLOCK_SEPARATOR.join(kept)
