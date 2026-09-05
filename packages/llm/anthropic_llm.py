"""AnthropicLLM — Claude API adapter that enforces the output schema via tool use."""

import time
from typing import TYPE_CHECKING, Any

import httpx

from packages.llm.concurrency import ConcurrencyGate
from packages.llm.config import LLMConfig
from packages.llm.observability import LlmCallLog
from packages.llm.ports import (
    LLMSchemaError,
    LLMTransportError,
    OutputT,
    Purpose,
)
from packages.llm.prompts import PromptRegistry

if TYPE_CHECKING:
    from packages.llm.observability import LlmObserver

__all__ = ["AnthropicLLM"]

_TOOL_NAME = "emit"
_API_VERSION = "2023-06-01"
_DEFAULT_BASE_URL = "https://api.anthropic.com"


class AnthropicLLM:
    """Get structured output from `POST {base_url}/v1/messages`."""

    def __init__(
        self,
        config: LLMConfig,
        prompts: PromptRegistry,
        observer: "LlmObserver",
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._config = config
        self._prompts = prompts
        self._observer = observer
        self._transport = transport
        base_url = config.provider.base_url or _DEFAULT_BASE_URL
        self._url = f"{base_url.rstrip('/')}/v1/messages"
        # Honoured for symmetry — a hosted provider normally leaves it at 0, but the
        # same knob works if you ever need to rate-limit yourself.
        self._gate = ConcurrencyGate(config.provider.concurrency)

    async def complete(
        self,
        prompt_name: str,
        context: dict[str, Any],
        output_schema: type[OutputT],
        purpose: Purpose,
    ) -> OutputT:
        provider = self._config.provider
        params = self._config.params_for(purpose)
        rendered = self._prompts.render(prompt_name, context)

        body: dict[str, Any] = {
            "model": provider.model,
            "system": rendered.system,
            "messages": [{"role": "user", "content": rendered.user}],
            "temperature": params.temperature,
            "max_tokens": params.max_output_tokens,
            "tools": [
                {
                    "name": _TOOL_NAME,
                    "description": f"Emit the {output_schema.__name__} result.",
                    "input_schema": output_schema.model_json_schema(),
                }
            ],
            "tool_choice": {"type": "tool", "name": _TOOL_NAME},
        }

        # reasoning_effort is deliberately not sent: it is an OpenAI-style field with
        # no Anthropic equivalent, so a config tuned for a local runtime stays valid
        # here without edits.
        started = time.perf_counter()
        async with self._gate.hold():
            payload = await self._post(body)
        latency_ms = int((time.perf_counter() - started) * 1000)

        usage = payload.get("usage") or {}
        await self._observer.record(
            LlmCallLog(
                prompt_name=prompt_name,
                prompt_version=rendered.version,
                provider=provider.adapter,
                model=provider.model,
                purpose=purpose,
                input_tokens=int(usage.get("input_tokens") or 0),
                output_tokens=int(usage.get("output_tokens") or 0),
                latency_ms=latency_ms,
                attempts=1,
                degraded=False,
            )
        )
        return _parse(payload, output_schema)

    async def _post(self, body: dict[str, Any]) -> dict[str, Any]:
        provider = self._config.provider
        try:
            async with httpx.AsyncClient(
                transport=self._transport, timeout=provider.timeout_seconds
            ) as client:
                response = await client.post(
                    self._url,
                    json=body,
                    headers={
                        "x-api-key": provider.api_key,
                        "anthropic-version": _API_VERSION,
                    },
                )
        except httpx.HTTPError as exc:
            raise LLMTransportError(f"anthropic request failed: {exc}") from exc
        if response.status_code // 100 != 2:
            raise LLMTransportError(
                f"anthropic returned HTTP {response.status_code}: {response.text[:200]}"
            )
        try:
            decoded: dict[str, Any] = response.json()
        except ValueError as exc:
            raise LLMSchemaError(f"anthropic response is not JSON: {exc}") from exc
        return decoded


def _parse(payload: dict[str, Any], output_schema: type[OutputT]) -> OutputT:
    blocks = payload.get("content") or []
    for block in blocks:
        if isinstance(block, dict) and block.get("type") == "tool_use":
            try:
                return output_schema.model_validate(block.get("input"))
            except Exception as exc:  # noqa: BLE001 - normalise to the port's error type
                raise LLMSchemaError(f"anthropic tool_use input is invalid: {exc}") from exc
    raise LLMSchemaError("anthropic response has no tool_use block")
