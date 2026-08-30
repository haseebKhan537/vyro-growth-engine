from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tests.fixtures.personalization import invented_payload
from vyro_growth.domain import (
    EnrichmentRunStatus,
    PersonalizationFactType,
    PersonalizationReadiness,
)
from vyro_growth.models import (
    Activity,
    Contact,
    EnrichmentRun,
    Lead,
    Organization,
    OutreachMessage,
    PersonalizationDraft,
    SourceEvidence,
)
from vyro_growth.providers.personalization import (
    DEFAULT_OFFER,
    MalformedPersonalizationOutput,
    NonRetryablePersonalizationError,
    RetryablePersonalizationError,
    StaticPersonalizationProvider,
    StubPersonalizationProvider,
)
from vyro_growth.services.lead_scoring import LeadScoringService
from vyro_growth.services.personalization import PersonalizationError, PersonalizationService
from vyro_growth.workers.outbound import outbound_action_for_job
from vyro_growth.workers.personalization_handler import PERSONALIZE_SCORED_LEADS_JOB


def _org(db: Session, **overrides: object) -> Organization:
    values: dict[str, object] = {
        "name": "AUSTIN FAMILY MEDICINE PLLC",
        "npi": "1487448189",
        "city": "AUSTIN",
        "state": "TX",
        "specialty": "Family Medicine",
        "website": "https://austinfamily.example",
        "website_match_status": "verified",
    }
    values.update(overrides)
    organization = Organization(**values)
    db.add(organization)
    db.flush()
    return organization


def _seed_scored_lead(db: Session, organization: Organization) -> Lead:
    db.add(
        SourceEvidence(
            organization_id=organization.id,
            source_url="https://npiregistry.cms.hhs.gov/api/",
            claim_type="nppes_organization_record",
            extracted_value=organization.name,
            metadata_json={"business_record": {"status": "A"}},
        )
    )
    db.add(
        SourceEvidence(
            organization_id=organization.id,
            source_url="https://austinfamily.example/about",
            claim_type="ownership_signal",
            extracted_value="independent",
            evidence_snippet="independently owned practice",
            confidence=0.84,
            metadata_json={"fabricated": False},
        )
    )
    db.add(
        SourceEvidence(
            organization_id=organization.id,
            source_url="https://austinfamily.example/billing",
            claim_type="billing_signal",
            extracted_value="in-house billing",
            evidence_snippet="our billing department handles claims",
            confidence=0.8,
            metadata_json={"fabricated": False},
        )
    )
    db.add(
        Contact(
            organization_id=organization.id,
            full_name="Jordan Blake",
            title="Practice Manager",
            role_category="practice_manager",
            email_verified=False,
        )
    )
    db.flush()
    result = LeadScoringService().score_organization(db, organization.id)
    lead = db.get(Lead, result.lead_id)
    assert lead is not None
    return lead


def test_success_persists_evidence_grounded_draft(db_session: Session) -> None:
    organization = _org(db_session)
    lead = _seed_scored_lead(db_session, organization)
    service = PersonalizationService(StubPersonalizationProvider())

    result = service.personalize_lead(db_session, lead.id)

    assert result.status is EnrichmentRunStatus.COMPLETED
    assert result.outbound_attempted is False
    assert result.live_call_attempted is False
    assert result.reused_existing_draft is False
    assert result.readiness_status is PersonalizationReadiness.READY
    assert result.draft_id is not None
    draft = db_session.get(PersonalizationDraft, result.draft_id)
    assert draft is not None
    assert draft.suggested_offer == DEFAULT_OFFER
    assert "AUSTIN FAMILY MEDICINE PLLC" in draft.practice_summary
    assert draft.audit_json["live_call_attempted"] is False
    assert draft.audit_json["prompt_version"]
    assert draft.evidence_references
    assert db_session.scalar(select(OutreachMessage)) is None
    evidence = db_session.scalar(
        select(SourceEvidence).where(
            SourceEvidence.claim_type == PersonalizationFactType.PERSONALIZATION_DRAFT.value
        )
    )
    assert evidence is not None
    assert evidence.personalization_draft_id == draft.id
    assert evidence.metadata_json["fabricated"] is False
    activity = db_session.scalar(
        select(Activity).where(Activity.action == "personalization_completed")
    )
    assert activity is not None
    assert activity.details["outbound_attempted"] is False
    assert activity.details["fabricated_facts"] is False


