"""Environment settings for the Engine."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class EngineSettings(BaseSettings):
    """Loaded from environment variables (or `.env`); each field name is the variable name."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/guru_core"
    redis_url: str = "redis://127.0.0.1:6379/0"

    prompts_dir: Path = ROOT / "packages" / "llm" / "prompts"
    llm_fixtures_dir: Path = ROOT / "tests" / "fixtures" / "llm"
