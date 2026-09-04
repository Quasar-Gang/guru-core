"""InMemoryLlmCallRepo — in-memory implementation for tests."""

from __future__ import annotations

from packages.repo.entities import LlmCallLog


class InMemoryLlmCallRepo:
    """Accumulates llm_calls in an in-memory list; append-only."""

    def __init__(self) -> None:
        self.records: list[LlmCallLog] = []

    async def record(self, log: LlmCallLog) -> None:
        self.records.append(log)
