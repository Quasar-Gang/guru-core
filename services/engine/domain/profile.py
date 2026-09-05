"""The Profile: what the uploaded data adds up to.

The split here is the one rule the whole pipeline follows — **numbers in code, meaning in
the model**. The model classifies: which dimension an event belongs to, which skills the
résumé keeps repeating, which roles it lists. Everything countable — hours, shares, weeks
present, streaks, coverage — is computed here, deterministically, from that classification.

A Profile is revised in place and there is exactly one per user, so re-running the build
over more uploads sharpens the same read rather than starting a second one.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, timedelta
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from packages.importers.document import DocEvent, Document
from services.engine.domain.dimensions import DIMENSIONS, Dimension

__all__ = [
    "ClassifiedEvent",
    "Coverage",
    "DimensionMetrics",
    "ProfileSignals",
    "ProfileSignalsOutput",
    "RoleTrace",
    "SkillTrace",
    "build_coverage",
    "compute_metrics",
    "window",
]

_MINUTES_PER_HOUR = 60
_DAYS_PER_WEEK = 7


class ClassifiedEvent(BaseModel):
    """One calendar event placed in a dimension by the model.

    `source_ref` points back at the `DocEvent` it came from, so the arithmetic below can
    find the event's real duration instead of trusting the model with a number.
    """

    model_config = ConfigDict(extra="forbid")

    source_ref: str
    dimension: Dimension


class SkillTrace(BaseModel):
    """A skill the résumé keeps returning to, with how many roles mention it."""

    model_config = ConfigDict(extra="forbid")

    name: str
    roles: int = Field(ge=1)


class RoleTrace(BaseModel):
    """One position on the résumé. Tenure is what makes a trajectory readable."""

    model_config = ConfigDict(extra="forbid")

    title: str
    field: str
    months: int = Field(ge=0)
    current: bool = False


class ProfileSignals(BaseModel):
    """The classification model's whole output — no counts, no judgement."""

    model_config = ConfigDict(extra="forbid")

    timezone: str = "UTC"
    events: list[ClassifiedEvent] = Field(default_factory=list)
    skills: list[SkillTrace] = Field(default_factory=list)
    roles: list[RoleTrace] = Field(default_factory=list)


class ProfileSignalsOutput(BaseModel):
    """LLM `output_schema` wrapper for the `build_profile` prompt."""

    signals: ProfileSignals


class Coverage(BaseModel):
    """What the Profile was built from. Pure arithmetic over the parsed documents."""

    model_config = ConfigDict(extra="forbid")

    sources: list[str] = Field(default_factory=list)
    events: int = 0
    text_chunks: int = 0
    period_start: date | None = None
    period_end: date | None = None
    weeks: int = 0


class DimensionMetrics(BaseModel):
    """The countable half of a Report. Never written by the model."""

    model_config = ConfigDict(extra="forbid")

    dimension: Dimension
    events: int = 0
    hours: float = 0.0
    share: float = 0.0
    weeks_present: int = 0
    longest_streak_weeks: int = 0
    last_seen: date | None = None

    def as_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


def build_coverage(document: Document, sources: Sequence[str]) -> Coverage:
    """Summarise what was uploaded: how much, from where, and over what period."""
    days = sorted(event.start_at.date() for event in document.events)
    period_start = days[0] if days else None
    period_end = days[-1] if days else None
    weeks = 0
    if period_start is not None and period_end is not None:
        weeks = (period_end - period_start).days // _DAYS_PER_WEEK + 1
    return Coverage(
        sources=sorted(set(sources)),
        events=len(document.events),
        text_chunks=len(document.text_chunks),
        period_start=period_start,
        period_end=period_end,
        weeks=weeks,
    )


def compute_metrics(
    document: Document,
    signals: ProfileSignals,
    *,
    window_start: date,
    window_end: date,
) -> list[DimensionMetrics]:
    """Count every dimension over the window. Deterministic given the same classification.

    An event the model did not classify is not dropped — it counts as `unclassified`, which
    is the whole point of keeping that column.
    """
    by_ref = {_ref(event, index): event for index, event in enumerate(document.events)}
    assigned = {item.source_ref: item.dimension for item in signals.events}
    buckets: dict[Dimension, list[DocEvent]] = {name: [] for name in DIMENSIONS}
    for ref, event in by_ref.items():
        if not window_start <= event.start_at.date() <= window_end:
            continue
        buckets[assigned.get(ref, "unclassified")].append(event)

    totals = {name: sum(_minutes(event) for event in events) for name, events in buckets.items()}
    grand_total = sum(totals.values())
    return [
        DimensionMetrics(
            dimension=name,
            events=len(buckets[name]),
            hours=round(totals[name] / _MINUTES_PER_HOUR, 1),
            share=round(totals[name] / grand_total, 4) if grand_total else 0.0,
            weeks_present=len(_weeks(buckets[name], window_start)),
            longest_streak_weeks=_longest_streak(_weeks(buckets[name], window_start)),
            last_seen=max((event.start_at.date() for event in buckets[name]), default=None),
        )
        for name in DIMENSIONS
    ]


def _ref(event: DocEvent, index: int) -> str:
    """The identity the model is given for an event, and the one it must hand back."""
    return event.source_ref or f"e{index}"


def _minutes(event: DocEvent) -> int:
    """An all-day event is not eight hours of anything; count it as zero timed minutes."""
    if event.all_day:
        return 0
    return max(0, round((event.end_at - event.start_at).total_seconds() / 60))


def _weeks(events: Sequence[DocEvent], window_start: date) -> set[int]:
    return {(event.start_at.date() - window_start).days // _DAYS_PER_WEEK for event in events}


def _longest_streak(weeks: set[int]) -> int:
    """The longest run of consecutive weeks — the shape "11 weeks unbroken" comes from here."""
    longest = 0
    current = 0
    for week in range(min(weeks, default=0), max(weeks, default=-1) + 1):
        current = current + 1 if week in weeks else 0
        longest = max(longest, current)
    return longest


def window(period_end: date | None, weeks: int, today: date) -> tuple[date, date]:
    """The fixed window a Report covers: `weeks` back from the last day with data."""
    end = period_end or today
    return end - timedelta(days=weeks * _DAYS_PER_WEEK - 1), end
