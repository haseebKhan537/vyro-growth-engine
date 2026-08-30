from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from vyro_growth.domain import (
    ContactFactType,
    ContactRoleCategory,
    WebsiteFactType,
    WebsiteMatchStatus,
)
from vyro_growth.models import (
    Activity,
    Contact,
    Lead,
    LeadScore,
    Organization,
    OutreachMessage,
    SourceEvidence,
)
from vyro_growth.services.lead_scoring import (
    FactorCode,
    FactorStatus,
    LeadScoringService,
    ReasonCode,
    ScoreBand,
    ScoreFactor,
    ScoringResult,
    ScoringSnapshot,
    score_snapshot,
)


def _factor(result: ScoringResult, code: FactorCode) -> ScoreFactor:
    matches = [item for item in result.factors if item.code is code]
    assert len(matches) == 1
    return matches[0]


def _enriched_snapshot(**overrides: object) -> ScoringSnapshot:
    payload: dict[str, object] = {
        "organization_name": "AUSTIN FAMILY MEDICINE PLLC",
        "npi": "1487448189",
        "city": "AUSTIN",
        "state": "TX",
        "specialty": "Family Medicine",
        "website": "https://austinfamily.example",
        "nppes_status": "A",
        "has_nppes_evidence": True,
        "nppes_source_url": "https://npiregistry.cms.hhs.gov/api/",
        "verified_email": True,
        "has_contact_email": True,
        "has_contact_phone": True,
        "decision_maker_title": "Practice Manager",
        "decision_maker_role": ContactRoleCategory.PRACTICE_MANAGER.value,
        "website_match_status": WebsiteMatchStatus.VERIFIED.value,
        "website_facts_eligible": True,
        "ownership_value": "independent",
        "practice_size_value": "single_location",
        "provider_count_value": "3",
        "billing_value": "in-house_billing",
        "business_phone": "5125550100",
        "business_email": "info@austinfamily.example",
    }
    payload.update(overrides)
    return ScoringSnapshot(**payload)  # type: ignore[arg-type]


def test_full_icp_evidence_scores_hot() -> None:
    result = score_snapshot(_enriched_snapshot())

    assert result.total == 100
    assert result.band is ScoreBand.HOT
    assert _factor(result, FactorCode.WEBSITE_MATCH).reason_code is ReasonCode.POS_WEBSITE_VERIFIED
    assert _factor(result, FactorCode.OWNERSHIP_SIGNAL).reason_code is (
        ReasonCode.POS_INDEPENDENT_OWNERSHIP
    )
    assert _factor(result, FactorCode.BILLING_SIGNAL).points == 6
    assert ReasonCode.POS_TARGET_SPECIALTY.value in result.reason_codes
    assert result.disqualification_codes == ()
    assert result.fabricated_facts is False


def test_score_bands_cover_priority_ladder() -> None:
    hot = score_snapshot(_enriched_snapshot())
    high = score_snapshot(
        ScoringSnapshot(
            organization_name="AUSTIN FAMILY MEDICINE PLLC",
            npi="1487448189",
            city="AUSTIN",
            state="TX",
            specialty="Family Medicine",
            website="https://austinfamily.example",
            nppes_status="A",
            has_nppes_evidence=True,
            nppes_source_url="https://npiregistry.cms.hhs.gov/api/",
            verified_email=True,
            has_contact_email=True,
            decision_maker_title="Practice Manager",
        )
    )
    medium = score_snapshot(
        ScoringSnapshot(
            organization_name="AUSTIN FAMILY MEDICINE PLLC",
            npi="1487448189",
            city="AUSTIN",
            state="TX",
            specialty="Family Medicine",
            has_nppes_evidence=True,
            nppes_status="A",
            nppes_source_url="https://npiregistry.cms.hhs.gov/api/",
        )
    )
    low = score_snapshot(
        ScoringSnapshot(
            organization_name="AUSTIN CLINIC",
            npi="1487448189",
            specialty="Acupuncture",
            state="TX",
        )
    )
    research = score_snapshot(
        ScoringSnapshot(
            organization_name="AUSTIN CLINIC",
            npi="1487448189",
            state="TX",
            city="AUSTIN",
        )
    )
    disqualified = score_snapshot(
        _enriched_snapshot(
            specialty="General Acute Care Hospital",
            organization_name="AUSTIN HOSPITAL",
        )
    )

    assert hot.band is ScoreBand.HOT
    assert high.band is ScoreBand.HIGH
    assert medium.band is ScoreBand.MEDIUM
    assert low.band is ScoreBand.LOW
    assert research.band is ScoreBand.RESEARCH
    assert disqualified.band is ScoreBand.DISQUALIFIED


