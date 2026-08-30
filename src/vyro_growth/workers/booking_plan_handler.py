from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.orm import Session

from vyro_growth.providers.calendar_booking import (
    BookingCalendarProvider,
    build_booking_calendar_provider,
)
from vyro_growth.services.booking_plan import BookingPlanService
from vyro_growth.workers.base import Job

PLAN_BOOKING_SLOTS_JOB = "plan_booking_slots"


@dataclass
class PlanBookingSlotsHandler:
    db: Session
    provider: BookingCalendarProvider | None = None

    def handle(self, job: Job) -> None:
        lead_id = _optional_uuid(job.payload.get("lead_id"))
        classification_id = _optional_uuid(job.payload.get("classification_id"))
        operator_request = job.payload.get("operator_request") is True
        request_key = _optional_str(job.payload.get("request_key"))
        requested_window = _optional_window(job.payload.get("requested_window"))
        limit = _optional_int(job.payload.get("limit"))
        state = _optional_str(job.payload.get("state"))
        city = _optional_str(job.payload.get("city"))

        service = BookingPlanService(self.provider or build_booking_calendar_provider())
        if classification_id is not None and lead_id is None:
            service.plan_classification(self.db, classification_id)
            return
        if lead_id is not None:
            service.plan_lead(
                self.db,
                lead_id,
                classification_id=classification_id,
                operator_request=operator_request,
                request_key=request_key,
                requested_window=requested_window,
            )
            return
        service.plan_batch(
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


def _optional_window(value: object) -> dict[str, object] | None:
    if isinstance(value, dict):
        return dict(value)
    return None
