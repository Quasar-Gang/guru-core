"""OpenAICompatLLM — adapter for any OpenAI-compatible endpoint.

Covers vLLM, Ollama, LM Studio, SGLang and TGI.
"""

import json
import time
from typing import TYPE_CHECKING, Any

import httpx

from packages.llm.concurrency import ConcurrencyGate
from packages.llm.config import LLMConfig
from packages.llm.observability import LlmCallLog
from packages.llm.ports import (
    LLMError,
    LLMSchemaError,
    LLMTransportError,
    OutputT,
    Purpose,
)
from packages.llm.prompts import PromptRegistry

if TYPE_CHECKING:
    from packages.llm.observability import LlmObserver

__all__ = ["OpenAICompatLLM"]

_TOOL_NAME = "emit"


class OpenAICompatLLM:
    """Get structured output from `POST {base_url}/chat/completions`."""

    def __init__(
        self,
        config: LLMConfig,
        prompts: PromptRegistry,
        observer: "LlmObserver",
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        provider = config.provider
        if not provider.base_url:
            raise LLMError("openai_compat adapter requires provider.base_url")
        self._config = config
        self._prompts = prompts
        self._observer = observer
        self._transport = transport
        self._url = f"{provider.base_url.rstrip('/')}/chat/completions"
        self._gate = ConcurrencyGate(provider.concurrency)

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
        schema = output_schema.model_json_schema()
        mode = provider.structured_output
        user = rendered.user
        if mode == "prompt":
            user = (
                f"{user}\n\n"
                "Reply with JSON only — no prose, no markdown fence — "
                "matching this JSON Schema:\n"
                f"{json.dumps(schema, ensure_ascii=False)}"
            )

        body: dict[str, Any] = {
            "model": provider.model,
            "messages": [
                {"role": "system", "content": rendered.system},
                {"role": "user", "content": user},
            ],
            "temperature": params.temperature,
            # The port calls it max_output_tokens; the wire field is max_tokens.
            "max_tokens": params.max_output_tokens,
        }
        if params.reasoning_effort is not None:
            body["reasoning_effort"] = params.reasoning_effort
        if mode == "guided_json":
            body["extra_body"] = {"guided_json": schema}
        elif mode == "json_schema":
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": output_schema.__name__,
                    "schema": schema,
                    "strict": True,
                },
            }
        elif mode == "tool_use":
            body["tools"] = [
                {
                    "type": "function",
                    "function": {"name": _TOOL_NAME, "parameters": schema},
                }
            ]
            body["tool_choice"] = {"type": "function", "function": {"name": _TOOL_NAME}}

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
                input_tokens=int(usage.get("prompt_tokens") or 0),
                output_tokens=int(usage.get("completion_tokens") or 0),
                latency_ms=latency_ms,
                attempts=1,
                degraded=False,
            )
        )
        return _parse(payload, output_schema, tool_use=mode == "tool_use")

    async def _post(self, body: dict[str, Any]) -> dict[str, Any]:
        provider = self._config.provider
        try:
            async with httpx.AsyncClient(
                transport=self._transport, timeout=provider.timeout_seconds
            ) as client:
                response = await client.post(
                    self._url,
                    json=body,
                    headers={"Authorization": f"Bearer {provider.api_key}"},
                )
        except httpx.HTTPError as exc:
            raise LLMTransportError(f"openai_compat request failed: {exc}") from exc
        if response.status_code // 100 != 2:
            raise LLMTransportError(
                f"openai_compat returned HTTP {response.status_code}: {response.text[:200]}"
            )
        try:
            decoded: dict[str, Any] = response.json()
        except ValueError as exc:
            raise LLMSchemaError(f"openai_compat response is not JSON: {exc}") from exc
        return decoded


def _parse(payload: dict[str, Any], output_schema: type[OutputT], *, tool_use: bool) -> OutputT:
    try:
        message = payload["choices"][0]["message"]
        raw = message["tool_calls"][0]["function"]["arguments"] if tool_use else message["content"]
        data = json.loads(raw) if isinstance(raw, str) else raw
        return output_schema.model_validate(data)
    except Exception as exc:  # noqa: BLE001 - normalise to the port's error type
        raise LLMSchemaError(f"cannot parse openai_compat response: {exc}") from exc
