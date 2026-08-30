from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Vyro Growth Engine"
    environment: str = "development"
    database_url: str = "postgresql+psycopg://vyro:vyro@localhost:5432/vyro_growth"
    outbound_enabled: bool = Field(
        default=False,
        description=(
            "Primary env enablement for outreach-like actions. Must be explicitly true, "
            "and is not sufficient if the operator halt is active."
        ),
    )
    outbound_halted: bool = Field(
        default=False,
        description=(
            "Settings-backed operator halt. When true, blocks outbound even if "
            "OUTBOUND_ENABLED is true."
        ),
    )
    log_level: str = "INFO"
    nppes_api_base_url: str = "https://npiregistry.cms.hhs.gov/api/"
    nppes_timeout_seconds: float = Field(default=10.0, ge=1.0)
    nppes_max_retries: int = Field(default=3, ge=0)
    nppes_retry_backoff_seconds: float = Field(default=0.5, ge=0.0)
    discovery_max_records_per_run: int = Field(default=500, ge=1)
    internal_api_key: str = Field(
        default="",
        description=(
            "Shared secret for internal HTTP triggers such as NPPES discovery. "
            "Required outside development; empty is fail-closed in those environments."
        ),
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
