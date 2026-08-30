from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from tests.fixtures.booking import meeting_request_bundle
from vyro_growth.domain import BookingPlanStatus
from vyro_growth.models import BookingPlan
from vyro_growth.providers.calendar_booking import StubBookingCalendarProvider
from vyro_growth.workers.base import Job
from vyro_growth.workers.booking_plan_handler import (
    PLAN_BOOKING_SLOTS_JOB,
    PlanBookingSlotsHandler,
)


def test_worker_plans_one_lead(db_session: Session) -> None:
    _organization, lead, _contact, _classification = meeting_request_bundle(db_session)
    handler = PlanBookingSlotsHandler(db=db_session, provider=StubBookingCalendarProvider())

    handler.handle(
        Job(
            name=PLAN_BOOKING_SLOTS_JOB,
            payload={"lead_id": str(lead.id)},
        )
    )

    plan = db_session.scalar(select(BookingPlan))
    assert plan is not None
    assert plan.lead_id == lead.id
    assert plan.status == BookingPlanStatus.PLANNED.value
    assert plan.dry_run is True
    assert plan.event_created is False
    assert plan.meet_link_created is False


def test_worker_batch_uses_limit(db_session: Session) -> None:
    meeting_request_bundle(db_session)
    handler = PlanBookingSlotsHandler(db=db_session, provider=StubBookingCalendarProvider())
    handler.handle(Job(name=PLAN_BOOKING_SLOTS_JOB, payload={"limit": 1}))
    assert db_session.scalar(select(BookingPlan)) is not None
