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
    """Call purpose; selects temperature, output length and role model context budget."""

    evaluate = "evaluate"
    generate = "generate"
    revise = "revise"
    recommend = "recommend"


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
