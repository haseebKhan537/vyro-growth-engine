from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from tests.fixtures.voice import voice_call_request_bundle
from vyro_growth.domain import VoicePlanStatus
from vyro_growth.models import VoiceQualificationPlan
from vyro_growth.providers.voice_qualification import StubVoiceQualificationProvider
from vyro_growth.workers.base import Job
from vyro_growth.workers.voice_qualification_handler import (
    PLAN_VOICE_QUALIFICATIONS_JOB,
    PlanVoiceQualificationsHandler,
)


def test_worker_plans_one_lead(db_session: Session) -> None:
    _organization, lead, _contact, _message = voice_call_request_bundle(db_session)
    handler = PlanVoiceQualificationsHandler(
        db=db_session,
        provider=StubVoiceQualificationProvider(),
    )

    handler.handle(
        Job(
            name=PLAN_VOICE_QUALIFICATIONS_JOB,
            payload={"lead_id": str(lead.id)},
        )
    )

    plan = db_session.scalar(select(VoiceQualificationPlan))
    assert plan is not None
    assert plan.lead_id == lead.id
    assert plan.status == VoicePlanStatus.PLANNED.value
    assert plan.dry_run is True
    assert plan.call_placed is False
    assert plan.live_call_attempted is False


def test_worker_batch_uses_limit(db_session: Session) -> None:
    voice_call_request_bundle(db_session, npi="1487448189")
    handler = PlanVoiceQualificationsHandler(
        db=db_session,
        provider=StubVoiceQualificationProvider(),
    )
    handler.handle(Job(name=PLAN_VOICE_QUALIFICATIONS_JOB, payload={"limit": 1}))
    assert db_session.scalar(select(VoiceQualificationPlan)) is not None
