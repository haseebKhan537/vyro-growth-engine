from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.orm import Session

from vyro_growth.services.lead_scoring import LeadScoringError, LeadScoringService
from vyro_growth.workers.base import Job

SCORE_DISCOVERED_LEADS_JOB = "score_discovered_leads"


@dataclass
class ScoreDiscoveredLeadsHandler:
    db: Session

    def handle(self, job: Job) -> None:
        lead_id = _optional_uuid(job.payload.get("lead_id"))
        organization_id = _optional_uuid(job.payload.get("organization_id"))
        limit = _optional_int(job.payload.get("limit"))
        if lead_id is not None and organization_id is not None:
            raise LeadScoringError("Provide lead_id or organization_id, not both")

        service = LeadScoringService()
        if lead_id is not None:
            service.score_lead(self.db, lead_id)
            return
        if organization_id is not None:
            service.score_organization(self.db, organization_id)
            return
        service.score_batch(self.db, limit=limit or 100)


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
    text = _optional_str(value) if not isinstance(value, UUID) else None
    if isinstance(value, UUID):
        return value
    if text is None:
        return None
    return UUID(text)
