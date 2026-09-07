from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from vyro_growth.domain import ContactDiscoveryCallStatus, EnrichmentRunStatus
from vyro_growth.models import ContactDiscoveryCall, EnrichmentRun, Organization
from vyro_growth.workers.base import Job
from vyro_growth.workers.phone_verification_handler import (
    QUEUE_PHONE_VERIFICATION_JOB,
    QueuePhoneVerificationHandler,
)


def test_worker_queues_no_contact_found_organization(db_session: Session) -> None:
    organization = Organization(
        name="AUSTIN FAMILY MEDICINE PLLC",
        npi="1487448189",
        city="AUSTIN",
        state="TX",
    )
    db_session.add(organization)
    db_session.flush()
    db_session.add(
        EnrichmentRun(
            organization_id=organization.id,
            source="decision_maker",
            status=EnrichmentRunStatus.COMPLETED.value,
            contacts_upserted=0,
            contacts_skipped=0,
            candidates_considered=0,
        )
    )
    db_session.flush()
    handler = QueuePhoneVerificationHandler(db=db_session)

    handler.handle(
        Job(
            name=QUEUE_PHONE_VERIFICATION_JOB,
            payload={"organization_id": str(organization.id)},
        )
    )

    task = db_session.scalar(select(ContactDiscoveryCall))
    assert task is not None
    assert task.organization_id == organization.id
    assert task.status == ContactDiscoveryCallStatus.QUEUED.value
    assert task.live_call_attempted is False
    assert task.voice_provider_used is False


def test_worker_batch_uses_limit(db_session: Session) -> None:
    organization = Organization(
        name="AUSTIN FAMILY MEDICINE PLLC",
        npi="1487448189",
        city="AUSTIN",
        state="TX",
    )
    db_session.add(organization)
    db_session.flush()
    db_session.add(
        EnrichmentRun(
            organization_id=organization.id,
            source="decision_maker",
            status=EnrichmentRunStatus.COMPLETED.value,
            contacts_upserted=0,
        )
    )
    db_session.flush()
    handler = QueuePhoneVerificationHandler(db=db_session)

    handler.handle(Job(name=QUEUE_PHONE_VERIFICATION_JOB, payload={"limit": 1}))
    assert db_session.scalar(select(ContactDiscoveryCall)) is not None
