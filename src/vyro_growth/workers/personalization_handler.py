from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.orm import Session

from vyro_growth.providers.personalization import (
    PersonalizationProvider,
    build_personalization_provider,
)
from vyro_growth.services.personalization import PersonalizationError, PersonalizationService
from vyro_growth.workers.base import Job

PERSONALIZE_SCORED_LEADS_JOB = "personalize_scored_leads"


@dataclass
class PersonalizeScoredLeadsHandler:
    db: Session
    provider: PersonalizationProvider | None = None

    def handle(self, job: Job) -> None:
        lead_id = _optional_uuid(job.payload.get("lead_id"))
        organization_id = _optional_uuid(job.payload.get("organization_id"))
        limit = _optional_int(job.payload.get("limit"))
        state = _optional_str(job.payload.get("state"))
        city = _optional_str(job.payload.get("city"))
        if lead_id is not None and organization_id is not None:
            raise PersonalizationError("Provide lead_id or organization_id, not both")

        service = PersonalizationService(self.provider or build_personalization_provider())
        if lead_id is not None:
            service.personalize_lead(self.db, lead_id)
            return
        if organization_id is not None:
            service.personalize_organization(self.db, organization_id)
            return
        service.personalize_batch(
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
