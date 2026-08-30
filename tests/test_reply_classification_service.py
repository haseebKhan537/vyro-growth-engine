from __future__ import annotations

from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tests.fixtures.replies import REPLY_BODIES, classified_payload
from vyro_growth.config import Settings
from vyro_growth.domain import (
    ConversationStatus,
    LeadStage,
    MessageDirection,
    ReplyClassificationOutcome,
    ReplyIntent,
)
from vyro_growth.models import (
    Activity,
    Campaign,
    Contact,
    Conversation,
    Lead,
    Meeting,
    Organization,
    OutreachMessage,
    ReplyClassification,
    Suppression,
)
from vyro_growth.providers.reply_classification import (
    RetryableReplyClassifierError,
    StaticReplyClassifier,
    StubReplyClassifier,
)
from vyro_growth.services.operator_halt import read_operator_halt, set_operator_halt
from vyro_growth.services.outbound_guard import OutboundAction, OutboundGuard
from vyro_growth.services.reply_classification import (
    InboundReplySpec,
    ReplyClassificationService,
)
from vyro_growth.workers.outbound import outbound_action_for_job
from vyro_growth.workers.reply_classification_handler import CLASSIFY_INBOUND_REPLIES_JOB


def _org(db: Session, **overrides: object) -> Organization:
    values: dict[str, object] = {
        "name": "AUSTIN FAMILY MEDICINE PLLC",
        "npi": "1487448189",
        "city": "AUSTIN",
        "state": "TX",
        "specialty": "Family Medicine",
    }
    values.update(overrides)
    organization = Organization(**values)
    db.add(organization)
    db.flush()
    return organization


def _lead(db: Session, organization: Organization, stage: LeadStage = LeadStage.CONTACTED) -> Lead:
    lead = Lead(organization_id=organization.id, stage=stage.value, source="test")
    db.add(lead)
    db.flush()
    return lead


def _contact(
    db: Session,
    organization: Organization,
    email: str = "owner@clinic.example",
) -> Contact:
    contact = Contact(
        organization_id=organization.id,
        full_name="Jordan Blake",
        title="Practice Manager",
        email=email,
    )
    db.add(contact)
    db.flush()
    return contact


def _inbound(
    db: Session,
    lead: Lead,
    body: str,
    *,
    contact: Contact | None = None,
    provider_message_id: str | None = None,
    subject: str | None = "Re: billing",
) -> OutreachMessage:
    message = OutreachMessage(
        lead_id=lead.id,
        contact_id=contact.id if contact is not None else None,
        channel="email",
        direction=MessageDirection.INBOUND.value,
        subject=subject,
        body=body,
        provider_message_id=provider_message_id or f"msg-{uuid4()}",
    )
    db.add(message)
    db.flush()
    return message


def test_interested_moves_contacted_to_interested(db_session: Session) -> None:
    organization = _org(db_session)
    lead = _lead(db_session, organization)
    message = _inbound(db_session, lead, REPLY_BODIES[ReplyIntent.INTERESTED])
    service = ReplyClassificationService(StubReplyClassifier())

    result = service.classify_message(db_session, message.id)

    assert result.intent is ReplyIntent.INTERESTED
    assert result.outcome is ReplyClassificationOutcome.CLASSIFIED
    assert result.outbound_attempted is False
    assert result.live_call_attempted is False
    db_session.refresh(lead)
    assert lead.stage == LeadStage.INTERESTED.value
    conversation = db_session.scalar(select(Conversation).where(Conversation.lead_id == lead.id))
    assert conversation is not None
    assert conversation.status == ConversationStatus.INTERESTED.value
    row = db_session.get(ReplyClassification, result.classification_id)
    assert row is not None
    assert row.outbound_attempted is False


def test_meeting_request_does_not_book_or_advance_to_meeting(db_session: Session) -> None:
    organization = _org(db_session)
    lead = _lead(db_session, organization)
    message = _inbound(db_session, lead, REPLY_BODIES[ReplyIntent.MEETING_REQUEST])
    service = ReplyClassificationService(StubReplyClassifier())

    result = service.classify_message(db_session, message.id)

    assert result.intent is ReplyIntent.MEETING_REQUEST
    db_session.refresh(lead)
    assert lead.stage == LeadStage.INTERESTED.value
    assert lead.stage != LeadStage.MEETING_BOOKED.value
    assert lead.stage != LeadStage.MEETING_READY.value
    assert db_session.scalar(select(func.count()).select_from(Meeting)) == 0
    conversation = db_session.scalar(select(Conversation).where(Conversation.lead_id == lead.id))
    assert conversation is not None
    assert conversation.status == ConversationStatus.MEETING_REQUESTED.value


