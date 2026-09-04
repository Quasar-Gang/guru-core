"""Role Model Service 的環境設定。"""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class RoleModelSettings(BaseSettings):
    """由環境變數（或 `.env`）載入；欄位名即環境變數名（不分大小寫）。"""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/guru_core"
    role_model_api_key: str = "dev-role-model-key"
    tag_vocab_path: Path | None = None
    """None 表示用 `config/tag_vocab.yaml`；測試以 tmp_path 覆寫。"""

    llm_fixtures_dir: Path = ROOT / "tests" / "fixtures" / "llm"
