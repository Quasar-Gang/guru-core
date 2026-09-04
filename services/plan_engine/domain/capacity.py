"""使用者可用時段與既有行程（PRD 4.3.2 的 scheduler 輸入）。

``Capacity`` 是「每個星期幾的哪些 slot 有哪些可用區間」，區間用「自當地 00:00
起算的分鐘數」表示，因此與日期、時區無關——時區只記在 ``Capacity.timezone``，
由 scheduler 在展開成絕對時間時才套用。``BusyBlock`` 則相反，它來自既有行事曆
或匯入文件，本來就是絕對時間，一律 timezone-aware UTC。
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from services.plan_engine.domain.template import SlotHint

__all__ = ["MINUTES_PER_DAY", "BusyBlock", "Capacity", "TimeWindow"]

MINUTES_PER_DAY = 24 * 60
_DAYS_PER_WEEK = 7

_DEFAULT_WINDOWS: dict[SlotHint, tuple[int, int]] = {
    "morning": (7 * 60, 9 * 60),  # 07:00–09:00
    "noon": (12 * 60, 13 * 60),  # 12:00–13:00
    "evening": (19 * 60, 22 * 60),  # 19:00–22:00
}


class TimeWindow(BaseModel):
    """當地一日之內的可用區間，以自 00:00 起算的分鐘數表示。"""

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
    """使用者每週的可用時段。

    ``slots`` 的 key 是 ``date.weekday()``（0=Mon … 6=Sun），value 是該日每個
    slot 的可用區間清單。沒設定的 weekday / slot 一律視為「沒有空檔」。
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
        """該 weekday / slot 的可用區間，依 ``start_minute`` 遞增；沒設定回空 list。"""
        return sorted(
            self.slots.get(weekday, {}).get(slot, []),
            key=lambda window: (window.start_minute, window.end_minute),
        )

    @classmethod
    def default(cls, timezone: str) -> Capacity:
        """七天皆 morning 07:00–09:00、noon 12:00–13:00、evening 19:00–22:00。"""

        def day() -> dict[SlotHint, list[TimeWindow]]:
            return {
                slot: [TimeWindow(start_minute=start, end_minute=end)]
                for slot, (start, end) in _DEFAULT_WINDOWS.items()
            }

        return cls(
            timezone=timezone,
            slots={weekday: day() for weekday in range(_DAYS_PER_WEEK)},
        )


class BusyBlock(BaseModel):
    """既有行程佔用的絕對時間區段（UTC aware）。"""

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
