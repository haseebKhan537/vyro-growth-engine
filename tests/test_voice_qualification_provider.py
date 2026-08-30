from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from vyro_growth.config import Settings
from vyro_growth.domain import VoiceConsentChannel, VoiceConsentSource
from vyro_growth.providers.voice_qualification import (
    MalformedVoicePlanOutput,
    StubVoiceQualificationProvider,
    VoiceConsentProof,
    VoiceQualificationRequest,
    build_voice_qualification_provider,
    contains_suspected_phi,
    message_requests_call,
    parse_voice_qualification_result,
    sanitize_stored_facts,
)


def _request() -> VoiceQualificationRequest:
    return VoiceQualificationRequest(
        lead_id=uuid4(),
        organization_id=uuid4(),
        idempotency_key="lead:contact:operator:ops-1",
        request_key="ops-1",
        consent=VoiceConsentProof(
            source=VoiceConsentSource.OPERATOR_REQUEST,
            channel=VoiceConsentChannel.OPERATOR,
            consented_at=datetime(2026, 8, 30, 15, 0, tzinfo=UTC),
            permitted_phone="5551112222",
            evidence_reference_id="ops-1",
        ),
        organization_name="AUSTIN FAMILY MEDICINE PLLC",
        stored_facts={"specialty": "Family Medicine"},
    )


def test_stub_plans_without_placing_a_call() -> None:
    provider = StubVoiceQualificationProvider()
    result = provider.plan_qualification(_request())

    assert result.accepted is True
    assert result.dry_run is True
    assert result.live_call_attempted is False
    assert result.call_placed is False
    assert result.provider_name == "stub"
    assert result.facts == {"specialty": "Family Medicine"}
    assert result.raw["call_placed"] is False
    assert provider.live is False


def test_build_voice_provider_ignores_live_flag() -> None:
    settings = Settings(voice_live_enabled=True, voice_api_key="placeholder")
    provider = build_voice_qualification_provider(settings)
    assert isinstance(provider, StubVoiceQualificationProvider)


def test_message_requests_call_requires_explicit_language() -> None:
    assert message_requests_call("Please call me tomorrow") is True
    assert message_requests_call("Let's meet next week if you can schedule a meeting.") is False
    assert message_requests_call("We are interested") is False


def test_contains_suspected_phi() -> None:
    assert contains_suspected_phi("Please call me. The patient has diabetes.") is True
    assert contains_suspected_phi("Please call me about billing follow-up.") is False


def test_sanitize_stored_facts_omits_unknown_and_phi() -> None:
    facts = sanitize_stored_facts(
        {
            "specialty": "Family Medicine",
            "denial_rate": "32%",
            "patient_note": "the patient is late",
            "urgency": "this week",
        }
    )
    assert facts == {"specialty": "Family Medicine", "urgency": "this week"}
    assert "denial_rate" not in facts
    assert "patient_note" not in facts


def test_parse_rejects_live_call_claim() -> None:
    with pytest.raises(MalformedVoicePlanOutput, match="live call"):
        parse_voice_qualification_result(
            {
                "accepted": True,
                "dry_run": True,
                "live_call_attempted": False,
                "call_placed": True,
                "provider_name": "stub",
                "facts": {},
            }
        )


def test_parse_rejects_invented_facts() -> None:
    with pytest.raises(MalformedVoicePlanOutput, match="invented"):
        parse_voice_qualification_result(
            {
                "accepted": True,
                "dry_run": True,
                "live_call_attempted": False,
                "call_placed": False,
                "provider_name": "stub",
                "facts": {"specialty": "Cardiology"},
            },
            allowed_facts={"specialty": "Family Medicine"},
        )