def test_missing_evidence_marks_needs_more_evidence_without_inventing(
    db_session: Session,
) -> None:
    organization = _org(
        db_session,
        specialty=None,
        city=None,
        state=None,
        website=None,
        npi=None,
        website_match_status=None,
    )
    lead = Lead(organization_id=organization.id, stage="discovered", source="local")
    db_session.add(lead)
    db_session.flush()
    service = PersonalizationService(StubPersonalizationProvider())

    result = service.personalize_lead(db_session, lead.id)

    assert result.status is EnrichmentRunStatus.COMPLETED
    assert result.readiness_status is PersonalizationReadiness.NEEDS_MORE_EVIDENCE
    draft = db_session.get(PersonalizationDraft, result.draft_id)
    assert draft is not None
    notes = " ".join(str(item) for item in draft.missing_data_notes)
    assert "specialty" in notes
    assert "denial" not in draft.practice_summary.lower()
    assert "payer mix" not in draft.why_vyro_relevant.lower()
    assert db_session.scalar(select(OutreachMessage)) is None


def test_malformed_provider_output_fails_without_draft(db_session: Session) -> None:
    organization = _org(db_session)
    lead = _seed_scored_lead(db_session, organization)
    service = PersonalizationService(StaticPersonalizationProvider({"nope": True}))

    result = service.personalize_lead(db_session, lead.id)

    assert result.status is EnrichmentRunStatus.FAILED
    assert result.draft_id is None
    assert db_session.scalar(select(PersonalizationDraft)) is None
    run = db_session.get(EnrichmentRun, result.enrichment_run_id)
    assert run is not None
    assert run.status == EnrichmentRunStatus.FAILED.value
    activity = db_session.scalar(
        select(Activity).where(Activity.action == "personalization_failed")
    )
    assert activity is not None
    assert activity.details["failure_kind"] == "malformed_output"
    assert activity.details["outbound_attempted"] is False


def test_ungrounded_invented_facts_fail_the_run(db_session: Session) -> None:
    organization = _org(db_session)
    lead = _seed_scored_lead(db_session, organization)
    service = PersonalizationService(StaticPersonalizationProvider(invented_payload()))

    result = service.personalize_lead(db_session, lead.id)

    assert result.status is EnrichmentRunStatus.FAILED
    assert db_session.scalar(select(PersonalizationDraft)) is None
    activity = db_session.scalar(
        select(Activity).where(Activity.action == "personalization_failed")
    )
    assert activity is not None
    assert activity.details["failure_kind"] == "malformed_output"


def test_retryable_provider_failure_is_recorded(db_session: Session) -> None:
    organization = _org(db_session)
    lead = _seed_scored_lead(db_session, organization)
    service = PersonalizationService(
        StaticPersonalizationProvider(error=RetryablePersonalizationError("rate limited"))
    )

    result = service.personalize_lead(db_session, lead.id)

    assert result.status is EnrichmentRunStatus.FAILED
    run = db_session.get(EnrichmentRun, result.enrichment_run_id)
    assert run is not None
    assert run.input_params["retryable"] is True
    assert db_session.scalar(select(PersonalizationDraft)) is None


def test_non_retryable_provider_failure_is_recorded(db_session: Session) -> None:
    organization = _org(db_session)
    lead = _seed_scored_lead(db_session, organization)
    service = PersonalizationService(
        StaticPersonalizationProvider(error=NonRetryablePersonalizationError("unauthorized"))
    )

    result = service.personalize_lead(db_session, lead.id)

    assert result.status is EnrichmentRunStatus.FAILED
    run = db_session.get(EnrichmentRun, result.enrichment_run_id)
    assert run is not None
    assert run.input_params["retryable"] is False
    activity = db_session.scalar(
        select(Activity).where(Activity.action == "personalization_failed")
    )
    assert activity is not None
    assert activity.details["failure_kind"] == "non_retryable"


def test_rerun_is_idempotent_and_does_not_duplicate_drafts(db_session: Session) -> None:
    organization = _org(db_session)
    lead = _seed_scored_lead(db_session, organization)
    service = PersonalizationService(StubPersonalizationProvider())

    first = service.personalize_lead(db_session, lead.id)
    second = service.personalize_lead(db_session, lead.id)

    assert first.draft_id == second.draft_id
    assert second.reused_existing_draft is True
    draft_count = db_session.scalar(select(func.count()).select_from(PersonalizationDraft))
    assert draft_count == 1
    run_count = db_session.scalar(
        select(func.count())
        .select_from(EnrichmentRun)
        .where(EnrichmentRun.source == "personalization")
    )
    assert run_count == 2
    reused = db_session.scalar(select(Activity).where(Activity.action == "personalization_reused"))
    assert reused is not None
    assert reused.details["outbound_attempted"] is False
    assert db_session.scalar(select(OutreachMessage)) is None


def test_personalize_unknown_lead_raises(db_session: Session) -> None:
    service = PersonalizationService(StubPersonalizationProvider())
    with pytest.raises(PersonalizationError, match="Lead not found"):
        service.personalize_lead(db_session, uuid4())


def test_personalization_job_is_not_an_outbound_action() -> None:
    assert outbound_action_for_job(PERSONALIZE_SCORED_LEADS_JOB) is None


def test_malformed_error_type_is_non_retryable() -> None:
    error = MalformedPersonalizationOutput("bad json")
    assert error.retryable is False
