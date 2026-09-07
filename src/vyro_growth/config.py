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
    decision_maker_live_enabled: bool = Field(
        default=False,
        description=(
            "Explicit opt-in for the live decision-maker/people-search adapter boundary. "
            "Default false; CI and local development use the deterministic stub and never "
            "call a paid contact provider. Phase 66 does not perform live HTTP even when "
            "this flag is true unless a test injects a client."
        ),
    )
    decision_maker_api_key: str = Field(
        default="",
        description=(
            "Live people-search credential placeholder. Unused unless a future "
            "owner-approved live step."
        ),
    )
    decision_maker_api_base_url: str = Field(
        default="",
        description=(
            "Live people-search API base URL. Unused by default; not required for tests."
        ),
    )
    decision_maker_timeout_seconds: float = Field(default=10.0, ge=1.0)
    decision_maker_max_retries: int = Field(default=3, ge=0)
    decision_maker_retry_backoff_seconds: float = Field(default=0.5, ge=0.0)
    email_verification_live_enabled: bool = Field(
        default=False,
        description=(
            "Explicit opt-in for the live email-verification adapter boundary. Default "
            "false; CI and local development use the deterministic stub and never call "
            "NeverBounce/ZeroBounce/Hunter or SMTP recipient servers. Phase 69 does not "
            "perform live HTTP even when this flag is true unless a test injects a client."
        ),
    )
    email_verification_api_key: str = Field(
        default="",
        description=(
            "Live email-verifier credential placeholder. Unused unless a future "
            "owner-approved live step."
        ),
    )
    email_verification_api_base_url: str = Field(
        default="",
        description=(
            "Live email-verifier API base URL. Unused by default; not required for tests."
        ),
    )
    email_verification_timeout_seconds: float = Field(default=10.0, ge=1.0)
    email_verification_max_retries: int = Field(default=3, ge=0)
    email_verification_retry_backoff_seconds: float = Field(default=0.5, ge=0.0)
    email_verification_smtp_enabled: bool = Field(
        default=False,
        description=(
            "Must remain false. SMTP recipient-server validation is forbidden in Phase 69 "
            "and in CI/defaults."
        ),
    )


class RuntimeConfigError(ValueError):
    """Raised when required runtime or security settings are missing."""


def is_development_environment(settings: Settings) -> bool:
    return settings.environment == "development"


def live_provider_flags(settings: Settings) -> dict[str, bool]:
    """Explicit live-provider opt-in flags. All default false and stay unused in CI."""

    return {
        "openai_personalization": settings.openai_personalization_enabled,
        "openai_reply_classification": settings.openai_reply_classification_enabled,
        "smartlead": settings.smartlead_live_enabled,
        "google_calendar": settings.google_calendar_live_enabled,
        "voice": settings.voice_live_enabled,
        "decision_maker": settings.decision_maker_live_enabled,
        "email_verification": settings.email_verification_live_enabled,
    }


def any_live_provider_enabled(settings: Settings) -> bool:
    return any(live_provider_flags(settings).values())


def credential_presence_flags(settings: Settings) -> dict[str, bool]:
    """Boolean presence of local credentials. Never returns secret values."""

    return {
        "internal_api_key": bool(settings.internal_api_key.strip()),
        "generative_ai_api_key": bool(settings.openai_api_key.strip()),
        "campaign_provider_api_key": bool(settings.smartlead_api_key.strip()),
        "calendar_api_key": bool(settings.google_calendar_api_key.strip()),
        "voice_api_key": bool(settings.voice_api_key.strip()),
        "decision_maker_api_key": bool(settings.decision_maker_api_key.strip()),
        "email_verification_api_key": bool(settings.email_verification_api_key.strip()),
    }


def validate_runtime_settings(settings: Settings) -> tuple[str, ...]:
    """Return fail-closed configuration issues. Does not call external providers."""

    issues: list[str] = []
    if not settings.database_url.strip():
        issues.append("DATABASE_URL is required")
    if not is_development_environment(settings) and not settings.internal_api_key.strip():
        issues.append("INTERNAL_API_KEY is required outside development")
    if settings.openai_personalization_enabled and not settings.openai_api_key.strip():
        issues.append("OPENAI_API_KEY is required when OPENAI_PERSONALIZATION_ENABLED is true")
    if settings.openai_reply_classification_enabled and not settings.openai_api_key.strip():
        issues.append(
            "OPENAI_API_KEY is required when OPENAI_REPLY_CLASSIFICATION_ENABLED is true"
        )
    if settings.smartlead_live_enabled and not settings.smartlead_api_key.strip():
        issues.append("SMARTLEAD_API_KEY is required when SMARTLEAD_LIVE_ENABLED is true")
    if settings.google_calendar_live_enabled and not settings.google_calendar_api_key.strip():
        issues.append(
            "GOOGLE_CALENDAR_API_KEY is required when GOOGLE_CALENDAR_LIVE_ENABLED is true"
        )
    if settings.voice_live_enabled and not settings.voice_api_key.strip():
        issues.append("VOICE_API_KEY is required when VOICE_LIVE_ENABLED is true")
    if settings.decision_maker_live_enabled and not settings.decision_maker_api_key.strip():
        issues.append(
            "DECISION_MAKER_API_KEY is required when DECISION_MAKER_LIVE_ENABLED is true"
        )
    if (
        settings.email_verification_live_enabled
        and not settings.email_verification_api_key.strip()
    ):
        issues.append(
            "EMAIL_VERIFICATION_API_KEY is required when EMAIL_VERIFICATION_LIVE_ENABLED "
            "is true"
        )
    if settings.email_verification_smtp_enabled:
        issues.append("EMAIL_VERIFICATION_SMTP_ENABLED must remain false")
    return tuple(issues)


def require_valid_runtime_settings(settings: Settings) -> None:
    issues = validate_runtime_settings(settings)
    if issues:
        raise RuntimeConfigError("; ".join(issues))


@lru_cache
def get_settings() -> Settings:
    return Settings()
