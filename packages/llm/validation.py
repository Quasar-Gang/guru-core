"""Validate, retry with feedback, then degrade.

A well-formed response is not necessarily a sensible one, so both layers must pass.
"""

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
"""Return the list of violation messages; an empty list means the output passed."""


class LLMValidationExhausted(LLMError):
    """Retries were exhausted and no fallback was available."""

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
    """Call the LLM and apply the business rules.

    On failure the violations are fed back into the next attempt. Once attempts run out the
    fallback is used if one was given, otherwise LLMValidationExhausted is raised.
    """
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
