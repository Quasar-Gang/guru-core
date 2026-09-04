"""AnthropicLLM：以 tool use 強制 schema，並映射錯誤與觀測欄位。"""

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import BaseModel

from packages.llm.anthropic_llm import AnthropicLLM
from packages.llm.config import LLMConfig, ProviderConfig, PurposeParams, RetryConfig
from packages.llm.ports import LLMSchemaError, LLMTransportError, Purpose
from packages.llm.prompts import PromptRegistry

PROMPTS_DIR = Path(__file__).resolve().parents[4] / "packages" / "llm" / "prompts"


class Out(BaseModel):
    n: int


class _FakeObserver:
    def __init__(self) -> None:
        self.logs: list[Any] = []

    async def record(self, log: Any) -> None:
        self.logs.append(log)


def _prompts() -> PromptRegistry:
    return PromptRegistry(PROMPTS_DIR)


def _cfg() -> LLMConfig:
    return LLMConfig(
        provider=ProviderConfig(
            adapter="anthropic",
            base_url="https://claude.test",
            api_key="key-2",
            model="claude-test",
            structured_output="tool_use",
        ),
        params={
            Purpose.evaluate: PurposeParams(temperature=0.2, max_output_tokens=1500),
            Purpose.generate: PurposeParams(temperature=0.4, max_output_tokens=4000),
            Purpose.revise: PurposeParams(temperature=0.3, max_output_tokens=3000),
            Purpose.recommend: PurposeParams(temperature=0.3, max_output_tokens=800),
        },
        budgets={
            Purpose.evaluate: 100,
            Purpose.generate: 300,
            Purpose.revise: 200,
            Purpose.recommend: 600,
        },
        retry=RetryConfig(),
    )


def _tool_use_response(request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "content": [{"type": "tool_use", "name": "emit", "input": {"n": 7}}],
            "usage": {"input_tokens": 5, "output_tokens": 2},
        },
    )


async def test_anthropic_uses_tool_use() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        captured["_url"] = str(request.url)
        captured["_api_key"] = request.headers.get("x-api-key")
        captured["_version"] = request.headers.get("anthropic-version")
        return _tool_use_response(request)

    llm = AnthropicLLM(_cfg(), _prompts(), _FakeObserver(), transport=httpx.MockTransport(handler))
    out = await llm.complete("smoke", {"goal": "g"}, Out, Purpose.generate)

    assert out.n == 7
    assert captured["tools"][0]["input_schema"] == Out.model_json_schema()
    assert captured["tool_choice"]["type"] == "tool"
    assert captured["tool_choice"]["name"] == "emit"
    assert captured["model"] == "claude-test"
    assert captured["temperature"] == 0.4
    assert captured["max_tokens"] == 4000
    assert captured["_url"] == "https://claude.test/v1/messages"
    assert captured["_api_key"] == "key-2"
    assert captured["_version"]


async def test_anthropic_records_observability() -> None:
    observer = _FakeObserver()
    llm = AnthropicLLM(
        _cfg(), _prompts(), observer, transport=httpx.MockTransport(_tool_use_response)
    )
    await llm.complete("smoke", {"goal": "g"}, Out, Purpose.generate)

    log = observer.logs[0]
    assert log.prompt_name == "smoke"
    assert log.prompt_version == _prompts().version("smoke")
    assert log.provider == "anthropic"
    assert log.model == "claude-test"
    assert log.input_tokens == 5
    assert log.output_tokens == 2
    assert log.attempts == 1
    assert log.degraded is False


async def test_anthropic_missing_tool_use_block_raises_schema_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"content": [{"type": "text", "text": "hi"}], "usage": {}},
        )

    llm = AnthropicLLM(_cfg(), _prompts(), _FakeObserver(), transport=httpx.MockTransport(handler))
    with pytest.raises(LLMSchemaError):
        await llm.complete("smoke", {"goal": "g"}, Out, Purpose.generate)


async def test_anthropic_schema_mismatch_raises_schema_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "content": [{"type": "tool_use", "name": "emit", "input": {"n": "x"}}],
                "usage": {"input_tokens": 1, "output_tokens": 1},
            },
        )

    llm = AnthropicLLM(_cfg(), _prompts(), _FakeObserver(), transport=httpx.MockTransport(handler))
    with pytest.raises(LLMSchemaError):
        await llm.complete("smoke", {"goal": "g"}, Out, Purpose.generate)


async def test_anthropic_http_429_raises_transport_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, text="slow down")

    llm = AnthropicLLM(_cfg(), _prompts(), _FakeObserver(), transport=httpx.MockTransport(handler))
    with pytest.raises(LLMTransportError):
        await llm.complete("smoke", {"goal": "g"}, Out, Purpose.generate)


async def test_anthropic_connection_failure_raises_transport_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timeout")

    llm = AnthropicLLM(_cfg(), _prompts(), _FakeObserver(), transport=httpx.MockTransport(handler))
    with pytest.raises(LLMTransportError):
        await llm.complete("smoke", {"goal": "g"}, Out, Purpose.generate)
