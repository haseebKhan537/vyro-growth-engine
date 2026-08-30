from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy.orm import Session

from tests.fixtures.outreach import sample_contact, sample_lead, sample_organization
from vyro_growth.domain import LeadStage, MessageDirection
from vyro_growth.models import Contact, Lead, Organization, OutreachMessage

CALL_REQUEST_BODY = "Please call me tomorrow about billing follow-up."
MEETING_ONLY_BODY = "Let's meet next week if you can schedule a meeting."
PHI_CALL_BODY = "Please call me. The patient has a diagnosis of diabetes."


def voice_call_request_bundle(
    db: Session,
    *,
    stage: LeadStage = LeadStage.INTERESTED,
    npi: str = "1487448189",
    email: str = "jordan.blake@austinfamily.example",
    phone: str = "5551112222",
    body: str = CALL_REQUEST_BODY,
) -> tuple[Organization, Lead, Contact, OutreachMessage]:
    organization = sample_organization(db, npi=npi)
    lead = sample_lead(db, organization, stage=stage)
    contact = sample_contact(
        db,
        organization,
        email=email,
        phone=phone,
        dedupe_key=f"email:{email}",
    )
    message = OutreachMessage(
        lead_id=lead.id,
        contact_id=contact.id,
        channel="email",
        direction=MessageDirection.INBOUND.value,
        subject="Re: billing",
        body=body,
        provider_message_id=f"voice-msg-{uuid4()}",
    )
    db.add(message)
    db.flush()
    return organization, lead, contact, message


def operator_consent_timestamp() -> datetime:
    return datetime(2026, 8, 30, 15, 0, tzinfo=UTC)
