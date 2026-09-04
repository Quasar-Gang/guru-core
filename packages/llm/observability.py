"""LLM call observability (PRD 7.8): the fields recorded per call, plus a minimal observer."""

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
    """Write a structured log line only; nothing is persisted to the database."""

    async def record(self, log: LlmCallLog) -> None:
        _logger.info("llm_call", extra={"llm_call": log.model_dump(mode="json")})
