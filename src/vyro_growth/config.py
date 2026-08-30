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
            "Shared secret for internal HTTP routes such as NPPES discovery and the "
            "operator dashboard. Required outside development; empty is fail-closed "
            "in those environments."
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
    smartlead_live_enabled: bool = Field(
        default=False,
        description=(
            "Explicit opt-in for the live Smartlead adapter boundary. Default false; "
            "CI and local development use the deterministic stub and never enroll or send. "
            "Phase 6 does not perform live HTTP even when this flag is true unless a test "
            "injects a client."
        ),
    )
    smartlead_api_key: str = Field(
        default="",
        description="Live Smartlead API key. Unused unless a future owner-approved live step.",
    )
    smartlead_api_base_url: str = Field(
        default="",
        description="Live Smartlead API base URL. Unused by default; not required for tests.",
    )
    smartlead_timeout_seconds: float = Field(default=10.0, ge=1.0)
    smartlead_max_retries: int = Field(default=3, ge=0)
    smartlead_retry_backoff_seconds: float = Field(default=0.5, ge=0.0)
    openai_reply_classification_enabled: bool = Field(
        default=False,
        description=(
            "Explicit opt-in for live OpenAI reply classification. Default false; CI and "
            "local development use the deterministic rule stub and never require a live key."
        ),
    )
    google_calendar_live_enabled: bool = Field(
        default=False,
        description=(
            "Explicit opt-in for the live Google Calendar/Meet adapter boundary. Default "
            "false; CI and local development use the deterministic stub and never create "
            "calendar events or Meet links. Phase 8 does not perform live HTTP even when "
            "this flag is true unless a test injects a client."
        ),
    )
    google_calendar_api_key: str = Field(
        default="",
        description=(
            "Live Google Calendar credential placeholder. Unused unless a future "
            "owner-approved live step."
        ),
    )
    google_calendar_api_base_url: str = Field(
        default="",
        description=(
            "Live Google Calendar API base URL. Unused by default; not required for tests."
        ),
    )
    google_calendar_timeout_seconds: float = Field(default=10.0, ge=1.0)
    google_calendar_max_retries: int = Field(default=3, ge=0)
    google_calendar_retry_backoff_seconds: float = Field(default=0.5, ge=0.0)
    voice_live_enabled: bool = Field(
        default=False,
        description=(
            "Explicit opt-in for the live voice qualification adapter boundary. Default "
            "false; CI and local development use the deterministic stub and never place "
            "calls. Phase 9 does not perform live HTTP even when this flag is true unless "
            "a test injects a client."
        ),
    )
    voice_api_key: str = Field(
        default="",
        description=(
            "Live voice provider credential placeholder. Unused unless a future "
            "owner-approved live step."
        ),
    )
    voice_api_base_url: str = Field(
        default="",
        description="Live voice API base URL. Unused by default; not required for tests.",
    )
    voice_timeout_seconds: float = Field(default=10.0, ge=1.0)
    voice_max_retries: int = Field(default=3, ge=0)
    voice_retry_backoff_seconds: float = Field(default=0.5, ge=0.0)


@lru_cache
def get_settings() -> Settings:
    return Settings()
