"""LLMPort and its types: callers only deal in prompt names, context and an output schema."""

from enum import StrEnum
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel

__all__ = [
    "LLMError",
    "LLMPort",
    "LLMSchemaError",
    "LLMTransportError",
    "OutputT",
    "Purpose",
]


class Purpose(StrEnum):
    """Call purpose; selects temperature, output length and the context budget.

    Three, and only three, kinds of judgement are asked of a model anywhere in the system:
    read the data (`analyze`), hold a shape against it (`verdict`), and lay out the work
    (`generate`). Everything else — placing tasks on dates, applying the quota, diffing two
    schedules — is arithmetic, and arithmetic stays in code.
    """

    analyze = "analyze"
    verdict = "verdict"
    generate = "generate"


OutputT = TypeVar("OutputT", bound=BaseModel)


class LLMPort(Protocol):
    async def complete(
        self,
        prompt_name: str,
        context: dict[str, Any],
        output_schema: type[OutputT],
        purpose: Purpose,
    ) -> OutputT: ...


class LLMError(RuntimeError):
    """Base class for every LLM call failure."""


class LLMSchemaError(LLMError):
    """The response failed Pydantic validation."""


class LLMTransportError(LLMError):
    """The network or HTTP layer failed."""
