"""OpenAICompatLLM: request assembly, parsing and error mapping, driven by httpx.MockTransport."""

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import BaseModel

from packages.llm.config import LLMConfig, ProviderConfig, PurposeParams, RetryConfig
from packages.llm.openai_compat import OpenAICompatLLM
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


def _cfg(structured_output: str = "guided_json") -> LLMConfig:
    return LLMConfig(
        provider=ProviderConfig(
            adapter="openai_compat",
            base_url="http://llm.test/v1",
            api_key="key-1",
            model="local-model",
            structured_output=structured_output,  # type: ignore[arg-type]
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


def _ok_response(request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": '{"n": 7}'}}],
            "usage": {"prompt_tokens": 11, "completion_tokens": 3},
        },
    )


async def test_openai_compat_uses_guided_json_and_parses() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        captured["_url"] = str(request.url)
        captured["_auth"] = request.headers.get("authorization")
        return _ok_response(request)

    llm = OpenAICompatLLM(
        _cfg(structured_output="guided_json"),
        _prompts(),
        _FakeObserver(),
        transport=httpx.MockTransport(handler),
    )
    out = await llm.complete("smoke", {"goal": "g"}, Out, Purpose.generate)

    assert out.n == 7
    assert "guided_json" in captured["extra_body"]
    assert captured["extra_body"]["guided_json"] == Out.model_json_schema()
    assert captured["temperature"] == 0.4
    assert captured["max_tokens"] == 4000
    assert captured["model"] == "local-model"
    assert captured["_url"] == "http://llm.test/v1/chat/completions"
    assert captured["_auth"] == "Bearer key-1"


async def test_openai_compat_json_schema_mode_sets_response_format() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return _ok_response(request)

    llm = OpenAICompatLLM(
        _cfg(structured_output="json_schema"),
        _prompts(),
        _FakeObserver(),
        transport=httpx.MockTransport(handler),
    )
    await llm.complete("smoke", {"goal": "g"}, Out, Purpose.evaluate)

    fmt = captured["response_format"]
    assert fmt["type"] == "json_schema"
    assert fmt["json_schema"]["strict"] is True
    assert fmt["json_schema"]["schema"] == Out.model_json_schema()
    assert "extra_body" not in captured


async def test_openai_compat_prompt_mode_appends_schema_to_user_message() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return _ok_response(request)

    llm = OpenAICompatLLM(
        _cfg(structured_output="prompt"),
        _prompts(),
        _FakeObserver(),
        transport=httpx.MockTransport(handler),
    )
    await llm.complete("smoke", {"goal": "g"}, Out, Purpose.generate)

    user = captured["messages"][-1]["content"]
    assert "JSON" in user
    assert '"n"' in user
    assert "response_format" not in captured
    assert "extra_body" not in captured


async def test_openai_compat_tool_use_mode_reads_tool_call_arguments() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "tool_calls": [{"function": {"name": "emit", "arguments": '{"n": 9}'}}]
                        }
                    }
                ],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            },
        )

    llm = OpenAICompatLLM(
        _cfg(structured_output="tool_use"),
        _prompts(),
        _FakeObserver(),
        transport=httpx.MockTransport(handler),
    )
    out = await llm.complete("smoke", {"goal": "g"}, Out, Purpose.generate)

    assert out.n == 9
    assert captured["tools"][0]["function"]["name"] == "emit"
    assert captured["tools"][0]["function"]["parameters"] == Out.model_json_schema()
    assert captured["tool_choice"]["function"]["name"] == "emit"


async def test_openai_compat_records_observability() -> None:
    observer = _FakeObserver()
    llm = OpenAICompatLLM(
        _cfg(),
        _prompts(),
        observer,
        transport=httpx.MockTransport(_ok_response),
    )
    await llm.complete("smoke", {"goal": "g"}, Out, Purpose.generate)

    assert len(observer.logs) == 1
    log = observer.logs[0]
    assert log.prompt_name == "smoke"
    assert log.prompt_version == _prompts().version("smoke")
    assert log.provider == "openai_compat"
    assert log.model == "local-model"
    assert log.purpose is Purpose.generate
    assert log.input_tokens == 11
    assert log.output_tokens == 3
    assert log.latency_ms >= 0
    assert log.attempts == 1
    assert log.degraded is False


async def test_openai_compat_missing_usage_records_zero_tokens() -> None:
    observer = _FakeObserver()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"n": 1}'}}]})

    llm = OpenAICompatLLM(_cfg(), _prompts(), observer, transport=httpx.MockTransport(handler))
    await llm.complete("smoke", {"goal": "g"}, Out, Purpose.generate)

    assert observer.logs[0].input_tokens == 0
    assert observer.logs[0].output_tokens == 0


async def test_openai_compat_bad_json_raises_schema_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": "not json"}}]})

    llm = OpenAICompatLLM(
        _cfg(), _prompts(), _FakeObserver(), transport=httpx.MockTransport(handler)
    )
    with pytest.raises(LLMSchemaError):
        await llm.complete("smoke", {"goal": "g"}, Out, Purpose.generate)


async def test_openai_compat_schema_mismatch_raises_schema_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"n": "x"}'}}]})

    llm = OpenAICompatLLM(
        _cfg(), _prompts(), _FakeObserver(), transport=httpx.MockTransport(handler)
    )
    with pytest.raises(LLMSchemaError):
        await llm.complete("smoke", {"goal": "g"}, Out, Purpose.generate)


async def test_openai_compat_http_500_raises_transport_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    llm = OpenAICompatLLM(
        _cfg(), _prompts(), _FakeObserver(), transport=httpx.MockTransport(handler)
    )
    with pytest.raises(LLMTransportError):
        await llm.complete("smoke", {"goal": "g"}, Out, Purpose.generate)


async def test_openai_compat_connection_failure_raises_transport_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route")

    llm = OpenAICompatLLM(
        _cfg(), _prompts(), _FakeObserver(), transport=httpx.MockTransport(handler)
    )
    with pytest.raises(LLMTransportError):
        await llm.complete("smoke", {"goal": "g"}, Out, Purpose.generate)
