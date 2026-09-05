"""FakeLLM — LLMPort implementation for development and tests, answering from fixtures."""

import json
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from packages.llm.observability import LlmCallLog, LlmObserver
from packages.llm.ports import LLMError, LLMSchemaError, OutputT, Purpose

__all__ = ["FakeLLM"]


class FakeLLM:
    """Return a canned response per prompt name; `overrides` wins over `fixtures_dir`.

    A prompt asked more than once in a run can answer differently each time: the n-th call
    to a prompt uses `{name}.{n}.json` when that file exists, and falls back to
    `{name}.json` otherwise. Without that, a validate-and-retry chain could never be tested
    end to end, because the second attempt would repeat the first one's mistake forever.
    """

    def __init__(
        self,
        fixtures_dir: Path,
        overrides: Mapping[str, Any] | None = None,
        observer: LlmObserver | None = None,
    ) -> None:
        self._fixtures_dir = fixtures_dir
        self._overrides = dict(overrides or {})
        # Optional so the many tests that only care about the answer stay untouched; when
        # given, the fake reports calls exactly like the real adapters do, which is what
        # makes the observability wiring testable without a provider.
        self._observer = observer
        self._call_counts: dict[str, int] = {}
        self.calls: list[tuple[str, Purpose, dict[str, Any]]] = []

    async def complete(
        self,
        prompt_name: str,
        context: dict[str, Any],
        output_schema: type[OutputT],
        purpose: Purpose,
    ) -> OutputT:
        self.calls.append((prompt_name, purpose, context))
        started = time.perf_counter()
        occurrence = self._call_counts.get(prompt_name, 0) + 1
        self._call_counts[prompt_name] = occurrence
        payload = self._payload(prompt_name, occurrence)
        if self._observer is not None:
            await self._record(prompt_name, purpose, started)
        try:
            return output_schema.model_validate(payload)
        except Exception as exc:  # noqa: BLE001 - normalise to the port's error type
            raise LLMSchemaError(
                f"fixture for {prompt_name!r} does not match schema: {exc}"
            ) from exc

    async def _record(self, prompt_name: str, purpose: Purpose, started: float) -> None:
        assert self._observer is not None
        await self._observer.record(
            LlmCallLog(
                prompt_name=prompt_name,
                prompt_version="fake",
                provider="fake",
                model="fake",
                purpose=purpose,
                input_tokens=0,
                output_tokens=0,
                latency_ms=int((time.perf_counter() - started) * 1000),
                attempts=1,
                degraded=False,
            )
        )

    def _payload(self, prompt_name: str, occurrence: int) -> Any:
        if prompt_name in self._overrides:
            return self._overrides[prompt_name]
        numbered = self._fixtures_dir / f"{prompt_name}.{occurrence}.json"
        path = numbered if numbered.is_file() else self._fixtures_dir / f"{prompt_name}.json"
        if not path.is_file():
            raise LLMError(f"no fixture for {prompt_name!r} in {self._fixtures_dir}")
        return json.loads(path.read_text(encoding="utf-8"))
