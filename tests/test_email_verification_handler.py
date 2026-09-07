from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from tests.test_email_verification_service import PROSPECT_EMAIL, _contact, _org
from vyro_growth.domain import EmailVerificationVerdict
from vyro_growth.models import Contact
from vyro_growth.providers.email_verification import StaticEmailVerificationProvider
from vyro_growth.workers.base import Job
from vyro_growth.workers.email_verification_handler import (
    VERIFY_CONTACT_EMAILS_JOB,
    VerifyContactEmailsHandler,
)


def test_worker_verifies_one_organization(db_session: Session) -> None:
    organization = _org(db_session)
    contact = _contact(db_session, organization)
    handler = VerifyContactEmailsHandler(
        db=db_session,
        provider=StaticEmailVerificationProvider(
            {PROSPECT_EMAIL: EmailVerificationVerdict.VALID}
        ),
    )

    handler.handle(
        Job(
            name=VERIFY_CONTACT_EMAILS_JOB,
            payload={"organization_id": str(organization.id)},
        )
    )

    db_session.refresh(contact)
    assert contact.email_verification_verdict == EmailVerificationVerdict.VALID.value
    assert contact.email_verified is True
    stored = db_session.scalar(select(Contact))
    assert stored is not None
    assert stored.organization_id == organization.id


def test_worker_batch_uses_limit(db_session: Session) -> None:
    organization = _org(db_session)
    contact = _contact(db_session, organization)
    handler = VerifyContactEmailsHandler(
        db=db_session,
        provider=StaticEmailVerificationProvider(
            {PROSPECT_EMAIL: EmailVerificationVerdict.VALID}
        ),
    )

    handler.handle(Job(name=VERIFY_CONTACT_EMAILS_JOB, payload={"limit": 1}))
    db_session.refresh(contact)
    assert contact.email_verification_verdict == EmailVerificationVerdict.VALID.value
