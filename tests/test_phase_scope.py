from __future__ import annotations

from pathlib import Path

from vyro_growth.config import Settings
from vyro_growth.providers.personalization import (
    StubPersonalizationProvider,
    build_personalization_provider,
)


def test_outbound_remains_disabled_by_default() -> None:
    settings = Settings()
    assert settings.outbound_enabled is False
    assert settings.internal_api_key == ""
    assert settings.openai_personalization_enabled is False


def test_env_example_keeps_outbound_disabled() -> None:
    env_example = Path(".env.example").read_text(encoding="utf-8")
    assert "OUTBOUND_ENABLED=false" in env_example
    assert "OUTBOUND_HALTED=false" in env_example
    assert "INTERNAL_API_KEY=" in env_example
    assert "WEBSITE_USER_AGENT=VyroGrowthEngine/0.1" in env_example
    assert "OPENAI_PERSONALIZATION_ENABLED=false" in env_example
    assert "sk-" not in env_example


def test_current_phases_do_not_add_later_phase_integrations() -> None:
    src_root = Path("src/vyro_growth")
    openai_boundary = {
        "config.py",
        "observability.py",
        "personalization.py",
        "personalization_openai.py",
        "personalization_handler.py",
    }
    forbidden = (
        "apollo",
        "smartlead",
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


def test_default_personalization_provider_is_stub() -> None:
    settings = Settings(openai_personalization_enabled=False)
    provider = build_personalization_provider(settings)
    assert isinstance(provider, StubPersonalizationProvider)


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
