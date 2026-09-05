"""LLM call observability: the fields recorded per call, plus a minimal observer."""

import logging
from typing import Protocol

from pydantic import BaseModel

from packages.llm.ports import Purpose
from packages.logging import current_job_id
from packages.repo.entities import LlmCallLog as LlmCallRow
from packages.repo.ports import LlmCallRepo

__all__ = ["DbLlmObserver", "LlmCallLog", "LlmObserver", "NullObserver"]

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


class DbLlmObserver:
    """Persist one row per LLM call to the `llm_calls` table."""

    def __init__(self, repo: LlmCallRepo) -> None:
        self._repo = repo

    async def record(self, log: LlmCallLog) -> None:
        # `packages.llm.observability.LlmCallLog` and `packages.repo.entities.LlmCallLog`
        # are deliberately two different models: the first is what an LLM adapter knows
        # about a call, the second is what the repo boundary accepts. They happen to carry
        # the same fields today, but neither layer may depend on the other's shape, so the
        # translation is explicit here rather than passed straight through.
        await self._repo.record(
            LlmCallRow(
                prompt_name=log.prompt_name,
                prompt_version=log.prompt_version,
                provider=log.provider,
                model=log.model,
                purpose=log.purpose,
                input_tokens=log.input_tokens,
                output_tokens=log.output_tokens,
                latency_ms=log.latency_ms,
                attempts=log.attempts,
                degraded=log.degraded,
                # Adapters do not know which job they run inside, so fall back to the
                # job id bound by the worker handler.
                job_id=log.job_id or current_job_id(),
            )
        )
