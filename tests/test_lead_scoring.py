from __future__ import annotations

import ast
import json
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from vyro_growth.domain import LeadStage
from vyro_growth.models import Activity, Contact, Lead, LeadScore, Organization, SourceEvidence
from vyro_growth.services.lead_scoring import (
    BATCH_MAX,
    MODEL_VERSION,
    FactorCode,
    FactorStatus,
    LeadScoringError,
    LeadScoringService,
    ScoreBand,
    ScoreFactor,
    ScoringResult,
    ScoringSnapshot,
    classify_specialty,
    npi_checksum_valid,
    score_snapshot,
)
from vyro_growth.workers.outbound import outbound_action_for_job
from vyro_growth.workers.scoring_handler import SCORE_DISCOVERED_LEADS_JOB


def _factor(result: ScoringResult, code: FactorCode) -> ScoreFactor:
    matches = [item for item in result.factors if item.code is code]
    assert len(matches) == 1
    return matches[0]


def _target_snapshot(
    *,
    organization_name: str | None = "AUSTIN FAMILY MEDICINE PLLC",
    npi: str | None = "1487448189",
    city: str | None = "AUSTIN",
    state: str | None = "TX",
    specialty: str | None = "Family Medicine",
    website: str | None = "https://austinfamily.example",
    nppes_status: str | None = "A",
    has_nppes_evidence: bool = True,
    nppes_source_url: str | None = "https://npiregistry.cms.hhs.gov/api/",
    verified_email: bool = True,
    has_contact_email: bool = True,
    decision_maker_title: str | None = "Practice Manager",
) -> ScoringSnapshot:
    return ScoringSnapshot(
        organization_name=organization_name,
        npi=npi,
        city=city,
        state=state,
        specialty=specialty,
        website=website,
        nppes_status=nppes_status,
        has_nppes_evidence=has_nppes_evidence,
        nppes_source_url=nppes_source_url,
        verified_email=verified_email,
        has_contact_email=has_contact_email,
        decision_maker_title=decision_maker_title,
    )


def test_npi_checksum_matches_known_registry_sample() -> None:
    assert npi_checksum_valid("1487448189") is True
    assert npi_checksum_valid("1234567890") is False


def test_classify_specialty_is_conservative() -> None:
    assert classify_specialty("Family Medicine").value == "target"
    assert classify_specialty("General Acute Care Hospital").value == "excluded"
    assert classify_specialty("Acupuncture").value == "unknown"
    assert classify_specialty(None).value == "unknown"


def test_complete_local_record_scores_high_with_all_factors() -> None:
    result = score_snapshot(_target_snapshot())

    assert result.total == 100
    assert result.band is ScoreBand.HIGH
    assert result.model_version == MODEL_VERSION
    assert result.fabricated_facts is False
    assert result.external_providers_called == ()
    assert _factor(result, FactorCode.NPI_IDENTITY).points == 20
    assert _factor(result, FactorCode.SPECIALTY_FIT).points == 15
    assert _factor(result, FactorCode.LOCAL_WEBSITE).points == 5
    assert _factor(result, FactorCode.VERIFIED_EMAIL).points == 5


def test_missing_data_scores_zero_and_lists_missing_fields() -> None:
    result = score_snapshot(
        ScoringSnapshot(
            organization_name=None,
            npi=None,
            city=None,
            state=None,
            specialty=None,
            website=None,
            nppes_status=None,
            has_nppes_evidence=False,
            nppes_source_url=None,
            verified_email=False,
            has_contact_email=False,
            decision_maker_title=None,
        )
    )

    assert result.total == 0
    assert result.band is ScoreBand.LOW
    assert "organization.name" in result.missing_fields
    assert "organization.npi" in result.missing_fields
    assert "organization.website" in result.missing_fields
    assert "contact.email_verified" in result.missing_fields
    assert _factor(result, FactorCode.NPI_IDENTITY).status is FactorStatus.MISSING
    assert _factor(result, FactorCode.SPECIALTY_FIT).reason == "specialty missing; fit not inferred"
    excluded = _factor(result, FactorCode.EXCLUDED_ORGANIZATION_NAME)
    assert excluded.status is FactorStatus.NOT_APPLICABLE