def test_unsubscribe_creates_suppression_and_suppresses_lead(db_session: Session) -> None:
    organization = _org(db_session)
    lead = _lead(db_session, organization)
    contact = _contact(db_session, organization, "optout@clinic.example")
    message = _inbound(db_session, lead, REPLY_BODIES[ReplyIntent.UNSUBSCRIBE], contact=contact)
    service = ReplyClassificationService(StubReplyClassifier())

    result = service.classify_message(db_session, message.id)

    assert result.outcome is ReplyClassificationOutcome.SUPPRESSED
    assert result.suppressed is True
    db_session.refresh(lead)
    assert lead.stage == LeadStage.SUPPRESSED.value
    suppression = db_session.scalar(
        select(Suppression).where(Suppression.email == "optout@clinic.example")
    )
    assert suppression is not None
    assert suppression.reason == "unsubscribe"
    assert suppression.permanent is True
    activity = db_session.scalar(select(Activity).where(Activity.action == "reply_suppressed"))
    assert activity is not None


def test_unsubscribe_confirms_existing_suppression(db_session: Session) -> None:
    organization = _org(db_session)
    lead = _lead(db_session, organization)
    contact = _contact(db_session, organization, "optout@clinic.example")
    db_session.add(
        Suppression(email="optout@clinic.example", reason="unsubscribe", permanent=True)
    )
    db_session.flush()
    message = _inbound(db_session, lead, REPLY_BODIES[ReplyIntent.UNSUBSCRIBE], contact=contact)
    service = ReplyClassificationService(StubReplyClassifier())

    result = service.classify_message(db_session, message.id)

    assert result.suppressed is True
    count = db_session.scalar(
        select(func.count())
        .select_from(Suppression)
        .where(Suppression.email == "optout@clinic.example")
    )
    assert count == 1


def test_not_interested_marks_lost_from_contacted(db_session: Session) -> None:
    organization = _org(db_session)
    lead = _lead(db_session, organization)
    message = _inbound(db_session, lead, REPLY_BODIES[ReplyIntent.NOT_INTERESTED])
    result = ReplyClassificationService(StubReplyClassifier()).classify_message(
        db_session, message.id
    )
    assert result.intent is ReplyIntent.NOT_INTERESTED
    db_session.refresh(lead)
    assert lead.stage == LeadStage.LOST.value


def test_out_of_office_skips_stage_change(db_session: Session) -> None:
    organization = _org(db_session)
    lead = _lead(db_session, organization)
    message = _inbound(db_session, lead, REPLY_BODIES[ReplyIntent.OUT_OF_OFFICE])
    result = ReplyClassificationService(StubReplyClassifier()).classify_message(
        db_session, message.id
    )
    assert result.outcome is ReplyClassificationOutcome.SKIPPED
    db_session.refresh(lead)
    assert lead.stage == LeadStage.CONTACTED.value
    activity = db_session.scalar(select(Activity).where(Activity.action == "reply_skipped"))
    assert activity is not None


def test_unknown_from_contacted_moves_only_to_replied(db_session: Session) -> None:
    organization = _org(db_session)
    lead = _lead(db_session, organization)
    message = _inbound(db_session, lead, REPLY_BODIES[ReplyIntent.UNKNOWN])
    result = ReplyClassificationService(StubReplyClassifier()).classify_message(
        db_session, message.id
    )
    assert result.outcome is ReplyClassificationOutcome.UNKNOWN
    db_session.refresh(lead)
    assert lead.stage == LeadStage.REPLIED.value
    activity = db_session.scalar(select(Activity).where(Activity.action == "reply_unknown"))
    assert activity is not None


def test_interested_from_discovered_is_blocked(db_session: Session) -> None:
    organization = _org(db_session)
    lead = _lead(db_session, organization, stage=LeadStage.DISCOVERED)
    message = _inbound(db_session, lead, REPLY_BODIES[ReplyIntent.INTERESTED])
    result = ReplyClassificationService(StubReplyClassifier()).classify_message(
        db_session, message.id
    )
    assert result.outcome is ReplyClassificationOutcome.BLOCKED
    db_session.refresh(lead)
    assert lead.stage == LeadStage.DISCOVERED.value
    activity = db_session.scalar(select(Activity).where(Activity.action == "reply_blocked"))
    assert activity is not None


