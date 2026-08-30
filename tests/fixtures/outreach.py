from __future__ import annotations

from uuid import uuid4

from sqlalchemy.orm import Session

from vyro_growth.domain import LeadStage, PersonalizationReadiness
from vyro_growth.models import Contact, Lead, LeadScore, Organization, PersonalizationDraft


def sample_organization(db: Session, **overrides: object) -> Organization:
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


def sample_contact(db: Session, organization: Organization, **overrides: object) -> Contact:
    values: dict[str, object] = {
        "organization_id": organization.id,
        "full_name": "Jordan Blake",
        "title": "Practice Manager",
        "email": "jordan.blake@austinfamily.example",
        "role_category": "practice_manager",
        "role_rank": 3,
        "email_verified": False,
        "dedupe_key": "email:jordan.blake@austinfamily.example",
    }
    values.update(overrides)
    contact = Contact(**values)
    db.add(contact)
    db.flush()
    return contact


def sample_lead(
    db: Session,
    organization: Organization,
    *,
    stage: LeadStage = LeadStage.READY_FOR_OUTREACH,
) -> Lead:
    lead = Lead(
        organization_id=organization.id,
        stage=stage.value,
        source="nppes",
    )
    db.add(lead)
    db.flush()
    return lead


def sample_score(
    db: Session,
    lead: Lead,
    *,
    total: int = 88,
    band: str = "hot",
) -> LeadScore:
    row = LeadScore(
        lead_id=lead.id,
        score=total,
        model_version="deterministic-icp-v2",
        rationale={"band": band, "fabricated_facts": False},
    )
    db.add(row)
    db.flush()
    return row


def sample_draft(
    db: Session,
    lead: Lead,
    organization: Organization,
    **overrides: object,
) -> PersonalizationDraft:
    values: dict[str, object] = {
        "lead_id": lead.id,
        "organization_id": organization.id,
        "readiness_status": PersonalizationReadiness.READY.value,
        "prompt_version": "test-v1",
        "schema_version": "test-v1",
        "provider_name": "stub",
        "practice_summary": (
            "AUSTIN FAMILY MEDICINE PLLC is a Family Medicine practice in AUSTIN, TX."
        ),
        "why_vyro_relevant": "Stored billing evidence notes in-house billing.",
        "opening_line": "Jordan, I noticed Austin Family Medicine is independently owned.",
        "outreach_angle": "Offer a complimentary revenue leakage analysis.",
        "suggested_offer": "Complimentary Revenue Leakage Analysis",
        "missing_data_notes": [],
        "evidence_references": [],
        "confidence": 0.72,
        "content_json": {},
        "audit_json": {"live_call_attempted": False, "fabricated_facts": False},
        "evidence_fingerprint": f"fp-{uuid4().hex[:16]}",
    }
    values.update(overrides)
    draft = PersonalizationDraft(**values)
    db.add(draft)
    db.flush()
    return draft


def eligible_lead_bundle(
    db: Session,
    **org_overrides: object,
) -> tuple[Organization, Lead, Contact, PersonalizationDraft]:
    organization = sample_organization(db, **org_overrides)
    lead = sample_lead(db, organization)
    contact = sample_contact(db, organization)
    sample_score(db, lead)
    draft = sample_draft(db, lead, organization)
    return organization, lead, contact, draft
