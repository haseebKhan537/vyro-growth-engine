from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.orm import Session

from vyro_growth.providers.decision_makers import (
    DecisionMakerEnrichmentProvider,
    build_decision_maker_provider,
)
from vyro_growth.services.contact_enrichment import ContactEnrichmentService
from vyro_growth.workers.base import Job

ENRICH_DECISION_MAKERS_JOB = "enrich_decision_makers"


@dataclass
class EnrichDecisionMakersHandler:
    db: Session
    provider: DecisionMakerEnrichmentProvider | None = None

    def handle(self, job: Job) -> None:
        organization_id = _optional_uuid(job.payload.get("organization_id"))
        limit = _optional_int(job.payload.get("limit"))
        state = _optional_str(job.payload.get("state"))
        city = _optional_str(job.payload.get("city"))

        service = ContactEnrichmentService(self.provider or build_decision_maker_provider())
        if organization_id is not None:
            service.enrich_organization(self.db, organization_id)
            return
        service.enrich_batch(
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