def test_does_not_advance_into_contacted(db_session: Session) -> None:
    organization = _org(db_session)
    lead = _lead(db_session, organization, stage=LeadStage.READY_FOR_OUTREACH)
    message = _inbound(db_session, lead, REPLY_BODIES[ReplyIntent.INTERESTED])
    ReplyClassificationService(StubReplyClassifier()).classify_message(db_session, message.id)
    db_session.refresh(lead)
    assert lead.stage != LeadStage.CONTACTED.value
    assert lead.stage == LeadStage.READY_FOR_OUTREACH.value


def test_idempotent_by_message_provider_id_and_content_hash(db_session: Session) -> None:
    organization = _org(db_session)
    lead = _lead(db_session, organization)
    provider_id = "provider-inbound-1"
    message = _inbound(
        db_session,
        lead,
        REPLY_BODIES[ReplyIntent.NEEDS_MORE_INFO],
        provider_message_id=provider_id,
    )
    service = ReplyClassificationService(StubReplyClassifier())
    first = service.classify_message(db_session, message.id)
    second = service.classify_message(db_session, message.id)
    third = service.classify_inbound(
        db_session,
        InboundReplySpec(
            lead_id=lead.id,
            body=REPLY_BODIES[ReplyIntent.NEEDS_MORE_INFO],
            subject="Re: billing",
            provider_message_id=provider_id,
        ),
    )

    assert first.classification_id == second.classification_id == third.classification_id
    assert second.reused_existing is True
    assert third.reused_existing is True
    assert db_session.scalar(select(func.count()).select_from(ReplyClassification)) == 1
    skip_count = db_session.scalar(
        select(func.count()).select_from(Activity).where(Activity.action == "reply_skipped")
    )
    assert skip_count == 2
    db_session.refresh(lead)
    assert lead.stage == LeadStage.REPLIED.value


def test_malformed_provider_output_fails_without_state_change(db_session: Session) -> None:
    organization = _org(db_session)
    lead = _lead(db_session, organization)
    message = _inbound(db_session, lead, REPLY_BODIES[ReplyIntent.INTERESTED])
    service = ReplyClassificationService(StaticReplyClassifier({"nope": True}))

    result = service.classify_message(db_session, message.id)

    assert result.outcome is ReplyClassificationOutcome.FAILED
    db_session.refresh(lead)
    assert lead.stage == LeadStage.CONTACTED.value
    assert db_session.scalar(select(ReplyClassification)) is None
    activity = db_session.scalar(
        select(Activity).where(Activity.action == "reply_classification_failed")
    )
    assert activity is not None
    assert activity.details["retryable"] is False


def test_retryable_provider_failure_is_audited(db_session: Session) -> None:
    organization = _org(db_session)
    lead = _lead(db_session, organization)
    message = _inbound(db_session, lead, REPLY_BODIES[ReplyIntent.UNKNOWN])
    service = ReplyClassificationService(
        StaticReplyClassifier(RetryableReplyClassifierError("timeout"))
    )

    result = service.classify_message(db_session, message.id)

    assert result.outcome is ReplyClassificationOutcome.FAILED
    activity = db_session.scalar(
        select(Activity).where(Activity.action == "reply_classification_failed")
    )
    assert activity is not None
    assert activity.details["retryable"] is True
    assert activity.details["failure_kind"] == "retryable"


def test_operator_halt_is_preserved(db_session: Session) -> None:
    set_operator_halt(db_session, halted=True, reason="incident")
    organization = _org(db_session)
    lead = _lead(db_session, organization)
    message = _inbound(db_session, lead, REPLY_BODIES[ReplyIntent.INTERESTED])
    service = ReplyClassificationService(StubReplyClassifier())

    result = service.classify_message(db_session, message.id)

    assert result.operator_halt_before == "halted"
    assert result.operator_halt_after == "halted"
    assert read_operator_halt(db_session).value == "halted"
    control_reason = db_session.scalar(
        select(Activity).where(Activity.action == "reply_classified")
    )
    assert control_reason is not None
    assert control_reason.details["operator_halt_after"] == "halted"


