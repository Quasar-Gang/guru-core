"""API service settings, read from environment variables and `.env` via pydantic-settings."""

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

    r2_account_id: str = ""
    r2_access_key_id: str = ""
    r2_secret_access_key: str = ""
    r2_bucket: str = ""

    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = ""

    oauth_token_enc_key: str = ""
    role_model_base_url: str = "http://127.0.0.1:8001"

    llm_fixtures_dir: Path = Path("tests/fixtures/llm")

    #: Requests allowed per caller per minute; 0 or less disables rate limiting entirely.
    rate_limit_per_minute: int = 60

    #: LOCAL SMOKE TESTING ONLY - NEVER ENABLE IN PRODUCTION.
    #: When true, `POST /v1/auth/google` accepts `{"code": "fake:<email>"}` and signs the
    #: caller in as that email without ever contacting Google, i.e. anyone can log in as
    #: anyone. It exists so `scripts/smoke.sh` can run without real Google credentials.
    allow_fake_login: bool = False
