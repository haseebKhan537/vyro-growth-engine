from __future__ import annotations

from uuid import uuid4

from vyro_growth.config import Settings
from vyro_growth.providers.smartlead import (
    MalformedSmartleadOutput,
    SmartleadLeadPayload,
    StaticSmartleadProvider,
    StubSmartleadProvider,
    build_smartlead_provider,
    parse_smartlead_plan_result,
    split_stored_name,
    stored_custom_fields,
)


def _payload() -> SmartleadLeadPayload:
    return SmartleadLeadPayload(
        campaign_key="phase-6-dry-run",
        email="jordan.blake@austinfamily.example",
        company_name="AUSTIN FAMILY MEDICINE PLLC",
        idempotency_key="camp:lead:contact",
        organization_id=uuid4(),
        first_name="Jordan",
        last_name="Blake",
        custom_fields={"organization_name": "AUSTIN FAMILY MEDICINE PLLC"},
    )


def test_stub_plans_without_live_send() -> None:
    provider = StubSmartleadProvider()
    result = provider.plan_enrollment(_payload())

    assert result.accepted is True
    assert result.dry_run is True
    assert result.live_call_attempted is False
    assert result.provider_name == "stub"
    assert result.raw["sent"] is False
    assert result.raw["enrolled_live"] is False
    assert provider.live is False


def test_build_smartlead_provider_ignores_live_flag() -> None:
    settings = Settings(smartlead_live_enabled=True, smartlead_api_key="placeholder")
    provider = build_smartlead_provider(settings)
    assert isinstance(provider, StubSmartleadProvider)


def test_stored_custom_fields_omit_missing_values() -> None:
    fields = stored_custom_fields(
        organization_name="AUSTIN FAMILY MEDICINE PLLC",
        city="AUSTIN",
        state="TX",
        specialty=None,
        website=None,
        npi="1487448189",
        opening_line="Hello",
        outreach_angle=None,
        suggested_offer="Complimentary Revenue Leakage Analysis",
        personalization_draft_id="draft-1",
    )
    assert fields["organization_name"] == "AUSTIN FAMILY MEDICINE PLLC"
    assert "specialty" not in fields
    assert "denial" not in str(fields).lower()
    assert "payer mix" not in str(fields).lower()


def test_split_stored_name_does_not_invent() -> None:
    assert split_stored_name("Jordan Blake") == ("Jordan", "Blake")
    assert split_stored_name("Jordan") == ("Jordan", None)
    assert split_stored_name("  ") == (None, None)


def test_parse_rejects_live_send_claim() -> None:
    try:
        parse_smartlead_plan_result(
            {
                "accepted": True,
                "dry_run": True,
                "live_call_attempted": False,
                "provider_name": "stub",
                "raw": {"sent": True},
            }
        )
    except MalformedSmartleadOutput as exc:
        assert "live send" in str(exc)
    else:
        raise AssertionError("expected malformed live send claim")


def test_static_provider_raises_configured_error() -> None:
    provider = StaticSmartleadProvider(error=MalformedSmartleadOutput("bad"))
    try:
        provider.plan_enrollment(_payload())
    except MalformedSmartleadOutput:
        return
    raise AssertionError("expected malformed output")
