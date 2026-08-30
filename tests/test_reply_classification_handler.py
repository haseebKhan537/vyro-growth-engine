from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from tests.fixtures.replies import REPLY_BODIES
from vyro_growth.domain import LeadStage, MessageDirection, ReplyIntent
from vyro_growth.models import Lead, Organization, OutreachMessage, ReplyClassification
from vyro_growth.providers.reply_classification import StubReplyClassifier
from vyro_growth.workers.base import Job
from vyro_growth.workers.reply_classification_handler import (
    CLASSIFY_INBOUND_REPLIES_JOB,
    ClassifyInboundRepliesHandler,
)


def test_worker_classifies_one_inbound_message(db_session: Session) -> None:
    organization = Organization(
        name="AUSTIN FAMILY MEDICINE PLLC",
        npi="1487448189",
        city="AUSTIN",
        state="TX",
        specialty="Family Medicine",
    )
    db_session.add(organization)
    db_session.flush()
    lead = Lead(
        organization_id=organization.id,
        stage=LeadStage.CONTACTED.value,
        source="test",
    )
    db_session.add(lead)
    db_session.flush()
    message = OutreachMessage(
        lead_id=lead.id,
        channel="email",
        direction=MessageDirection.INBOUND.value,
        subject="Re: billing",
        body=REPLY_BODIES[ReplyIntent.INTERESTED],
        provider_message_id="worker-msg-1",
    )
    db_session.add(message)
    db_session.flush()
    handler = ClassifyInboundRepliesHandler(db=db_session, provider=StubReplyClassifier())

    handler.handle(
        Job(
            name=CLASSIFY_INBOUND_REPLIES_JOB,
            payload={"message_id": str(message.id)},
        )
    )

    row = db_session.scalar(select(ReplyClassification))
    assert row is not None
    assert row.intent == ReplyIntent.INTERESTED.value


def test_worker_batch_uses_limit(db_session: Session) -> None:
    organization = Organization(
        name="AUSTIN FAMILY MEDICINE PLLC",
        npi="1487448189",
        city="AUSTIN",
        state="TX",
    )
    db_session.add(organization)
    db_session.flush()
    lead = Lead(
        organization_id=organization.id,
        stage=LeadStage.CONTACTED.value,
        source="test",
    )
    db_session.add(lead)
    db_session.flush()
    db_session.add(
        OutreachMessage(
            lead_id=lead.id,
            channel="email",
            direction=MessageDirection.INBOUND.value,
            body=REPLY_BODIES[ReplyIntent.UNKNOWN],
            provider_message_id="worker-batch-1",
        )
    )
    db_session.flush()
    handler = ClassifyInboundRepliesHandler(db=db_session, provider=StubReplyClassifier())

    handler.handle(Job(name=CLASSIFY_INBOUND_REPLIES_JOB, payload={"limit": 1}))
    assert db_session.scalar(select(ReplyClassification)) is not None