def test_score_is_deterministic() -> None:
    snapshot = _target_snapshot(website=None, verified_email=False, has_contact_email=False)
    first = score_snapshot(snapshot)
    second = score_snapshot(snapshot)

    assert first == second
    assert first.to_rationale() == second.to_rationale()


def test_rationale_payload_is_auditable_and_json_serializable() -> None:
    result = score_snapshot(_target_snapshot(website=None))
    payload = result.to_rationale()

    assert payload["fabricated_facts"] is False
    assert payload["external_providers_called"] == []
    assert payload["policy"] == {
        "no_outbound": True,
        "local_data_only": True,
        "unknown_not_inferred": True,
    }
    assert isinstance(payload["factors"], list)
    assert {factor["code"] for factor in payload["factors"]} == {code.value for code in FactorCode}
    json.dumps(payload)


def test_website_is_not_inferred_from_organization_name() -> None:
    result = score_snapshot(
        _target_snapshot(
            organization_name="Austin Family Medicine",
            website=None,
        )
    )

    website = _factor(result, FactorCode.LOCAL_WEBSITE)
    assert website.points == 0
    assert website.status is FactorStatus.MISSING
    assert "not guessed from organization name" in website.reason


def test_unknown_specialty_is_not_assumed_positive() -> None:
    result = score_snapshot(_target_snapshot(specialty="Acupuncture"))

    present = _factor(result, FactorCode.SPECIALTY_PRESENT)
    fit = _factor(result, FactorCode.SPECIALTY_FIT)
    assert present.points == 8
    assert fit.points == 0
    assert fit.status is FactorStatus.APPLIED
    assert "not assumed" in fit.reason


def test_hospital_specialty_is_penalized() -> None:
    result = score_snapshot(_target_snapshot(specialty="General Acute Care Hospital"))

    fit = _factor(result, FactorCode.SPECIALTY_FIT)
    assert fit.points == -10
    assert "outside the conservative medical billing ICP" in fit.reason


def test_invalid_npi_checksum_is_not_counted() -> None:
    result = score_snapshot(_target_snapshot(npi="1234567890"))

    npi = _factor(result, FactorCode.NPI_IDENTITY)
    assert npi.points == 0
    assert npi.status is FactorStatus.APPLIED
    assert "checksum" in npi.reason


def test_invalid_state_is_not_counted() -> None:
    result = score_snapshot(_target_snapshot(state="ZZ"))

    state = _factor(result, FactorCode.US_STATE)
    assert state.points == 0
    assert "not a recognized US jurisdiction" in state.reason


def test_unverified_email_is_not_counted() -> None:
    result = score_snapshot(_target_snapshot(verified_email=False, has_contact_email=True))

    email = _factor(result, FactorCode.VERIFIED_EMAIL)
    assert email.points == 0
    assert email.observed_value == "false"
    assert "not verified" in email.reason


def test_nppes_evidence_without_status_is_not_assumed_active() -> None:
    result = score_snapshot(_target_snapshot(nppes_status=None, has_nppes_evidence=True))

    status = _factor(result, FactorCode.NPPES_ACTIVE_STATUS)
    assert status.points == 0
    assert status.status is FactorStatus.MISSING
    assert "not assumed" in status.reason


def test_excluded_organization_name_applies_penalty() -> None:
    result = score_snapshot(_target_snapshot(organization_name="AUSTIN GENERAL HOSPITAL"))

    excluded = _factor(result, FactorCode.EXCLUDED_ORGANIZATION_NAME)
    assert excluded.points == -15
    assert excluded.status is FactorStatus.APPLIED


def _seed_organization(
    db: Session,
    *,
    name: str = "AUSTIN FAMILY MEDICINE PLLC",
    npi: str | None = "1487448189",
    city: str | None = "AUSTIN",
    state: str | None = "TX",
    specialty: str | None = "Family Medicine",
    website: str | None = None,
    with_nppes_evidence: bool = True,
) -> Organization:
    organization = Organization(
        name=name,
        npi=npi,
        city=city,
        state=state,
        specialty=specialty,
        website=website,
    )
    db.add(organization)
    db.flush()
    if with_nppes_evidence:
        db.add(
            SourceEvidence(
                organization_id=organization.id,
                source_url="https://npiregistry.cms.hhs.gov/api/",
                claim_type="nppes_organization_record",
                extracted_value=name,
                metadata_json={"business_record": {"status": "A", "npi": npi}},
            )
        )
        db.flush()
    return organization


