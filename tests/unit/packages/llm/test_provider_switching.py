"""The config must let a deployment move between providers without a code change.

These lock the two properties that make that true: every value is an environment
variable, and a field one provider needs but another rejects can be switched off
by leaving that variable empty.
"""

import asyncio
import json
from typing import Any

import httpx
import pytest
from pydantic import BaseModel

from packages.llm import Purpose, load_llm_config
from packages.llm.anthropic_llm import AnthropicLLM
from packages.llm.concurrency import ConcurrencyGate
from packages.llm.observability import LlmCallLog
from packages.llm.openai_compat import OpenAICompatLLM
from packages.llm.prompts import PromptRegistry


class Out(BaseModel):
    n: int


class _Observer:
    def __init__(self) -> None:
        self.logs: list[LlmCallLog] = []

    async def record(self, log: LlmCallLog) -> None:
        self.logs.append(log)


@pytest.fixture
def prompts(tmp_path):
    (tmp_path / "p.md").write_text('---\nversion: "1"\n---\n# SYSTEM\nsys\n# USER\nuser\n')
    return PromptRegistry(tmp_path)


def _capture() -> tuple[dict[str, Any], httpx.MockTransport]:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        if "/v1/messages" in str(request.url):
            return httpx.Response(
                200,
                json={
                    "content": [{"type": "tool_use", "name": "emit", "input": {"n": 1}}],
                    "usage": {"input_tokens": 1, "output_tokens": 1},
                },
            )
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"n": 1}'}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            },
        )

    return seen, httpx.MockTransport(handler)


# --- configuration is entirely environment-driven ---------------------------


def test_defaults_describe_the_hosted_baseline(monkeypatch):
    for var in (
        "LLM_ADAPTER",
        "LLM_BASE_URL",
        "LLM_MODEL",
        "LLM_STRUCTURED_OUTPUT",
        "LLM_MAX_CONTEXT",
        "LLM_TIMEOUT",
        "LLM_CONCURRENCY",
        "LLM_REASONING_EFFORT",
    ):
        monkeypatch.delenv(var, raising=False)
    provider = load_llm_config().provider
    assert provider.base_url == "https://api.x.ai/v1"
    assert provider.model == "grok-4.6"
    assert provider.structured_output == "json_schema"
    assert provider.max_context_tokens == 500000
    assert provider.concurrency == 0


def test_every_provider_field_is_overridable(monkeypatch):
    monkeypatch.setenv("LLM_ADAPTER", "anthropic")
    monkeypatch.setenv("LLM_BASE_URL", "")
    monkeypatch.setenv("LLM_MODEL", "claude-sonnet-5")
    monkeypatch.setenv("LLM_STRUCTURED_OUTPUT", "tool_use")
    monkeypatch.setenv("LLM_MAX_CONTEXT", "200000")
    monkeypatch.setenv("LLM_TIMEOUT", "120")
    monkeypatch.setenv("LLM_CONCURRENCY", "0")

    provider = load_llm_config().provider

    assert provider.adapter == "anthropic"
    assert provider.base_url is None  # blank means "use the adapter's own default"
    assert provider.model == "claude-sonnet-5"
    assert provider.structured_output == "tool_use"
    assert provider.max_context_tokens == 200000
    assert provider.timeout_seconds == 120
    assert provider.concurrency == 0


def test_blank_reasoning_effort_means_unset(monkeypatch):
    monkeypatch.setenv("LLM_REASONING_EFFORT", "")
    config = load_llm_config()
    assert all(p.reasoning_effort is None for p in config.params.values())


def test_reasoning_effort_defaults_to_low_for_grok(monkeypatch):
    monkeypatch.delenv("LLM_REASONING_EFFORT", raising=False)
    assert load_llm_config().params_for(Purpose.generate).reasoning_effort == "low"


# --- adapters honour it -----------------------------------------------------


async def test_openai_compat_sends_reasoning_effort_when_set(monkeypatch, prompts):
    monkeypatch.setenv("LLM_ADAPTER", "openai_compat")
    monkeypatch.setenv("LLM_REASONING_EFFORT", "none")
    seen, transport = _capture()
    llm = OpenAICompatLLM(load_llm_config(), prompts, _Observer(), transport=transport)

    await llm.complete("p", {}, Out, Purpose.generate)

    assert seen["reasoning_effort"] == "none"
    assert seen["max_tokens"] == 4000  # the port's max_output_tokens on the wire


async def test_openai_compat_omits_reasoning_effort_when_blank(monkeypatch, prompts):
    monkeypatch.setenv("LLM_ADAPTER", "openai_compat")
    monkeypatch.setenv("LLM_REASONING_EFFORT", "")
    seen, transport = _capture()
    llm = OpenAICompatLLM(load_llm_config(), prompts, _Observer(), transport=transport)

    await llm.complete("p", {}, Out, Purpose.generate)

    assert "reasoning_effort" not in seen


async def test_anthropic_never_sends_reasoning_effort(monkeypatch, prompts):
    """A config tuned for a local runtime must stay valid against Claude."""
    monkeypatch.setenv("LLM_ADAPTER", "anthropic")
    monkeypatch.setenv("LLM_REASONING_EFFORT", "none")
    seen, transport = _capture()
    llm = AnthropicLLM(load_llm_config(), prompts, _Observer(), transport=transport)

    await llm.complete("p", {}, Out, Purpose.generate)

    assert "reasoning_effort" not in seen
    assert seen["tool_choice"] == {"type": "tool", "name": "emit"}


# --- the concurrency gate ---------------------------------------------------


async def test_gate_serialises_when_limited():
    gate = ConcurrencyGate(1)
    order: list[str] = []

    async def worker(name: str) -> None:
        async with gate.hold():
            order.append(f"{name}-in")
            await asyncio.sleep(0.01)
            order.append(f"{name}-out")

    await asyncio.gather(worker("a"), worker("b"))

    # With a limit of 1 no two holds overlap, so the pairs never interleave.
    assert order in (
        ["a-in", "a-out", "b-in", "b-out"],
        ["b-in", "b-out", "a-in", "a-out"],
    )


async def test_gate_allows_overlap_when_uncapped():
    gate = ConcurrencyGate(0)
    assert gate.enabled is False
    order: list[str] = []

    async def worker(name: str) -> None:
        async with gate.hold():
            order.append(f"{name}-in")
            await asyncio.sleep(0.01)
            order.append(f"{name}-out")

    await asyncio.gather(worker("a"), worker("b"))

    assert order[:2] == ["a-in", "b-in"]  # both entered before either finished


async def test_openai_compat_serialises_requests_when_concurrency_is_one(monkeypatch, prompts):
    monkeypatch.setenv("LLM_ADAPTER", "openai_compat")
    monkeypatch.setenv("LLM_CONCURRENCY", "1")
    inflight = 0
    peak = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal inflight, peak
        inflight += 1
        peak = max(peak, inflight)
        await asyncio.sleep(0.01)
        inflight -= 1
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"n": 1}'}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            },
        )

    llm = OpenAICompatLLM(
        load_llm_config(), prompts, _Observer(), transport=httpx.MockTransport(handler)
    )

    await asyncio.gather(*(llm.complete("p", {}, Out, Purpose.generate) for _ in range(4)))

    assert peak == 1
