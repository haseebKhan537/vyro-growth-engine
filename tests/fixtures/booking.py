from __future__ import annotations

from uuid import uuid4

from sqlalchemy.orm import Session

from tests.fixtures.outreach import sample_contact, sample_lead, sample_organization
from vyro_growth.domain import (
    LeadStage,
    MessageDirection,
    ReplyClassificationOutcome,
    ReplyIntent,
)
from vyro_growth.models import Contact, Lead, Organization, OutreachMessage, ReplyClassification


def meeting_request_bundle(
    db: Session,
    *,
    stage: LeadStage = LeadStage.INTERESTED,
    npi: str = "1487448189",
    email: str = "jordan.blake@austinfamily.example",
) -> tuple[Organization, Lead, Contact, ReplyClassification]:
    organization = sample_organization(db, npi=npi)
    lead = sample_lead(db, organization, stage=stage)
    contact = sample_contact(db, organization, email=email, dedupe_key=f"email:{email}")
    message = OutreachMessage(
        lead_id=lead.id,
        contact_id=contact.id,
        channel="email",
        direction=MessageDirection.INBOUND.value,
        subject="Re: billing",
        body="Let's meet next week if you can schedule a meeting.",
        provider_message_id=f"msg-{uuid4()}",
    )
    db.add(message)
    db.flush()
    classification = ReplyClassification(
        lead_id=lead.id,
        outreach_message_id=message.id,
        provider_message_id=message.provider_message_id,
        sender_email=email,
        intent=ReplyIntent.MEETING_REQUEST.value,
        outcome=ReplyClassificationOutcome.CLASSIFIED.value,
        confidence=0.78,
        provider_name="stub",
        schema_version="reply-classification-v1",
        content_hash=f"hash-{uuid4().hex}",
        unsubscribe_explicit=False,
        suppressed=False,
        outbound_attempted=False,
        live_call_attempted=False,
        lead_stage_before=LeadStage.CONTACTED.value,
        lead_stage_after=stage.value,
        conversation_status_after="meeting_requested",
        matched_signals=["schedule a meeting"],
        rationale_json={"intent": ReplyIntent.MEETING_REQUEST.value},
        audit_json={"meetings_created": 0},
    )
    db.add(classification)
    db.flush()
    return organization, lead, contact, classification