def test_score_organization_creates_lead_score_and_activity(db_session: Session) -> None:
    organization = _seed_organization(db_session)
    service = LeadScoringService()

    result = service.score_organization(db_session, organization.id)

    lead = db_session.get(Lead, result.lead_id)
    score_row = db_session.get(LeadScore, result.lead_score_id)
    activity = db_session.scalar(select(Activity).where(Activity.action == "lead_scored"))

    assert result.lead_created is True
    assert lead is not None
    assert lead.stage == LeadStage.DISCOVERED.value
    assert lead.source == "nppes"
    assert score_row is not None
    assert score_row.score == result.scoring.total
    assert score_row.model_version == MODEL_VERSION
    assert score_row.rationale["fabricated_facts"] is False
    assert score_row.rationale["external_providers_called"] == []
    assert activity is not None
    assert activity.actor == "lead_scoring"
    assert activity.lead_id == lead.id
    assert activity.details["fabricated_facts"] is False


def test_score_organization_reuses_existing_lead_and_does_not_qualify(db_session: Session) -> None:
    organization = _seed_organization(db_session)
    lead = Lead(
        organization_id=organization.id,
        stage=LeadStage.DISCOVERED.value,
        source="nppes",
    )
    db_session.add(lead)
    db_session.flush()
    service = LeadScoringService()

    result = service.score_organization(db_session, organization.id)
    refreshed = db_session.get(Lead, lead.id)

    assert result.lead_id == lead.id
    assert result.lead_created is False
    assert refreshed is not None
    assert refreshed.stage == LeadStage.DISCOVERED.value


def test_score_lead_missing_id_raises(db_session: Session) -> None:
    service = LeadScoringService()

    with pytest.raises(LeadScoringError, match="Lead not found"):
        service.score_lead(db_session, uuid4())


def test_unverified_contact_email_is_ignored_in_persisted_score(db_session: Session) -> None:
    organization = _seed_organization(db_session)
    db_session.add(
        Contact(
            organization_id=organization.id,
            full_name="Alex Admin",
            title="Practice Manager",
            email="alex@clinic.example",
            email_verified=False,
        )
    )
    db_session.flush()
    service = LeadScoringService()

    result = service.score_organization(db_session, organization.id)
    email = _factor(result.scoring, FactorCode.VERIFIED_EMAIL)
    title = _factor(result.scoring, FactorCode.DECISION_MAKER_TITLE)

    assert email.points == 0
    assert title.points == 5
    assert title.observed_value == "Practice Manager"


def test_score_batch_respects_limit(db_session: Session) -> None:
    _seed_organization(db_session, npi="1487448189")
    _seed_organization(db_session, name="SECOND CLINIC", npi="1234567893")
    service = LeadScoringService()

    results = service.score_batch(db_session, limit=1)

    assert len(results) == 1
    assert db_session.scalar(select(LeadScore).limit(1)) is not None


def test_score_batch_rejects_non_positive_limit(db_session: Session) -> None:
    service = LeadScoringService()

    with pytest.raises(LeadScoringError, match="limit must be >= 1"):
        service.score_batch(db_session, limit=0)


def test_batch_max_is_conservative() -> None:
    assert BATCH_MAX == 500


def test_scoring_job_is_not_an_outbound_action() -> None:
    assert outbound_action_for_job(SCORE_DISCOVERED_LEADS_JOB) is None


def test_scoring_modules_do_not_import_outbound_or_enrichment_providers() -> None:
    files = [
        Path("src/vyro_growth/services/lead_scoring.py"),
        Path("src/vyro_growth/workers/scoring_handler.py"),
    ]
    forbidden = {
        "httpx",
        "openai",
        "apollo",
        "smartlead",
        "firecrawl",
        "twilio",
        "vapi",
        "vyro_growth.providers.nppes_client",
        "vyro_growth.providers.stubs",
        "vyro_growth.providers.guarded",
    }
    imported: set[str] = set()
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
    assert imported.isdisjoint(forbidden)
    source = "\n".join(path.read_text(encoding="utf-8") for path in files).lower()
    forbidden_tokens = (
        "apollo",
        "smartlead",
        "openai",
        "firecrawl",
        "twilio",
        "vapi",
        "google.calendar",
    )
    for token in forbidden_tokens:
        assert token not in source
