"""Two ClockPort implementations: SystemClock for production, FakeClock for tests."""

from datetime import UTC, datetime, timedelta

__all__ = ["FakeClock", "SystemClock"]


class SystemClock:
    """Real clock; always returns a timezone-aware UTC datetime."""

    def now(self) -> datetime:
        return datetime.now(UTC)


class FakeClock:
    """Controllable clock for tests."""

    def __init__(self, start: datetime) -> None:
        if start.tzinfo is None:
            raise ValueError("FakeClock needs a timezone-aware datetime")
        self._now = start

    def now(self) -> datetime:
        return self._now

    def advance(self, *, seconds: float = 0, days: float = 0) -> None:
        self._now += timedelta(seconds=seconds, days=days)
