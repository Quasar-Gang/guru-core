"""LLMPort 與其型別：呼叫端只認識 prompt 名稱、context 與輸出 schema。"""

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
    """呼叫用途，決定溫度、輸出長度與 role model context 預算。"""

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
    """LLM 呼叫失敗的共同基底。"""


class LLMSchemaError(LLMError):
    """回應無法通過 Pydantic 驗證。"""


class LLMTransportError(LLMError):
    """網路 / HTTP 層失敗。"""
