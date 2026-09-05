"""Capacity: the room the user actually has, observed rather than declared.

`Capacity` describes which windows are free in each slot of each weekday. Windows are
minutes from local midnight, so they carry no date and no timezone — the timezone is kept
in `Capacity.timezone` and only applied when the scheduler expands them into absolute
times. `BusyBlock` is the opposite: it comes from a calendar the user already keeps, so it
is already absolute and always timezone-aware UTC.

Capacity is not the Quota, and the two must never be merged. Capacity is a Report
dimension: it says what is physically possible. The Quota is declared by Q-3: it says what
the user has agreed to allow, and what gets cut first when the two disagree.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from services.engine.domain.plan_template import SlotHint

__all__ = ["MINUTES_PER_DAY", "BusyBlock", "Capacity", "TimeWindow"]

MINUTES_PER_DAY = 24 * 60
_DAYS_PER_WEEK = 7

_DEFAULT_WINDOWS: dict[SlotHint, tuple[int, int]] = {
    "morning": (7 * 60, 9 * 60),  # 07:00-09:00
    "noon": (12 * 60, 13 * 60),  # 12:00-13:00
    "evening": (19 * 60, 22 * 60),  # 19:00-22:00
}


class TimeWindow(BaseModel):
    """A free window within one local day, as minutes from local midnight."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    start_minute: int = Field(ge=0, le=MINUTES_PER_DAY)
    end_minute: int = Field(ge=0, le=MINUTES_PER_DAY)

    @model_validator(mode="after")
    def end_after_start(self) -> TimeWindow:
        if self.end_minute <= self.start_minute:
            raise ValueError(
                f"end_minute {self.end_minute} must be greater than "
                f"start_minute {self.start_minute}"
            )
        return self

    @property
    def length_minutes(self) -> int:
        return self.end_minute - self.start_minute


class Capacity(BaseModel):
    """A user's weekly availability.

    Keys of `slots` are `date.weekday()` values (0=Mon ... 6=Sun); each value maps a slot to
    the free windows of that day. A weekday or slot that is absent means no availability.
    """

    model_config = ConfigDict(extra="forbid")

    timezone: str = "UTC"
    slots: dict[int, dict[SlotHint, list[TimeWindow]]] = {}

    @field_validator("slots")
    @classmethod
    def weekdays_in_range(
        cls, value: dict[int, dict[SlotHint, list[TimeWindow]]]
    ) -> dict[int, dict[SlotHint, list[TimeWindow]]]:
        for weekday in value:
            if not 0 <= weekday < _DAYS_PER_WEEK:
                raise ValueError(f"weekday must be 0..6, got {weekday}")
        return value

    def windows(self, weekday: int, slot: SlotHint) -> list[TimeWindow]:
        """Free windows for that weekday and slot, sorted by `start_minute`; empty if unset."""
        return sorted(
            self.slots.get(weekday, {}).get(slot, []),
            key=lambda window: (window.start_minute, window.end_minute),
        )

    @classmethod
    def default(cls, timezone: str) -> Capacity:
        """Every day: morning 07:00-09:00, noon 12:00-13:00, evening 19:00-22:00."""

        def day() -> dict[SlotHint, list[TimeWindow]]:
            return {
                slot: [TimeWindow(start_minute=start, end_minute=end)]
                for slot, (start, end) in _DEFAULT_WINDOWS.items()
            }

        return cls(timezone=timezone, slots={weekday: day() for weekday in range(_DAYS_PER_WEEK)})


class BusyBlock(BaseModel):
    """An absolute time range taken by an existing commitment (UTC-aware)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    start_at: datetime
    end_at: datetime

    @model_validator(mode="after")
    def aware_and_ordered(self) -> BusyBlock:
        if self.start_at.tzinfo is None or self.end_at.tzinfo is None:
            raise ValueError("BusyBlock times must be timezone-aware")
        if self.end_at <= self.start_at:
            raise ValueError("BusyBlock end_at must be after start_at")
        return self
