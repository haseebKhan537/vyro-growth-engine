from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.orm import Session

from vyro_growth.services.phone_verification import PhoneVerificationService
from vyro_growth.workers.base import Job

QUEUE_PHONE_VERIFICATION_JOB = "queue_phone_verification_tasks"


@dataclass
class QueuePhoneVerificationHandler:
    db: Session

    def handle(self, job: Job) -> None:
        organization_id = _optional_uuid(job.payload.get("organization_id"))
        limit = _optional_int(job.payload.get("limit"))
        state = _optional_str(job.payload.get("state"))
        city = _optional_str(job.payload.get("city"))
        service = PhoneVerificationService()
        if organization_id is not None:
            service.queue_missing_contacts(
                self.db,
                organization_id=organization_id,
                source="worker",
            )
            return
        service.queue_missing_contacts(
            self.db,
            limit=limit or 50,
            state=state,
            city=city,
            source="worker",
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
