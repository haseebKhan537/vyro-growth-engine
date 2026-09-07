from __future__ import annotations

import pytest

from vyro_growth.config import (
    RuntimeConfigError,
    Settings,
    any_live_provider_enabled,
    live_provider_flags,
    require_valid_runtime_settings,
    validate_runtime_settings,
)


def test_development_allows_empty_internal_key() -> None:
    settings = Settings(environment="development", internal_api_key="")

    assert validate_runtime_settings(settings) == ()
    require_valid_runtime_settings(settings)


def test_production_fails_closed_without_internal_key() -> None:
    settings = Settings(environment="production", internal_api_key="   ")

    issues = validate_runtime_settings(settings)

    assert "INTERNAL_API_KEY is required outside development" in issues
    with pytest.raises(RuntimeConfigError, match="INTERNAL_API_KEY"):
        require_valid_runtime_settings(settings)


def test_staging_fails_closed_without_internal_key() -> None:
    settings = Settings(environment="staging", internal_api_key="")

    assert "INTERNAL_API_KEY is required outside development" in validate_runtime_settings(settings)


def test_production_accepts_internal_key_and_database_url() -> None:
    settings = Settings(
        environment="production",
        internal_api_key="internal-secret",
        database_url="postgresql+psycopg://vyro:vyro@postgres:5432/vyro_growth",
    )

    assert validate_runtime_settings(settings) == ()


def test_empty_database_url_fails_closed() -> None:
    settings = Settings(environment="development", database_url="  ")

    assert "DATABASE_URL is required" in validate_runtime_settings(settings)


@pytest.mark.parametrize(
    ("kwargs", "issue_fragment"),
    [
        ({"openai_personalization_enabled": True}, "OPENAI_API_KEY"),
        ({"openai_reply_classification_enabled": True}, "OPENAI_API_KEY"),
        ({"smartlead_live_enabled": True}, "SMARTLEAD_API_KEY"),
        ({"google_calendar_live_enabled": True}, "GOOGLE_CALENDAR_API_KEY"),
        ({"voice_live_enabled": True}, "VOICE_API_KEY"),
        ({"decision_maker_live_enabled": True}, "DECISION_MAKER_API_KEY"),
        ({"email_verification_live_enabled": True}, "EMAIL_VERIFICATION_API_KEY"),
        ({"email_verification_smtp_enabled": True}, "EMAIL_VERIFICATION_SMTP_ENABLED"),
    ],
)
def test_live_flag_without_key_fails_closed(
    kwargs: dict[str, bool],
    issue_fragment: str,
) -> None:
    settings = Settings(environment="development", **kwargs)

    issues = validate_runtime_settings(settings)

    assert any(issue_fragment in issue for issue in issues)


def test_live_flag_with_placeholder_key_is_valid_config() -> None:
    settings = Settings(
        environment="production",
        internal_api_key="internal-secret",
        openai_personalization_enabled=True,
        openai_api_key="placeholder",
    )

    assert validate_runtime_settings(settings) == ()
    assert live_provider_flags(settings)["openai_personalization"] is True
    assert any_live_provider_enabled(settings) is True


def test_default_settings_keep_live_providers_off() -> None:
    settings = Settings()

    assert settings.outbound_enabled is False
    assert any_live_provider_enabled(settings) is False
    assert live_provider_flags(settings) == {
        "openai_personalization": False,
        "openai_reply_classification": False,
        "smartlead": False,
        "google_calendar": False,
        "voice": False,
        "decision_maker": False,
        "email_verification": False,
    }
