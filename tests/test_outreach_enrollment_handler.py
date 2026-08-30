from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from tests.fixtures.outreach import eligible_lead_bundle
from vyro_growth.domain import EnrollmentStatus
from vyro_growth.models import CampaignEnrollment
from vyro_growth.providers.smartlead import StubSmartleadProvider
from vyro_growth.workers.base import Job
from vyro_growth.workers.outreach_enrollment_handler import (
    PLAN_OUTREACH_ENROLLMENTS_JOB,
    PlanOutreachEnrollmentsHandler,
)


def test_worker_plans_one_lead(db_session: Session) -> None:
    _organization, lead, _contact, _draft = eligible_lead_bundle(db_session)
    handler = PlanOutreachEnrollmentsHandler(db=db_session, provider=StubSmartleadProvider())

    handler.handle(
        Job(
            name=PLAN_OUTREACH_ENROLLMENTS_JOB,
            payload={"lead_id": str(lead.id)},
        )
    )

    enrollment = db_session.scalar(select(CampaignEnrollment))
    assert enrollment is not None
    assert enrollment.lead_id == lead.id
    assert enrollment.status == EnrollmentStatus.PLANNED.value
    assert enrollment.dry_run is True
    assert enrollment.live_send_attempted is False


def test_worker_batch_uses_limit(db_session: Session) -> None:
    eligible_lead_bundle(db_session, npi="1487448189")
    handler = PlanOutreachEnrollmentsHandler(db=db_session, provider=StubSmartleadProvider())
    handler.handle(Job(name=PLAN_OUTREACH_ENROLLMENTS_JOB, payload={"limit": 1}))
    assert db_session.scalar(select(CampaignEnrollment)) is not None