def test_no_outbound_side_effects(db_session: Session) -> None:
    organization = _org(db_session)
    lead = _lead(db_session, organization)
    contact = _contact(db_session, organization)
    message = _inbound(
        db_session,
        lead,
        REPLY_BODIES[ReplyIntent.MEETING_REQUEST],
        contact=contact,
    )
    db_session.add(Campaign(name="dry-run", active=False))
    db_session.flush()
    service = ReplyClassificationService(StubReplyClassifier())
    service.classify_message(db_session, message.id)

    outbound_count = db_session.scalar(
        select(func.count())
        .select_from(OutreachMessage)
        .where(OutreachMessage.direction == MessageDirection.OUTBOUND.value)
    )
    assert outbound_count == 0
    assert db_session.scalar(select(func.count()).select_from(Meeting)) == 0
    campaign = db_session.scalar(select(Campaign))
    assert campaign is not None
    assert campaign.active is False
    settings = Settings()
    assert settings.outbound_enabled is False
    assert outbound_action_for_job(CLASSIFY_INBOUND_REPLIES_JOB) is None
    guard = OutboundGuard(Settings(outbound_enabled=False))
    decision = guard.evaluate(
        db_session,
        action=OutboundAction.EMAIL_SEND,
        email="owner@clinic.example",
    )
    assert decision.allowed is False


def test_does_not_persist_patient_or_invented_facts(db_session: Session) -> None:
    organization = _org(db_session)
    lead = _lead(db_session, organization)
    message = _inbound(
        db_session,
        lead,
        "We are interested. A diabetes patient asked about billing software and denial rates.",
    )
    specialty_before = organization.specialty
    result = ReplyClassificationService(StubReplyClassifier()).classify_message(
        db_session, message.id
    )
    db_session.refresh(organization)
    assert organization.specialty == specialty_before
    row = db_session.get(ReplyClassification, result.classification_id)
    assert row is not None
    rationale = str(row.rationale_json)
    assert "diabetes" not in rationale.lower()
    activity = db_session.scalar(select(Activity).where(Activity.action == "reply_classified"))
    assert activity is not None
    assert "diabetes" not in str(activity.details).lower()


def test_static_valid_payload_classifies(db_session: Session) -> None:
    organization = _org(db_session)
    lead = _lead(db_session, organization)
    message = _inbound(db_session, lead, "custom text without keywords")
    service = ReplyClassificationService(
        StaticReplyClassifier(classified_payload(ReplyIntent.REFERRAL))
    )
    result = service.classify_message(db_session, message.id)
    assert result.intent is ReplyIntent.REFERRAL
    db_session.refresh(lead)
    assert lead.stage == LeadStage.REPLIED.value


def test_classify_inbound_fixture_without_existing_message(db_session: Session) -> None:
    organization = _org(db_session)
    lead = _lead(db_session, organization)
    service = ReplyClassificationService(StubReplyClassifier())
    result = service.classify_inbound(
        db_session,
        InboundReplySpec(
            lead_id=lead.id,
            body=REPLY_BODIES[ReplyIntent.HOSTILE],
            sender_email="owner@clinic.example",
            provider_message_id="fixture-hostile-1",
        ),
    )
    assert result.intent is ReplyIntent.HOSTILE
    db_session.refresh(lead)
    assert lead.stage == LeadStage.LOST.value
    stored = db_session.scalar(select(OutreachMessage))
    assert stored is not None
    assert stored.direction == MessageDirection.INBOUND.value


def test_wrong_person_and_spam_and_needs_info(db_session: Session) -> None:
    organization = _org(db_session)
    service = ReplyClassificationService(StubReplyClassifier())

    lost_lead = _lead(db_session, organization)
    lost_message = _inbound(db_session, lost_lead, REPLY_BODIES[ReplyIntent.WRONG_PERSON])
    lost_result = service.classify_message(db_session, lost_message.id)
    assert lost_result.intent is ReplyIntent.WRONG_PERSON
    db_session.refresh(lost_lead)
    assert lost_lead.stage == LeadStage.LOST.value

    spam_lead = Lead(
        organization_id=organization.id,
        stage=LeadStage.CONTACTED.value,
        source="test",
    )
    db_session.add(spam_lead)
    db_session.flush()
    spam_message = _inbound(db_session, spam_lead, REPLY_BODIES[ReplyIntent.SPAM])
    spam_result = service.classify_message(db_session, spam_message.id)
    assert spam_result.outcome is ReplyClassificationOutcome.SKIPPED
    db_session.refresh(spam_lead)
    assert spam_lead.stage == LeadStage.CONTACTED.value
