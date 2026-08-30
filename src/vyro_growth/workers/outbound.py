from __future__ import annotations

from typing import TypedDict

from sqlalchemy.orm import Session

from vyro_growth.services.outbound_guard import OutboundAction, OutboundGuard
from vyro_growth.workers.base import Job
from vyro_growth.workers.runner import WorkerRunner

SEND_EMAIL_JOB = "send_email"
SCHEDULE_MEETING_JOB = "schedule_meeting"
PLACE_CONSENT_CALLBACK_JOB = "place_consent_callback"

OUTBOUND_JOB_ACTIONS: dict[str, OutboundAction] = {
    SEND_EMAIL_JOB: OutboundAction.EMAIL_SEND,
    SCHEDULE_MEETING_JOB: OutboundAction.CALENDAR_SCHEDULE,
    PLACE_CONSENT_CALLBACK_JOB: OutboundAction.PHONE_DIAL,
}


class OutboundJobTarget(TypedDict):
    email: str | None
    domain: str | None
    phone: str | None
    consent_to_call: bool


def outbound_action_for_job(job_name: str) -> OutboundAction | None:
    return OUTBOUND_JOB_ACTIONS.get(job_name)


def target_from_job_payload(payload: dict[str, object]) -> OutboundJobTarget:
    email = payload.get("email")
    domain = payload.get("domain")
    phone = payload.get("phone")
    consent = payload.get("consent_to_call", False)
    return {
        "email": email if isinstance(email, str) else None,
        "domain": domain if isinstance(domain, str) else None,
        "phone": phone if isinstance(phone, str) else None,
        "consent_to_call": consent is True,
    }


class SafetyCheckedWorkerRunner:
    """Fail-closed wrapper that gates registered outbound jobs before dispatch."""

    def __init__(self, inner: WorkerRunner, guard: OutboundGuard, db: Session) -> None:
        self._inner = inner
        self._guard = guard
        self._db = db

    def run(self, job: Job) -> None:
        action = outbound_action_for_job(job.name)
        if action is not None:
            target = target_from_job_payload(job.payload)
            self._guard.require_allowed(self._db, action=action, **target)
        self._inner.run(job)
