"""In-memory `llm_calls` sink; tests assert on `records`."""

from __future__ import annotations

from packages.repo.entities import LlmCallLog

__all__ = ["InMemoryLlmCallRepo"]


class InMemoryLlmCallRepo:
    def __init__(self) -> None:
        self.records: list[LlmCallLog] = []

    async def record(self, log: LlmCallLog) -> None:
        self.records.append(log)