def test_ambiguous_website_skips_website_facts() -> None:
    result = score_snapshot(
        _enriched_snapshot(
            website_match_status=WebsiteMatchStatus.AMBIGUOUS.value,
            website_facts_eligible=False,
        )
    )

    assert _factor(result, FactorCode.WEBSITE_MATCH).status is FactorStatus.AMBIGUOUS
    assert _factor(result, FactorCode.WEBSITE_MATCH).reason_code is ReasonCode.NEG_WEBSITE_AMBIGUOUS
    assert _factor(result, FactorCode.OWNERSHIP_SIGNAL).points == 0
    assert _factor(result, FactorCode.OWNERSHIP_SIGNAL).status is FactorStatus.AMBIGUOUS
    assert _factor(result, FactorCode.BILLING_SIGNAL).points == 0
    assert _factor(result, FactorCode.PROVIDER_COUNT).points == 0
    assert _factor(result, FactorCode.PRACTICE_SIZE_SIGNAL).reason_code is (
        ReasonCode.INFO_WEBSITE_FACTS_SKIPPED
    )
    assert result.band is not ScoreBand.HOT


def test_conflicting_ownership_is_not_assumed() -> None:
    result = score_snapshot(
        _enriched_snapshot(
            ownership_value=None,
            ownership_conflict=True,
        )
    )

    ownership = _factor(result, FactorCode.OWNERSHIP_SIGNAL)
    assert ownership.points == 0
    assert ownership.status is FactorStatus.CONFLICTING
    assert ownership.reason_code is ReasonCode.INFO_CONFLICTING_OWNERSHIP
    assert "not assumed" in ownership.reason


def test_conflicting_provider_count_is_not_assumed() -> None:
    result = score_snapshot(
        _enriched_snapshot(
            provider_count_value=None,
            provider_count_conflict=True,
        )
    )

    count = _factor(result, FactorCode.PROVIDER_COUNT)
    assert count.points == 0
    assert count.status is FactorStatus.CONFLICTING
    assert count.reason_code is ReasonCode.INFO_CONFLICTING_PROVIDER_COUNT


def test_conflicting_size_and_count_skip_both_signals() -> None:
    result = score_snapshot(
        _enriched_snapshot(
            practice_size_value="small_practice",
            provider_count_value="40",
        )
    )

    size = _factor(result, FactorCode.PRACTICE_SIZE_SIGNAL)
    count = _factor(result, FactorCode.PROVIDER_COUNT)
    assert size.points == 0
    assert count.points == 0
    assert size.status is FactorStatus.CONFLICTING
    assert count.status is FactorStatus.CONFLICTING
    assert size.reason_code is ReasonCode.INFO_CONFLICTING_SIZE_AND_COUNT


def test_unclassified_billing_phrase_is_not_scored() -> None:
    result = score_snapshot(_enriched_snapshot(billing_value="we accept most insurance"))

    billing = _factor(result, FactorCode.BILLING_SIGNAL)
    assert billing.points == 0
    assert billing.reason_code is ReasonCode.INFO_UNCLASSIFIED_SIGNAL
    assert "not assumed" in billing.reason


def test_missing_practice_size_is_not_inferred() -> None:
    result = score_snapshot(_enriched_snapshot(practice_size_value=None, provider_count_value=None))

    size = _factor(result, FactorCode.PRACTICE_SIZE_SIGNAL)
    count = _factor(result, FactorCode.PROVIDER_COUNT)
    assert size.points == 0
    assert count.points == 0
    assert size.status is FactorStatus.MISSING
    assert count.status is FactorStatus.MISSING


def test_larger_group_applies_negative_reason_without_inventing_parent() -> None:
    result = score_snapshot(_enriched_snapshot(ownership_value="larger_group:Regional Health"))

    ownership = _factor(result, FactorCode.OWNERSHIP_SIGNAL)
    assert ownership.points == -10
    assert ownership.reason_code is ReasonCode.NEG_LARGER_GROUP
    assert ownership.observed_value == "larger_group:Regional Health"
    assert result.band is not ScoreBand.DISQUALIFIED


