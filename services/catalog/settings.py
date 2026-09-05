"""Environment settings for the Catalog Service."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class CatalogSettings(BaseSettings):
    """Loaded from environment variables (or `.env`); each field name is the variable name."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/guru_core"
    catalog_api_key: str = "dev-catalog-key"

    #: `None` means `config/tag_vocab.yaml`; tests point this at a tmp_path.
    tag_vocab_path: Path | None = None
    seeds_path: Path = ROOT / "seeds" / "role_models" / "shapes.yaml"
