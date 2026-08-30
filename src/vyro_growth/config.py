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
    website_fetch_timeout_seconds: float = Field(default=8.0, ge=1.0)
    website_fetch_max_bytes: int = Field(default=524_288, ge=1024)
    website_fetch_max_redirects: int = Field(default=3, ge=0)
    website_max_pages_per_org: int = Field(default=5, ge=1)
    website_rate_limit_seconds: float = Field(default=0.5, ge=0.0)
    website_user_agent: str = Field(
        default="VyroGrowthEngine/0.1 (+https://github.com/haseebKhan537/vyro-growth-engine)"
    )
    openai_personalization_enabled: bool = Field(
        default=False,
        description=(
            "Explicit opt-in for live OpenAI personalization. Default false; CI and local "
            "development use the deterministic stub and never require a live key."
        ),
    )
    openai_api_key: str = Field(
        default="",
        description="Live OpenAI API key. Unused unless openai_personalization_enabled is true.",
    )
    openai_api_base_url: str = Field(default="https://api.openai.com/v1")
    openai_personalization_model: str = Field(default="gpt-4o-mini")
    openai_timeout_seconds: float = Field(default=20.0, ge=1.0)
    openai_max_retries: int = Field(default=3, ge=0)
    openai_retry_backoff_seconds: float = Field(default=0.5, ge=0.0)
    openai_max_output_tokens: int = Field(default=800, ge=1)
    openai_max_input_tokens: int = Field(default=4000, ge=1)
    openai_estimated_cost_usd_limit: float | None = Field(
        default=None,
        description="Placeholder cost ceiling for a future live adapter. Not enforced yet.",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