def test_ranked_contact_role_counts_and_unverified_email_does_not() -> None:
    result = score_snapshot(
        _enriched_snapshot(
            verified_email=False,
            has_contact_email=True,
            decision_maker_role=ContactRoleCategory.OWNER_PHYSICIAN_OWNER.value,
            decision_maker_title="Physician Owner",
        )
    )

    role = _factor(result, FactorCode.DECISION_MAKER_TITLE)
    email = _factor(result, FactorCode.VERIFIED_EMAIL)
    assert role.points == 6
    assert role.observed_value == ContactRoleCategory.OWNER_PHYSICIAN_OWNER.value
    assert email.points == 0
    assert email.reason_code is ReasonCode.INFO_UNVERIFIED_EMAIL


def test_public_business_contact_counts_only_when_stored() -> None:
    missing = score_snapshot(
        _enriched_snapshot(
            business_phone=None,
            business_email=None,
            has_contact_phone=False,
            has_contact_email=False,
            verified_email=False,
        )
    )
    stored = score_snapshot(_enriched_snapshot())

    assert _factor(missing, FactorCode.BUSINESS_PHONE).status is FactorStatus.MISSING
    assert _factor(missing, FactorCode.BUSINESS_EMAIL).status is FactorStatus.MISSING
    assert _factor(stored, FactorCode.BUSINESS_PHONE).points == 3
    assert _factor(stored, FactorCode.BUSINESS_EMAIL).points == 3


def _seed_organization(
    db: Session,
    *,
    name: str = "AUSTIN FAMILY MEDICINE PLLC",
    npi: str | None = "1487448189",
    specialty: str | None = "Family Medicine",
    website: str | None = "https://austinfamily.example",
    website_match_status: str | None = WebsiteMatchStatus.VERIFIED.value,
) -> Organization:
    organization = Organization(
        name=name,
        npi=npi,
        city="AUSTIN",
        state="TX",
        specialty=specialty,
        website=website,
        website_match_status=website_match_status,
    )
    db.add(organization)
    db.flush()
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


def _add_fact(
    db: Session,
    organization: Organization,
    claim_type: str,
    value: str,
    source_url: str = "https://austinfamily.example",
) -> SourceEvidence:
    row = SourceEvidence(
        organization_id=organization.id,
        source_url=source_url,
        claim_type=claim_type,
        extracted_value=value,
        confidence=0.84,
        evidence_snippet=f"evidence for {value}",
        metadata_json={"fabricated": False},
    )
    db.add(row)
    db.flush()
    return row


def test_persisted_score_links_material_reasons_to_source_evidence(db_session: Session) -> None:
    organization = _seed_organization(db_session)
    match_row = _add_fact(
        db_session,
        organization,
        WebsiteFactType.WEBSITE_MATCH.value,
        WebsiteMatchStatus.VERIFIED.value,
    )
    ownership_row = _add_fact(
        db_session,
        organization,
        WebsiteFactType.OWNERSHIP_SIGNAL.value,
        "independent",
    )
    billing_row = _add_fact(
        db_session,
        organization,
        WebsiteFactType.BILLING_SIGNAL.value,
        "in-house_billing",
    )
    service = LeadScoringService()

    result = service.score_organization(db_session, organization.id)
    match = _factor(result.scoring, FactorCode.WEBSITE_MATCH)
    ownership = _factor(result.scoring, FactorCode.OWNERSHIP_SIGNAL)
    billing = _factor(result.scoring, FactorCode.BILLING_SIGNAL)

    assert match.evidence_id == str(match_row.id)
    assert match.source_url == match_row.source_url
    assert ownership.evidence_id == str(ownership_row.id)
    assert billing.evidence_id == str(billing_row.id)
    assert billing.claim_type == WebsiteFactType.BILLING_SIGNAL.value


def test_conflicting_stored_ownership_is_linked_and_unscored(db_session: Session) -> None:
    organization = _seed_organization(db_session)
    _add_fact(db_session, organization, WebsiteFactType.WEBSITE_MATCH.value, "verified")
    first = _add_fact(
        db_session,
        organization,
        WebsiteFactType.OWNERSHIP_SIGNAL.value,
        "independent",
    )
    _add_fact(
        db_session,
        organization,
        WebsiteFactType.OWNERSHIP_SIGNAL.value,
        "larger_group:Health System",
    )
    service = LeadScoringService()

    result = service.score_organization(db_session, organization.id)
    ownership = _factor(result.scoring, FactorCode.OWNERSHIP_SIGNAL)

    assert ownership.points == 0
    assert ownership.status is FactorStatus.CONFLICTING
    assert ownership.evidence_id == str(first.id) or ownership.evidence_id is not None
    assert ownership.reason_code is ReasonCode.INFO_CONFLICTING_OWNERSHIP


