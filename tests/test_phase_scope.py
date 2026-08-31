from __future__ import annotations

from pathlib import Path

from vyro_growth.config import Settings
from vyro_growth.providers.calendar_booking import (
    StubBookingCalendarProvider,
    build_booking_calendar_provider,
)
from vyro_growth.providers.personalization import (
    StubPersonalizationProvider,
    build_personalization_provider,
)
from vyro_growth.providers.reply_classification import (
    StubReplyClassifier,
    build_reply_classifier,
)
from vyro_growth.providers.smartlead import StubSmartleadProvider, build_smartlead_provider
from vyro_growth.providers.voice_qualification import (
    StubVoiceQualificationProvider,
    build_voice_qualification_provider,
)


def test_outbound_remains_disabled_by_default() -> None:
    settings = Settings()
    assert settings.outbound_enabled is False
    assert settings.internal_api_key == ""
    assert settings.openai_personalization_enabled is False
    assert settings.smartlead_live_enabled is False
    assert settings.smartlead_api_key == ""
    assert settings.openai_reply_classification_enabled is False
    assert settings.google_calendar_live_enabled is False
    assert settings.google_calendar_api_key == ""
    assert settings.voice_live_enabled is False
    assert settings.voice_api_key == ""


def test_env_example_keeps_outbound_disabled() -> None:
    env_example = Path(".env.example").read_text(encoding="utf-8")
    assert "OUTBOUND_ENABLED=false" in env_example
    assert "OUTBOUND_HALTED=false" in env_example
    assert "INTERNAL_API_KEY=" in env_example
    assert "WEBSITE_USER_AGENT=VyroGrowthEngine/0.1" in env_example
    assert "OPENAI_PERSONALIZATION_ENABLED=false" in env_example
    assert "SMARTLEAD_LIVE_ENABLED=false" in env_example
    assert "OPENAI_REPLY_CLASSIFICATION_ENABLED=false" in env_example
    assert "GOOGLE_CALENDAR_LIVE_ENABLED=false" in env_example
    assert "VOICE_LIVE_ENABLED=false" in env_example
    assert "sk-" not in env_example
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")
    assert "OUTBOUND_ENABLED=false" in dockerfile
    assert 'OUTBOUND_ENABLED: "false"' in compose
    assert "GOOGLE_CALENDAR_LIVE_ENABLED=false" in dockerfile
    assert "VOICE_LIVE_ENABLED=false" in dockerfile


def test_current_phases_do_not_add_later_phase_integrations() -> None:
    src_root = Path("src/vyro_growth")
    openai_boundary = {
        "config.py",
        "observability.py",
        "personalization.py",
        "personalization_openai.py",
        "personalization_handler.py",
        "reply_classification.py",
        "reply_classification_openai.py",
        "reply_classification_handler.py",
        "dashboard.py",
        "growth_optimizer.py",
        "optimizer.py",
        "monitoring.py",
    }
    calendar_boundary = {
        "config.py",
        "observability.py",
        "calendar_booking.py",
        "google_calendar.py",
        "guarded.py",
        "booking_plan.py",
        "booking_plan_handler.py",
        "models.py",
        "cli.py",
        "domain.py",
        "__init__.py",
        "dashboard.py",
        "growth_optimizer.py",
        "optimizer.py",
        "monitoring.py",
    }
    smartlead_boundary = {
        "config.py",
        "observability.py",
        "smartlead.py",
        "smartlead_live.py",
        "guarded.py",
        "outreach_enrollment.py",
        "outreach_enrollment_handler.py",
        "models.py",
        "cli.py",
        "domain.py",
        "__init__.py",
        "dashboard.py",
        "growth_optimizer.py",
        "optimizer.py",
        "monitoring.py",
    }
    forbidden = (
        "apollo",
        "firecrawl",
        "google.calendar",
        "twilio",
        "vapi",
        "retell",
    )
    for path in src_root.rglob("*.py"):
        source = path.read_text(encoding="utf-8").lower()
        for token in forbidden:
            assert token not in source, f"{token} found in {path}"
        if "openai" in source:
            assert path.name in openai_boundary, f"openai token leaked into {path}"
        if "smartlead" in source:
            assert path.name in smartlead_boundary, f"smartlead token leaked into {path}"
        if "google_calendar" in source or "google calendar" in source:
            assert path.name in calendar_boundary, f"google calendar token leaked into {path}"


def test_default_personalization_provider_is_stub() -> None:
    settings = Settings(openai_personalization_enabled=False)
    provider = build_personalization_provider(settings)
    assert isinstance(provider, StubPersonalizationProvider)


def test_default_smartlead_provider_is_stub() -> None:
    settings = Settings(smartlead_live_enabled=True, smartlead_api_key="placeholder")
    provider = build_smartlead_provider(settings)
    assert isinstance(provider, StubSmartleadProvider)


def test_smartlead_stub_and_planner_do_not_use_httpx() -> None:
    paths = [
        Path("src/vyro_growth/providers/smartlead.py"),
        Path("src/vyro_growth/services/outreach_enrollment.py"),
        Path("src/vyro_growth/workers/outreach_enrollment_handler.py"),
    ]
    source = "\n".join(path.read_text(encoding="utf-8") for path in paths).lower()
    assert "httpx" not in source
    env_example = Path(".env.example").read_text(encoding="utf-8")
    assert "OUTBOUND_ENABLED=false" in env_example
    assert "SMARTLEAD_LIVE_ENABLED=false" in env_example


