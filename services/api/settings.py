"""API Service 的設定（pydantic-settings，讀環境變數與 `.env`）。"""

from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

__all__ = ["ApiSettings"]


class ApiSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str
    redis_url: str

    jwt_secret: str
    jwt_ttl_seconds: int = 2592000

    storage_backend: Literal["local", "memory", "r2"] = "local"
    storage_local_root: Path = Path("./.data/storage")
    storage_public_base_url: str
    storage_signing_secret: str

    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = ""

    oauth_token_enc_key: str = ""
    role_model_base_url: str = "http://127.0.0.1:8001"
    llm_fixtures_dir: Path = Path("tests/fixtures/llm")
