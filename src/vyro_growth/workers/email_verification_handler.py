from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.orm import Session

from vyro_growth.providers.email_verification import (
    EmailVerificationProvider,
    build_email_verification_provider,
)
from vyro_growth.services.email_verification import EmailVerificationService
from vyro_growth.workers.base import Job

VERIFY_CONTACT_EMAILS_JOB = "verify_contact_emails"


@dataclass
class VerifyContactEmailsHandler:
    db: Session
    provider: EmailVerificationProvider | None = None

    def handle(self, job: Job) -> None:
        organization_id = _optional_uuid(job.payload.get("organization_id"))
        limit = _optional_int(job.payload.get("limit"))
        state = _optional_str(job.payload.get("state"))
        city = _optional_str(job.payload.get("city"))

        service = EmailVerificationService(self.provider or build_email_verification_provider())
        if organization_id is not None:
            service.verify_organization(self.db, organization_id)
            return
        service.verify_batch(
            self.db,
            limit=limit or 50,
            state=state,
            city=city,
        )


def _optional_str(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _optional_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _optional_uuid(value: object) -> UUID | None:
    if isinstance(value, UUID):
        return value
    if isinstance(value, str) and value.strip():
        return UUID(value)
    return None
