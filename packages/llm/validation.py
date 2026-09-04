"""驗證 → 回灌 → 降級鏈（PRD 7.5）：格式對不代表內容合理，兩層都要過。"""

from collections.abc import Callable, Sequence
from typing import Any

from pydantic import BaseModel

from packages.llm.ports import LLMError, LLMPort, OutputT, Purpose

__all__ = [
    "BusinessRule",
    "LLMValidationExhausted",
    "ValidationOutcome",
    "complete_validated",
]

BusinessRule = Callable[[Any], list[str]]
"""回傳違規訊息列，空 list 代表通過。"""


class LLMValidationExhausted(LLMError):
    """重試耗盡且沒有 fallback 可降級。"""

    def __init__(self, violations: list[str]) -> None:
        super().__init__("; ".join(violations) or "validation exhausted")
        self.violations = list(violations)


class ValidationOutcome[T: BaseModel](BaseModel):
    value: T
    attempts: int
    degraded: bool
    violations: list[str] = []


async def complete_validated(
    llm: LLMPort,
    prompt_name: str,
    context: dict[str, Any],
    output_schema: type[OutputT],
    purpose: Purpose,
    *,
    max_attempts: int,
    rules: Sequence[BusinessRule] = (),
    fallback: Callable[[list[str]], OutputT] | None = None,
) -> ValidationOutcome[OutputT]:
    """呼叫 LLM 並跑業務規則；失敗就把違規訊息回灌重試，耗盡則降級或拋錯。"""
    violations: list[str] = []
    previous_output: dict[str, Any] = {}
    attempts = 0
    while attempts < max_attempts:
        call_context = dict(context)
        if violations:
            call_context["_violations"] = list(violations)
            call_context["_previous_output"] = previous_output
        value = await llm.complete(prompt_name, call_context, output_schema, purpose)
        attempts += 1
        violations = [message for rule in rules for message in rule(value)]
        if not violations:
            return ValidationOutcome(value=value, attempts=attempts, degraded=False)
        previous_output = value.model_dump(mode="json")

    if fallback is None:
        raise LLMValidationExhausted(violations)
    return ValidationOutcome(
        value=fallback(violations), attempts=attempts, degraded=True, violations=violations
    )
