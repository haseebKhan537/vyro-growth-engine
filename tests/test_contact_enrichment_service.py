from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from tests.fixtures.decision_makers import candidate
from vyro_growth.domain import (
    ContactFactType,
    ContactRoleCategory,
    ContactVerificationStatus,
    EnrichmentRunStatus,
)
from vyro_growth.models import (
    Activity,
    Contact,
    EnrichmentRun,
    Organization,
    OutreachMessage,
    SourceEvidence,
)
from vyro_growth.providers.decision_makers import (
    StaticDecisionMakerEnrichmentProvider,
    StubDecisionMakerEnrichmentProvider,
)
from vyro_growth.services.contact_enrichment import (
    ContactEnrichmentError,
    ContactEnrichmentService,
)


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


def _service(candidates: list[object] | None = None) -> ContactEnrichmentService:
    provider: StaticDecisionMakerEnrichmentProvider | StubDecisionMakerEnrichmentProvider
    if candidates is None:
        provider = StubDecisionMakerEnrichmentProvider()
    else:
        provider = StaticDecisionMakerEnrichmentProvider(candidates)
    return ContactEnrichmentService(provider)


def test_happy_path_persists_ranked_professional_contacts(db_session: Session) -> None:
    organization = _org(db_session)
    db_session.add(
        SourceEvidence(
            organization_id=organization.id,
            source_url="https://austinfamily.example",
            claim_type="ownership_signal",
            extracted_value="independent",
            confidence=0.84,
            evidence_snippet="independently owned practice",
            metadata_json={"fabricated": False},
        )
    )
    db_session.flush()
    service = _service(
        [
            candidate(
                full_name="Ops Person",
                title="Operations Manager",
                business_email="ops@austinfamily.example",
            ),
            candidate(
                full_name="Owner Person",
                title="Physician Owner",
                business_email="owner@austinfamily.example",
            ),
            candidate(
                full_name="Office Person",
                title="Office Manager",
                business_email="office@austinfamily.example",
            ),
        ]
    )

    result = service.enrich_organization(db_session, organization.id)

    assert result.status is EnrichmentRunStatus.COMPLETED
    assert result.contacts_upserted == 3
    assert result.provider_name == "static"
    contacts = db_session.scalars(
        select(Contact)
        .where(Contact.organization_id == organization.id)
        .order_by(Contact.role_rank.asc())
    ).all()
    assert [row.full_name for row in contacts] == ["Owner Person", "Office Person", "Ops Person"]
    assert [row.role_category for row in contacts] == [
        ContactRoleCategory.OWNER_PHYSICIAN_OWNER.value,
        ContactRoleCategory.OFFICE_MANAGER.value,
        ContactRoleCategory.OPERATIONS_MANAGER.value,
    ]
    owner = contacts[0]
    assert owner.email == "owner@austinfamily.example"
    assert owner.source_provider == "static"
    assert owner.source_timestamp is not None
    assert owner.confidence == 0.82
    assert owner.verification_status == ContactVerificationStatus.UNVERIFIED.value
    assert owner.email_verified is False
    assert owner.provenance_json["source_url"] == "https://provider.example/people/jblake"
    assert owner.provenance_json["fabricated"] is False

    evidence = db_session.scalars(
        select(SourceEvidence).where(
            SourceEvidence.claim_type == ContactFactType.DECISION_MAKER_CONTACT.value
        )
    ).all()
    assert len(evidence) == 3
    for row in evidence:
        assert row.source_url
        assert row.contact_id is not None
        assert row.enrichment_run_id == result.enrichment_run_id
        assert row.metadata_json["fabricated"] is False

    activity = db_session.scalar(
        select(Activity).where(Activity.action == "decision_maker_enrichment_completed")
    )
    assert activity is not None
    assert activity.details["fabricated_facts"] is False
    assert activity.details["outbound_attempted"] is False
    assert db_session.scalar(select(OutreachMessage)) is None


def test_stub_provider_persists_no_invented_contacts(db_session: Session) -> None:
    organization = _org(db_session)
    result = _service().enrich_organization(db_session, organization.id)
    assert result.contacts_upserted == 0
    assert result.candidates_considered == 0
    assert db_session.scalar(select(Contact)) is None
    run = db_session.get(EnrichmentRun, result.enrichment_run_id)
    assert run is not None
    assert run.source == "decision_maker"
    assert run.status == EnrichmentRunStatus.COMPLETED.value


def test_missing_optional_fields_remain_unknown(db_session: Session) -> None:
    organization = _org(db_session)
    result = _service(
        [
            candidate(
                full_name="Taylor Ng",
                title="Practice Administrator",
                business_email=None,
                business_phone=None,
                confidence=None,
                verification_status=ContactVerificationStatus.UNKNOWN,
            )
        ]
    ).enrich_organization(db_session, organization.id)
    contact = db_session.scalar(select(Contact))
    assert result.contacts_upserted == 1
    assert contact is not None
    assert contact.email is None
    assert contact.phone is None
    assert contact.confidence is None
    assert contact.verification_status == ContactVerificationStatus.UNKNOWN.value
    assert contact.email_verified is False


