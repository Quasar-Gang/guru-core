"""InMemoryLlmCallRepo — 測試用的記憶體實作。"""

from __future__ import annotations

from packages.repo.entities import LlmCallLog


class InMemoryLlmCallRepo:
    """把 llm_calls 累積在記憶體 list 中（僅追加）。"""

    def __init__(self) -> None:
        self.records: list[LlmCallLog] = []

    async def record(self, log: LlmCallLog) -> None:
        self.records.append(log)
