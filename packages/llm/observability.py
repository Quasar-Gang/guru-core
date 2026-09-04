"""LLM 呼叫觀測（PRD 7.8）：每次呼叫記錄的欄位與最小實作。"""

import logging
from typing import Protocol

from pydantic import BaseModel

from packages.llm.ports import Purpose

__all__ = ["LlmCallLog", "LlmObserver", "NullObserver"]

_logger = logging.getLogger("packages.llm.observability")


class LlmCallLog(BaseModel):
    prompt_name: str
    prompt_version: str
    provider: str
    model: str
    purpose: Purpose
    input_tokens: int
    output_tokens: int
    latency_ms: int
    attempts: int
    degraded: bool
    job_id: str | None = None


class LlmObserver(Protocol):
    async def record(self, log: LlmCallLog) -> None: ...


class NullObserver:
    """只寫 structured log，不落 DB。"""

    async def record(self, log: LlmCallLog) -> None:
        _logger.info("llm_call", extra={"llm_call": log.model_dump(mode="json")})
