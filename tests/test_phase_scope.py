from __future__ import annotations

from pathlib import Path

from vyro_growth.config import Settings


def test_outbound_remains_disabled_by_default() -> None:
    settings = Settings()
    assert settings.outbound_enabled is False
    assert settings.internal_api_key == ""


def test_env_example_keeps_outbound_disabled() -> None:
    env_example = Path(".env.example").read_text(encoding="utf-8")
    assert "OUTBOUND_ENABLED=false" in env_example
    assert "OUTBOUND_HALTED=false" in env_example
    assert "INTERNAL_API_KEY=" in env_example


def test_current_phases_do_not_add_later_phase_integrations() -> None:
    src_root = Path("src/vyro_growth")
    source = "\n".join(path.read_text(encoding="utf-8") for path in src_root.rglob("*.py"))
    forbidden = (
        "apollo",
        "smartlead",
        "openai",
        "firecrawl",
        "google.calendar",
        "twilio",
        "vapi",
    )
    lowered = source.lower()
    for token in forbidden:
        assert token not in lowered


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
