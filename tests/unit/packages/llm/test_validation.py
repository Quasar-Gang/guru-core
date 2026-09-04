import copy
from typing import Any

import pytest
from pydantic import BaseModel

from packages.llm import LLMValidationExhausted, Purpose, complete_validated
from packages.llm.ports import OutputT


class Out(BaseModel):
    n: int


class _ScriptedLLM:
    """Return the canned outputs in order, recording a deep copy of every context received."""

    def __init__(self, outputs: list[BaseModel]) -> None:
        self._outputs = list(outputs)
        self.contexts: list[dict[str, Any]] = []

    async def complete(
        self,
        prompt_name: str,
        context: dict[str, Any],
        output_schema: type[OutputT],
        purpose: Purpose,
    ) -> OutputT:
        self.contexts.append(copy.deepcopy(context))
        if not self._outputs:
            raise AssertionError("scripted LLM ran out of outputs")
        return output_schema.model_validate(self._outputs.pop(0).model_dump())


async def test_passes_first_try_when_rules_ok():
    llm = _ScriptedLLM([Out(n=5)])
    r = await complete_validated(
        llm, "p", {}, Out, Purpose.generate, max_attempts=3, rules=[lambda o: []]
    )
    assert r.attempts == 1 and r.degraded is False
    assert r.value.n == 5
    assert r.violations == []


async def test_retries_with_violations_injected():
    llm = _ScriptedLLM([Out(n=99), Out(n=1)])

    def rule(o: BaseModel) -> list[str]:
        assert isinstance(o, Out)
        return [] if o.n < 10 else ["n must be < 10"]

    r = await complete_validated(llm, "p", {}, Out, Purpose.generate, max_attempts=3, rules=[rule])
    assert r.attempts == 2 and r.value.n == 1
    assert llm.contexts[1]["_violations"] == ["n must be < 10"]
    assert llm.contexts[1]["_previous_output"]["n"] == 99


async def test_degrades_to_fallback_when_exhausted():
    llm = _ScriptedLLM([Out(n=99)] * 3)
    r = await complete_validated(
        llm,
        "p",
        {},
        Out,
        Purpose.generate,
        max_attempts=3,
        rules=[lambda o: ["always bad"]],
        fallback=lambda v: Out(n=0),
    )
    assert r.attempts == 3 and r.degraded is True and r.value.n == 0
    assert r.violations == ["always bad"]


async def test_raises_when_no_fallback():
    with pytest.raises(LLMValidationExhausted) as excinfo:
        await complete_validated(
            _ScriptedLLM([Out(n=99)] * 2),
            "p",
            {},
            Out,
            Purpose.generate,
            max_attempts=2,
            rules=[lambda o: ["bad"]],
        )
    assert excinfo.value.violations == ["bad"]


async def test_no_rules_always_passes_in_one_attempt():
    llm = _ScriptedLLM([Out(n=99)])
    r = await complete_validated(llm, "p", {}, Out, Purpose.generate, max_attempts=3)
    assert r.attempts == 1 and r.degraded is False and r.violations == []
    assert len(llm.contexts) == 1


async def test_violations_from_multiple_rules_are_merged():
    llm = _ScriptedLLM([Out(n=99), Out(n=99)])
    r = await complete_validated(
        llm,
        "p",
        {},
        Out,
        Purpose.generate,
        max_attempts=2,
        rules=[lambda o: ["first"], lambda o: [], lambda o: ["second", "third"]],
        fallback=lambda v: Out(n=len(v)),
    )
    assert r.violations == ["first", "second", "third"]
    assert llm.contexts[1]["_violations"] == ["first", "second", "third"]
    assert r.value.n == 3


async def test_caller_context_is_not_mutated():
    llm = _ScriptedLLM([Out(n=99), Out(n=99)])
    context: dict[str, Any] = {"goal": "g"}
    await complete_validated(
        llm,
        "p",
        context,
        Out,
        Purpose.generate,
        max_attempts=2,
        rules=[lambda o: ["bad"]],
        fallback=lambda v: Out(n=0),
    )
    assert context == {"goal": "g"}
    assert llm.contexts[0] == {"goal": "g"}