def test_contact_enrichment_evidence_is_used_without_inventing_people(db_session: Session) -> None:
    organization = _seed_organization(db_session)
    _add_fact(db_session, organization, WebsiteFactType.WEBSITE_MATCH.value, "verified")
    contact = Contact(
        organization_id=organization.id,
        full_name="Alex Admin",
        title="Practice Administrator",
        email="alex@clinic.example",
        email_verified=False,
        role_category=ContactRoleCategory.PRACTICE_ADMINISTRATOR.value,
        role_rank=2,
        verification_status="unverified",
    )
    db_session.add(contact)
    db_session.flush()
    evidence = SourceEvidence(
        organization_id=organization.id,
        contact_id=contact.id,
        source_url="provider:static",
        claim_type=ContactFactType.DECISION_MAKER_CONTACT.value,
        extracted_value=contact.full_name,
        metadata_json={"role_category": contact.role_category, "fabricated": False},
    )
    db_session.add(evidence)
    db_session.flush()
    service = LeadScoringService()

    result = service.score_organization(db_session, organization.id)
    role = _factor(result.scoring, FactorCode.DECISION_MAKER_TITLE)
    email = _factor(result.scoring, FactorCode.VERIFIED_EMAIL)

    assert role.points == 6
    assert role.observed_value == ContactRoleCategory.PRACTICE_ADMINISTRATOR.value
    assert role.evidence_id == str(evidence.id)
    assert email.points == 0


def test_scoring_rerun_is_idempotent_and_creates_no_outreach(db_session: Session) -> None:
    organization = _seed_organization(db_session)
    _add_fact(db_session, organization, WebsiteFactType.WEBSITE_MATCH.value, "verified")
    service = LeadScoringService()

    first = service.score_organization(db_session, organization.id)
    second = service.score_organization(db_session, organization.id)

    score_count = db_session.scalar(select(func.count()).select_from(LeadScore))
    activity_count = db_session.scalar(
        select(func.count()).select_from(Activity).where(Activity.action == "lead_scored")
    )
    lead_count = db_session.scalar(
        select(func.count()).select_from(Lead).where(Lead.organization_id == organization.id)
    )
    outreach_count = db_session.scalar(select(func.count()).select_from(OutreachMessage))

    assert first.reused_existing_score is False
    assert second.reused_existing_score is True
    assert second.lead_score_id == first.lead_score_id
    assert second.lead_id == first.lead_id
    assert score_count == 1
    assert activity_count == 1
    assert lead_count == 1
    assert outreach_count == 0
    assert first.scoring.fabricated_facts is False
    assert first.scoring.external_providers_called == ()


def test_changed_evidence_writes_new_score_without_outbound(db_session: Session) -> None:
    organization = _seed_organization(db_session)
    _add_fact(db_session, organization, WebsiteFactType.WEBSITE_MATCH.value, "verified")
    service = LeadScoringService()
    first = service.score_organization(db_session, organization.id)

    _add_fact(db_session, organization, WebsiteFactType.OWNERSHIP_SIGNAL.value, "independent")
    second = service.score_organization(db_session, organization.id)

    score_count = db_session.scalar(select(func.count()).select_from(LeadScore))
    outreach_count = db_session.scalar(select(func.count()).select_from(OutreachMessage))
    lead = db_session.get(Lead, first.lead_id)

    assert second.reused_existing_score is False
    assert second.lead_score_id != first.lead_score_id
    assert score_count == 2
    assert outreach_count == 0
    assert lead is not None
    assert lead.stage == "discovered"


def test_disqualified_hospital_is_not_auto_qualified(db_session: Session) -> None:
    organization = _seed_organization(
        db_session,
        name="AUSTIN GENERAL HOSPITAL",
        specialty="General Acute Care Hospital",
        website_match_status=None,
        website=None,
    )
    service = LeadScoringService()

    result = service.score_organization(db_session, organization.id)
    lead = db_session.get(Lead, result.lead_id)

    assert result.scoring.band is ScoreBand.DISQUALIFIED
    assert lead is not None
    assert lead.stage == "discovered"
    assert db_session.scalar(select(func.count()).select_from(OutreachMessage)) == 0
