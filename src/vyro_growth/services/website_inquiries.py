"""Persist consented public-site inquiries as inbound CRM leads.

This service is record-only. It never sends email, enrolls a campaign, books a
meeting, places a call, invokes a provider, or changes operator safety controls.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

import structlog
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from vyro_growth.domain import (
    ContactVerificationStatus,
    ConversationStatus,
    LeadStage,
    MessageDirection,
)
from vyro_growth.models import (
    Activity,
    Contact,
    Conversation,
    Lead,
    Organization,
    OutreachMessage,
    WebsiteInquiry,
)

logger = structlog.get_logger(__name__)

WEBSITE_INQUIRY_SOURCE = "website_inquiry"
WEBSITE_INQUIRY_ACTOR = "website_intake"


@dataclass(frozen=True)
class WebsiteInquiryInput:
    submission_id: UUID
    form_name: str
    source_page: str
    practice_name: str
    contact_name: str
    work_email: str
    business_phone: str | None
    specialty: str | None
    state: str | None
    provider_count: str | None
    primary_concern: str | None
    preferred_contact: str | None
    business_context: str | None
    contact_consent: bool
    consent_text_version: str


@dataclass(frozen=True)
class WebsiteInquiryResult:
    inquiry_id: UUID
    submission_id: UUID
    lead_id: UUID
    duplicate: bool
    accepted_at: datetime


class WebsiteInquiryService:
    def capture(
        self,
        db: Session,
        inquiry: WebsiteInquiryInput,
        *,
        commit: bool = True,
    ) -> WebsiteInquiryResult:
        existing = db.scalar(
            select(WebsiteInquiry).where(WebsiteInquiry.submission_id == inquiry.submission_id)
        )
        if existing is not None:
            return _result(existing, duplicate=True)

        organization = _find_or_create_organization(db, inquiry)
        contact = _find_or_create_contact(db, organization, inquiry)
        lead = Lead(
            organization_id=organization.id,
            stage=LeadStage.INTERESTED.value,
            source=WEBSITE_INQUIRY_SOURCE,
        )
        db.add(lead)
        db.flush()

        message = OutreachMessage(
            lead_id=lead.id,
            contact_id=contact.id,
            channel="website",
            direction=MessageDirection.INBOUND.value,
            subject=inquiry.form_name,
            body=inquiry.business_context or "No business context was provided.",
            provider_message_id=f"website:{inquiry.submission_id}",
        )
        db.add(message)
        db.flush()

        db.add(
            Conversation(
                lead_id=lead.id,
                status=ConversationStatus.OPEN.value,
                summary="Inbound website inquiry awaiting operator follow-up.",
            )
        )
        row = WebsiteInquiry(
            submission_id=inquiry.submission_id,
            organization_id=organization.id,
            contact_id=contact.id,
            lead_id=lead.id,
            message_id=message.id,
            form_name=inquiry.form_name,
            source_page=inquiry.source_page,
            status="new",
            provider_count=inquiry.provider_count,
            primary_concern=inquiry.primary_concern,
            preferred_contact=inquiry.preferred_contact,
            business_context=inquiry.business_context,
            contact_consent=inquiry.contact_consent,
            consent_text_version=inquiry.consent_text_version,
            consented_at=datetime.now(tz=UTC),
        )
        db.add(row)
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            duplicate = db.scalar(
                select(WebsiteInquiry).where(
                    WebsiteInquiry.submission_id == inquiry.submission_id
                )
            )
            if duplicate is None:
                raise
            return _result(duplicate, duplicate=True)
        db.add(
            Activity(
                lead_id=lead.id,
                actor=WEBSITE_INQUIRY_ACTOR,
                action="website_inquiry_received",
                details={
                    "inquiry_id": str(row.id),
                    "submission_id": str(inquiry.submission_id),
                    "form_name": inquiry.form_name,
                    "source_page": inquiry.source_page,
                    "contact_consent": True,
                    "consent_text_version": inquiry.consent_text_version,
                    "outbound_attempted": False,
                    "live_call_attempted": False,
                },
            )
        )
        if commit:
            db.commit()
        logger.info(
            "website_inquiry_recorded",
            inquiry_id=str(row.id),
            lead_id=str(lead.id),
            form_name=inquiry.form_name,
            outbound_attempted=False,
            live_call_attempted=False,
        )
        return _result(row, duplicate=False)


def _find_or_create_organization(
    db: Session,
    inquiry: WebsiteInquiryInput,
) -> Organization:
    statement = select(Organization).where(
        func.lower(func.trim(Organization.name)) == inquiry.practice_name.casefold()
    )
    if inquiry.state:
        statement = statement.where(Organization.state == inquiry.state)
    organization = db.scalar(statement.order_by(Organization.created_at.asc()).limit(1))
    if organization is None:
        organization = Organization(
            name=inquiry.practice_name,
            specialty=inquiry.specialty,
            state=inquiry.state,
        )
        db.add(organization)
        db.flush()
        return organization
    if organization.specialty is None and inquiry.specialty:
        organization.specialty = inquiry.specialty
    if organization.state is None and inquiry.state:
        organization.state = inquiry.state
    return organization


def _find_or_create_contact(
    db: Session,
    organization: Organization,
    inquiry: WebsiteInquiryInput,
) -> Contact:
    email = inquiry.work_email.casefold()
    dedupe_key = f"email:{email}"
    contact = db.scalar(
        select(Contact).where(
            Contact.organization_id == organization.id,
            Contact.dedupe_key == dedupe_key,
        )
    )
    if contact is None:
        contact = Contact(
            organization_id=organization.id,
            full_name=inquiry.contact_name,
            email=email,
            phone=inquiry.business_phone,
            email_verified=False,
            verification_status=ContactVerificationStatus.UNVERIFIED.value,
            source_provider=WEBSITE_INQUIRY_SOURCE,
            source_timestamp=datetime.now(tz=UTC),
            confidence=1.0,
            dedupe_key=dedupe_key,
            provenance_json={
                "source": WEBSITE_INQUIRY_SOURCE,
                "self_submitted": True,
                "contact_consent": True,
            },
        )
        db.add(contact)
        db.flush()
        return contact
    contact.full_name = inquiry.contact_name
    if inquiry.business_phone:
        contact.phone = inquiry.business_phone
    return contact


def _result(row: WebsiteInquiry, *, duplicate: bool) -> WebsiteInquiryResult:
    return WebsiteInquiryResult(
        inquiry_id=row.id,
        submission_id=row.submission_id,
        lead_id=row.lead_id,
        duplicate=duplicate,
        accepted_at=row.created_at,
    )
