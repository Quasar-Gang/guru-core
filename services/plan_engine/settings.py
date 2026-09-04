"""Environment settings for the Plan Engine, read from environment variables and `.env`."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

__all__ = ["PlanEngineSettings"]

ROOT = Path(__file__).resolve().parents[2]


class PlanEngineSettings(BaseSettings):
    """Each field name is the environment variable name, case-insensitive."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/guru_core"
    redis_url: str = "redis://127.0.0.1:6379/0"

    llm_fixtures_dir: Path = ROOT / "tests" / "fixtures" / "llm"
    """Where `FakeLLM` reads its canned responses from."""

    prompts_dir: Path = ROOT / "packages" / "llm" / "prompts"
    """Where `PromptRegistry` reads the `*.md` templates from."""
