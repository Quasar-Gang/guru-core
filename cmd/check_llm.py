# Smoke test: load config -> build_llm -> run one smoke prompt -> print provider/model/elapsed.
import asyncio
import time
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from packages.config import load_dotenv
from packages.llm import LlmCallLog, PromptRegistry, Purpose, load_llm_config
from packages.llm.factory import build_llm

ROOT = Path(__file__).resolve().parent.parent


class SmokeOut(BaseModel):
    model_config = ConfigDict(extra="allow")


class _Collector:
    async def record(self, log: LlmCallLog) -> None:
        print(log.model_dump_json())


async def _main() -> None:
    config = load_llm_config()
    prompts = PromptRegistry(ROOT / "packages" / "llm" / "prompts")
    llm = build_llm(config, prompts, _Collector(), ROOT / "tests" / "fixtures" / "llm")
    started = time.monotonic()
    out = await llm.complete("smoke", {"goal": "run 5k"}, SmokeOut, Purpose.analyze)
    print(
        f"adapter={config.provider.adapter} model={config.provider.model} "
        f"elapsed={time.monotonic() - started:.2f}s output={out.model_dump_json()}"
    )


if __name__ == "__main__":
    load_dotenv()
    asyncio.run(_main())
