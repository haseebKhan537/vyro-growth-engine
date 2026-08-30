from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.orm import Session

from vyro_growth.providers.smartlead import SmartleadProvider, build_smartlead_provider
from vyro_growth.services.outreach_enrollment import OutreachEnrollmentService
from vyro_growth.workers.base import Job

PLAN_OUTREACH_ENROLLMENTS_JOB = "plan_outreach_enrollments"


@dataclass
class PlanOutreachEnrollmentsHandler:
    db: Session
    provider: SmartleadProvider | None = None

    def handle(self, job: Job) -> None:
        lead_id = _optional_uuid(job.payload.get("lead_id"))
        campaign_id = _optional_uuid(job.payload.get("campaign_id"))
        campaign_name = _optional_str(job.payload.get("campaign_name"))
        limit = _optional_int(job.payload.get("limit"))
        state = _optional_str(job.payload.get("state"))
        city = _optional_str(job.payload.get("city"))

        service = OutreachEnrollmentService(self.provider or build_smartlead_provider())
        if lead_id is not None:
            service.plan_lead(
                self.db,
                lead_id,
                campaign_id=campaign_id,
                campaign_name=campaign_name,
            )
            return
        service.plan_batch(
            self.db,
            limit=limit or 50,
            state=state,
            city=city,
            campaign_id=campaign_id,
            campaign_name=campaign_name,
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
