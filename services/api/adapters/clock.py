"""ClockPort 的兩個實作：正式的 SystemClock 與測試用的 FakeClock。"""

from datetime import UTC, datetime, timedelta

__all__ = ["FakeClock", "SystemClock"]


class SystemClock:
    """真實時鐘，一律回 timezone-aware UTC。"""

    def now(self) -> datetime:
        return datetime.now(UTC)


class FakeClock:
    """測試用的可控時鐘。"""

    def __init__(self, start: datetime) -> None:
        if start.tzinfo is None:
            raise ValueError("FakeClock needs a timezone-aware datetime")
        self._now = start

    def now(self) -> datetime:
        return self._now

    def advance(self, *, seconds: float = 0, days: float = 0) -> None:
        self._now += timedelta(seconds=seconds, days=days)
