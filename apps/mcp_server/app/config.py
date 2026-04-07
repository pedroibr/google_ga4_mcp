from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = Field(default="development", alias="APP_ENV")
    app_name: str = "google-ga4-mcp"
    database_url: str = Field(
        default="sqlite+pysqlite:///:memory:",
        alias="DATABASE_URL",
    )
    google_oauth_client_id: str = Field(default="", alias="GOOGLE_OAUTH_CLIENT_ID")
    google_oauth_client_secret: str = Field(default="", alias="GOOGLE_OAUTH_CLIENT_SECRET")
    google_oauth_refresh_token: str = Field(default="", alias="GOOGLE_OAUTH_REFRESH_TOKEN")
    worker_shared_secret_salt: str = Field(
        default="change-me",
        alias="WORKER_SHARED_SECRET_SALT",
    )
    request_ttl_seconds: int = Field(default=300, alias="REQUEST_TTL_SECONDS")
    allow_sqlite: bool = Field(default=True, alias="ALLOW_SQLITE")
    admin_api_shared_secret: str = Field(default="", alias="ADMIN_API_SHARED_SECRET")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        populate_by_name=True,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