def test_default_booking_calendar_provider_is_stub() -> None:
    settings = Settings(google_calendar_live_enabled=True, google_calendar_api_key="placeholder")
    provider = build_booking_calendar_provider(settings)
    assert isinstance(provider, StubBookingCalendarProvider)


def test_booking_stub_and_planner_do_not_use_httpx() -> None:
    paths = [
        Path("src/vyro_growth/providers/calendar_booking.py"),
        Path("src/vyro_growth/services/booking_plan.py"),
        Path("src/vyro_growth/workers/booking_plan_handler.py"),
    ]
    source = "\n".join(path.read_text(encoding="utf-8") for path in paths).lower()
    assert "httpx" not in source
    assert "google.calendar" not in source
    env_example = Path(".env.example").read_text(encoding="utf-8")
    assert "OUTBOUND_ENABLED=false" in env_example
    assert "GOOGLE_CALENDAR_LIVE_ENABLED=false" in env_example


def test_default_reply_classifier_is_stub() -> None:
    settings = Settings(openai_reply_classification_enabled=False)
    provider = build_reply_classifier(settings)
    assert isinstance(provider, StubReplyClassifier)


def test_default_voice_qualification_provider_is_stub() -> None:
    settings = Settings(voice_live_enabled=True, voice_api_key="placeholder")
    provider = build_voice_qualification_provider(settings)
    assert isinstance(provider, StubVoiceQualificationProvider)


def test_voice_stub_and_planner_do_not_use_httpx() -> None:
    paths = [
        Path("src/vyro_growth/providers/voice_qualification.py"),
        Path("src/vyro_growth/services/voice_qualification.py"),
        Path("src/vyro_growth/workers/voice_qualification_handler.py"),
    ]
    source = "\n".join(path.read_text(encoding="utf-8") for path in paths).lower()
    assert "httpx" not in source
    assert "twilio" not in source
    assert "vapi" not in source
    assert "retell" not in source
    env_example = Path(".env.example").read_text(encoding="utf-8")
    assert "OUTBOUND_ENABLED=false" in env_example
    assert "VOICE_LIVE_ENABLED=false" in env_example


def test_review_queue_does_not_call_live_providers() -> None:
    paths = [
        Path("src/vyro_growth/services/review_queue.py"),
        Path("src/vyro_growth/api/review_queue.py"),
    ]
    source = "\n".join(path.read_text(encoding="utf-8") for path in paths).lower()
    assert "httpx" not in source
    assert "google.calendar" not in source
    assert "twilio" not in source
    assert "vapi" not in source
    assert "retell" not in source
    env_example = Path(".env.example").read_text(encoding="utf-8")
    assert "OUTBOUND_ENABLED=false" in env_example


def test_content_briefs_do_not_call_live_providers() -> None:
    paths = [
        Path("src/vyro_growth/services/content_brief.py"),
        Path("src/vyro_growth/api/content_briefs.py"),
        Path("src/vyro_growth/workers/content_brief_handler.py"),
    ]
    source = "\n".join(path.read_text(encoding="utf-8") for path in paths).lower()
    assert "httpx" not in source
    assert "openai" not in source
    assert "google ads" not in source
    assert "search console" not in source
    assert "apollo" not in source
    assert "smartlead" not in source
    assert "google.calendar" not in source
    assert "twilio" not in source
    assert "vapi" not in source
    assert "retell" not in source
    env_example = Path(".env.example").read_text(encoding="utf-8")
    assert "OUTBOUND_ENABLED=false" in env_example


def test_growth_optimizer_does_not_call_live_providers() -> None:
    paths = [
        Path("src/vyro_growth/services/growth_optimizer.py"),
        Path("src/vyro_growth/api/optimizer.py"),
        Path("src/vyro_growth/workers/growth_optimizer_handler.py"),
    ]
    source = "\n".join(path.read_text(encoding="utf-8") for path in paths).lower()
    assert "httpx" not in source
    assert "google.calendar" not in source
    assert "twilio" not in source
    assert "vapi" not in source
    assert "retell" not in source
    env_example = Path(".env.example").read_text(encoding="utf-8")
    assert "OUTBOUND_ENABLED=false" in env_example


def test_monitoring_does_not_call_live_providers() -> None:
    paths = [
        Path("src/vyro_growth/services/monitoring.py"),
        Path("src/vyro_growth/api/monitoring.py"),
    ]
    source = "\n".join(path.read_text(encoding="utf-8") for path in paths).lower()
    assert "httpx" not in source
    assert "google.calendar" not in source
    assert "twilio" not in source
    assert "vapi" not in source
    assert "retell" not in source
    env_example = Path(".env.example").read_text(encoding="utf-8")
    assert "OUTBOUND_ENABLED=false" in env_example


def test_contact_enrichment_does_not_call_paid_or_linkedin_providers() -> None:
    paths = [
        Path("src/vyro_growth/providers/decision_makers.py"),
        Path("src/vyro_growth/services/contact_enrichment.py"),
        Path("src/vyro_growth/workers/contact_enrichment_handler.py"),
    ]
    source = "\n".join(path.read_text(encoding="utf-8") for path in paths).lower()
    assert "httpx" not in source
    assert "linkedin" not in source
    assert "apollo" not in source
    env_example = Path(".env.example").read_text(encoding="utf-8")
    assert "OUTBOUND_ENABLED=false" in env_example
