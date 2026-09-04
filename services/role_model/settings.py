"""Environment settings for the Role Model Service."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class RoleModelSettings(BaseSettings):
    """Loaded from environment variables (or `.env`); each field name is the variable name,
    case-insensitive.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/guru_core"
    role_model_api_key: str = "dev-role-model-key"
    tag_vocab_path: Path | None = None
    """None means `config/tag_vocab.yaml`; tests override this with a tmp_path."""

    llm_fixtures_dir: Path = ROOT / "tests" / "fixtures" / "llm"
