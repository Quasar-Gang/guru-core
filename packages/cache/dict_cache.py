import time
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class _Entry:
    value: str
    expires_at: float | None


class DictCache:
    """In-process cache, for tests and single-machine development only."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._data: dict[str, _Entry] = {}

    def _live_entry(self, key: str) -> _Entry | None:
        entry = self._data.get(key)
        if entry is None:
            return None
        if entry.expires_at is not None and self._clock() >= entry.expires_at:
            del self._data[key]
            return None
        return entry

    async def get(self, key: str) -> str | None:
        entry = self._live_entry(key)
        return None if entry is None else entry.value

    async def set(self, key: str, value: str, ttl_seconds: int | None = None) -> None:
        expires_at = None if ttl_seconds is None else self._clock() + ttl_seconds
        self._data[key] = _Entry(value=value, expires_at=expires_at)

    async def delete(self, key: str) -> None:
        self._data.pop(key, None)

    async def incr(self, key: str, ttl_seconds: int | None = None) -> int:
        entry = self._live_entry(key)
        if entry is None:
            expires_at = None if ttl_seconds is None else self._clock() + ttl_seconds
            self._data[key] = _Entry(value="1", expires_at=expires_at)
            return 1
        new_value = int(entry.value) + 1
        self._data[key] = _Entry(value=str(new_value), expires_at=entry.expires_at)
        return new_value