def test_duplicates_are_deduped_across_reruns(db_session: Session) -> None:
    organization = _org(db_session)
    service = _service(
        [
            candidate(full_name="Jordan Blake", title="Practice Manager"),
            candidate(full_name="Jordan Blake", title="Practice Manager"),
        ]
    )
    first = service.enrich_organization(db_session, organization.id)
    second = service.enrich_organization(db_session, organization.id)
    contacts = db_session.scalars(select(Contact)).all()
    assert first.contacts_upserted == 1
    assert second.contacts_upserted == 1
    assert len(contacts) == 1
    runs = db_session.scalars(
        select(EnrichmentRun).where(EnrichmentRun.source == "decision_maker")
    ).all()
    assert len(runs) == 2
    evidence = db_session.scalars(
        select(SourceEvidence).where(
            SourceEvidence.claim_type == ContactFactType.DECISION_MAKER_CONTACT.value
        )
    ).all()
    assert len(evidence) == 2


def test_idempotent_rerun_fills_sparse_email_without_wiping(db_session: Session) -> None:
    organization = _org(db_session)
    first = ContactEnrichmentService(
        StaticDecisionMakerEnrichmentProvider(
            (candidate(business_email=None, business_phone="512-555-0100"),)
        )
    ).enrich_organization(db_session, organization.id)
    second = ContactEnrichmentService(
        StaticDecisionMakerEnrichmentProvider(
            (candidate(business_phone=None, business_email="jblake@austinfamily.example"),)
        )
    ).enrich_organization(db_session, organization.id)
    contact = db_session.scalar(select(Contact))
    assert first.contacts_upserted == 1
    assert second.contacts_upserted == 1
    assert contact is not None
    assert contact.email == "jblake@austinfamily.example"
    assert contact.phone == "512-555-0100"


def test_irrelevant_roles_are_not_persisted(db_session: Session) -> None:
    organization = _org(db_session)
    result = _service(
        [
            candidate(full_name="Sam Rivera", title="Family Physician, MD"),
            candidate(full_name="Riley Nurse", title="Registered Nurse"),
            candidate(full_name="Pat Front", title="Front Desk Coordinator"),
        ]
    ).enrich_organization(db_session, organization.id)
    assert result.contacts_upserted == 0
    assert result.contacts_skipped == 3
    assert db_session.scalar(select(Contact)) is None
    activity = db_session.scalar(
        select(Activity).where(Activity.action == "decision_maker_enrichment_completed")
    )
    assert activity is not None
    reasons = {item["reason"] for item in activity.details["skip_reasons"]}
    assert "irrelevant_clinical" in reasons
    assert "unknown_role" in reasons


def test_malformed_provider_results_are_skipped(db_session: Session) -> None:
    organization = _org(db_session)
    result = _service(
        [
            {},
            {"full_name": "A", "source_provider": "static"},
            candidate(full_name="Valid Manager", title="Practice Manager"),
            candidate(confidence=9.0),
            candidate(business_email="nope"),
        ]
    ).enrich_organization(db_session, organization.id)
    contacts = db_session.scalars(select(Contact)).all()
    assert [row.full_name for row in contacts] == ["Valid Manager"]
    assert result.contacts_upserted == 1
    assert result.contacts_skipped >= 4
    assert result.candidates_considered == 5


def test_confidence_and_provenance_are_persisted(db_session: Session) -> None:
    organization = _org(db_session)
    _service(
        [
            candidate(
                confidence=0.91,
                verification_status=ContactVerificationStatus.PROVIDER_VERIFIED,
                source_url="https://provider.example/record/1",
                evidence_snippet="Practice Manager at Austin Family Medicine",
            )
        ]
    ).enrich_organization(db_session, organization.id)
    contact = db_session.scalar(select(Contact))
    evidence = db_session.scalar(
        select(SourceEvidence).where(
            SourceEvidence.claim_type == ContactFactType.DECISION_MAKER_CONTACT.value
        )
    )
    assert contact is not None
    assert contact.confidence == 0.91
    assert contact.email_verified is True
    snippet = "Practice Manager at Austin Family Medicine"
    assert contact.provenance_json["evidence_snippet"] == snippet
    assert evidence is not None
    assert evidence.confidence == 0.91
    assert evidence.source_url == "https://provider.example/record/1"


def test_no_outbound_side_effects(db_session: Session) -> None:
    organization = _org(db_session)
    provider = StaticDecisionMakerEnrichmentProvider((candidate(),))
    ContactEnrichmentService(provider).enrich_organization(db_session, organization.id)
    assert db_session.scalar(select(OutreachMessage)) is None
    assert len(provider.requests) == 1
    request = provider.requests[0]
    assert request.organization.organization_id == organization.id
    assert request.organization.website == "https://austinfamily.example"
    from vyro_growth.config import Settings

    assert Settings().outbound_enabled is False


def test_website_context_is_passed_to_provider(db_session: Session) -> None:
    organization = _org(db_session)
    db_session.add(
        SourceEvidence(
            organization_id=organization.id,
            source_url="https://austinfamily.example",
            claim_type="ownership_signal",
            extracted_value="independent",
            metadata_json={},
        )
    )
    db_session.flush()
    provider = StaticDecisionMakerEnrichmentProvider(
        (candidate(full_name="Lee Chen", title="CEO", business_email="lee@austinfamily.example"),)
    )
    result = ContactEnrichmentService(provider).enrich_organization(db_session, organization.id)
    assert result.contacts_upserted == 1
    facts = provider.requests[0].organization.website_facts
    assert any(item.value == "independent" for item in facts)


def test_missing_organization_raises(db_session: Session) -> None:
    with pytest.raises(ContactEnrichmentError, match="not found"):
        _service([]).enrich_organization(db_session, uuid4())


def test_batch_respects_limit(db_session: Session) -> None:
    first = _org(db_session, npi="1000000001")
    _org(db_session, npi="1000000002")
    results = _service([candidate()]).enrich_batch(db_session, limit=1)
    assert len(results) == 1
    assert results[0].organization_id == first.id
