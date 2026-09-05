"""In-process concurrency gate shared by the provider adapters.

A local runtime serves one set of weights from one pool of memory, so two
generations at once do not go twice as fast — they contend for the same KV cache
and can push a laptop into swap. A hosted provider has the opposite property, so
the cap is opt-in: `concurrency: 0` means no gate at all and costs nothing.
"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

__all__ = ["ConcurrencyGate"]


class ConcurrencyGate:
    """Allow at most `limit` concurrent calls; `limit <= 0` disables the gate."""

    def __init__(self, limit: int) -> None:
        self._semaphore = asyncio.Semaphore(limit) if limit > 0 else None

    @property
    def enabled(self) -> bool:
        return self._semaphore is not None

    @asynccontextmanager
    async def hold(self) -> AsyncIterator[None]:
        if self._semaphore is None:
            yield
            return
        async with self._semaphore:
            yield
