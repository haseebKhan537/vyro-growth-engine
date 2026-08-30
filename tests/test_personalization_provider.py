from __future__ import annotations

from uuid import uuid4

import pytest

from tests.fixtures.personalization import invented_payload, sample_pack
from vyro_growth.config import Settings
from vyro_growth.domain import PersonalizationReadiness
from vyro_growth.providers.personalization import (
    DEFAULT_OFFER,
    MalformedPersonalizationOutput,
    PersonalizationRequest,
    StaticPersonalizationProvider,
    StubPersonalizationProvider,
    build_personalization_provider,
    generate_stub_content,
    ground_personalization_content,
    parse_personalization_content,
)


def test_stub_generates_grounded_draft_from_stored_evidence() -> None:
    pack = sample_pack()
    content = generate_stub_content(pack)

    assert "AUSTIN FAMILY MEDICINE PLLC" in content.practice_summary
    assert "Family Medicine" in content.practice_summary
    assert "AUSTIN" in content.practice_summary
    assert content.suggested_offer == DEFAULT_OFFER
    assert content.readiness_status is PersonalizationReadiness.READY
    assert content.confidence > 0
    assert "denial rate" not in content.practice_summary.lower()
    assert "payer mix" not in content.why_vyro_relevant.lower()
    grounded = ground_personalization_content(content, pack)
    assert grounded.evidence_references


def test_stub_missing_evidence_does_not_invent_facts() -> None:
    pack = sample_pack(missing=True)
    content = generate_stub_content(pack)

    assert content.readiness_status is PersonalizationReadiness.NEEDS_MORE_EVIDENCE
    assert any("specialty" in note for note in content.missing_data_notes)
    assert "denial" not in content.practice_summary.lower()
    assert "provider count" not in content.practice_summary.lower()
    assert content.suggested_offer == DEFAULT_OFFER


def test_stub_provider_records_no_live_call() -> None:
    pack = sample_pack()
    provider = StubPersonalizationProvider()
    result = provider.generate(PersonalizationRequest(lead_id=uuid4(), pack=pack))
    assert result.audit.live_call_attempted is False
    assert result.audit.provider_name == "stub"
    assert result.audit.prompt_version
    assert result.audit.prompt_hash


def test_build_personalization_provider_defaults_to_stub() -> None:
    settings = Settings(openai_personalization_enabled=False, openai_api_key="")
    provider = build_personalization_provider(settings)
    assert isinstance(provider, StubPersonalizationProvider)


def test_static_provider_rejects_malformed_payload() -> None:
    provider = StaticPersonalizationProvider({"nope": True})
    with pytest.raises(MalformedPersonalizationOutput):
        provider.generate(PersonalizationRequest(lead_id=uuid4(), pack=sample_pack()))


def test_invented_claims_are_rejected_during_grounding() -> None:
    parsed = parse_personalization_content(invented_payload())
    assert parsed is not None
    with pytest.raises(MalformedPersonalizationOutput, match="ungrounded claim"):
        ground_personalization_content(parsed, sample_pack())
