from __future__ import annotations

from dataclasses import dataclass, field

import pytest
from sqlalchemy.orm import Session

from vyro_growth.config import Settings
from vyro_growth.models import Suppression
from vyro_growth.services.operator_halt import set_operator_halt
from vyro_growth.services.outbound_guard import OutboundBlockedError, OutboundGuard
from vyro_growth.workers import InlineJobQueue, InlineWorkerRunner, Job, UnknownJobError
from vyro_growth.workers.booking_plan_handler import PLAN_BOOKING_SLOTS_JOB
from vyro_growth.workers.contact_enrichment_handler import ENRICH_DECISION_MAKERS_JOB
from vyro_growth.workers.outbound import (
    PLACE_CONSENT_CALLBACK_JOB,
    SCHEDULE_MEETING_JOB,
    SEND_EMAIL_JOB,
    SafetyCheckedWorkerRunner,
)
from vyro_growth.workers.outreach_enrollment_handler import PLAN_OUTREACH_ENROLLMENTS_JOB
from vyro_growth.workers.personalization_handler import PERSONALIZE_SCORED_LEADS_JOB
from vyro_growth.workers.reply_classification_handler import CLASSIFY_INBOUND_REPLIES_JOB
from vyro_growth.workers.scoring_handler import SCORE_DISCOVERED_LEADS_JOB
from vyro_growth.workers.voice_qualification_handler import PLAN_VOICE_QUALIFICATIONS_JOB
from vyro_growth.workers.website_enrichment_handler import ENRICH_ORGANIZATION_WEBSITES_JOB


@dataclass
class EchoHandler:
    handled: list[Job] = field(default_factory=list)

    def handle(self, job: Job) -> None:
        self.handled.append(job)


def test_inline_job_queue_returns_job_reference() -> None:
    queue = InlineJobQueue()
    job = Job(name="discover_practices", payload={"region": "TX"})

    job_id = queue.enqueue(job)

    assert job_id == "inline:discover_practices"


def test_inline_worker_runner_dispatches_to_handler() -> None:
    handler = EchoHandler()
    runner = InlineWorkerRunner({"discover_practices": handler})
    job = Job(name="discover_practices", payload={"region": "TX"})

    runner.run(job)

    assert handler.handled == [job]


def test_inline_worker_runner_raises_for_unknown_job() -> None:
    runner = InlineWorkerRunner({})

    with pytest.raises(UnknownJobError, match="discover_practices"):
        runner.run(Job(name="discover_practices", payload={}))


def test_safety_checked_runner_blocks_outbound_when_disabled(db_session: Session) -> None:
    handler = EchoHandler()
    runner = SafetyCheckedWorkerRunner(
        InlineWorkerRunner({SEND_EMAIL_JOB: handler}),
        OutboundGuard(Settings(outbound_enabled=False)),
        db_session,
    )

    with pytest.raises(OutboundBlockedError, match="global_outbound_disabled"):
        runner.run(Job(name=SEND_EMAIL_JOB, payload={"email": "owner@clinic.com"}))

    assert handler.handled == []


def test_safety_checked_runner_blocks_when_halted(db_session: Session) -> None:
    set_operator_halt(db_session, halted=True, reason="incident")
    handler = EchoHandler()
    runner = SafetyCheckedWorkerRunner(
        InlineWorkerRunner({SCHEDULE_MEETING_JOB: handler}),
        OutboundGuard(Settings(outbound_enabled=True, outbound_halted=False)),
        db_session,
    )

    with pytest.raises(OutboundBlockedError, match="operator_global_halt"):
        runner.run(
            Job(
                name=SCHEDULE_MEETING_JOB,
                payload={"email": "owner@clinic.com"},
            )
        )

    assert handler.handled == []


def test_safety_checked_runner_blocks_suppressed_phone_job(db_session: Session) -> None:
    set_operator_halt(db_session, halted=False, reason="test_clear")
    db_session.add(Suppression(phone="5551112222", reason="do_not_call", permanent=True))
    db_session.flush()
    handler = EchoHandler()
    runner = SafetyCheckedWorkerRunner(
        InlineWorkerRunner({PLACE_CONSENT_CALLBACK_JOB: handler}),
        OutboundGuard(Settings(outbound_enabled=True, outbound_halted=False)),
        db_session,
    )

    with pytest.raises(OutboundBlockedError, match="suppressed"):
        runner.run(
            Job(
                name=PLACE_CONSENT_CALLBACK_JOB,
                payload={"phone": "5551112222", "consent_to_call": True},
            )
        )

    assert handler.handled == []


def test_safety_checked_runner_fails_closed_without_target(db_session: Session) -> None:
    set_operator_halt(db_session, halted=False, reason="test_clear")
    handler = EchoHandler()
    runner = SafetyCheckedWorkerRunner(
        InlineWorkerRunner({SEND_EMAIL_JOB: handler}),
        OutboundGuard(Settings(outbound_enabled=True, outbound_halted=False)),
        db_session,
    )

    with pytest.raises(OutboundBlockedError, match="target_unidentified"):
        runner.run(Job(name=SEND_EMAIL_JOB, payload={}))

    assert handler.handled == []


def test_safety_checked_runner_allows_non_outbound_jobs_without_guard(db_session: Session) -> None:
    handler = EchoHandler()
    job = Job(name="discover_practices", payload={"region": "TX"})
    runner = SafetyCheckedWorkerRunner(
        InlineWorkerRunner({"discover_practices": handler}),
        OutboundGuard(Settings(outbound_enabled=False)),
        db_session,
    )

    runner.run(job)

    assert handler.handled == [job]


def test_safety_checked_runner_allows_scoring_jobs_without_guard(db_session: Session) -> None:
    handler = EchoHandler()
    job = Job(name=SCORE_DISCOVERED_LEADS_JOB, payload={"limit": 1})
    runner = SafetyCheckedWorkerRunner(
        InlineWorkerRunner({SCORE_DISCOVERED_LEADS_JOB: handler}),
        OutboundGuard(Settings(outbound_enabled=False)),
        db_session,
    )

    runner.run(job)

    assert handler.handled == [job]


def test_safety_checked_runner_allows_website_enrichment_without_guard(
    db_session: Session,
) -> None:
    handler = EchoHandler()
    job = Job(name=ENRICH_ORGANIZATION_WEBSITES_JOB, payload={"limit": 1})
    runner = SafetyCheckedWorkerRunner(
        InlineWorkerRunner({ENRICH_ORGANIZATION_WEBSITES_JOB: handler}),
        OutboundGuard(Settings(outbound_enabled=False)),
        db_session,
    )

    runner.run(job)

    assert handler.handled == [job]


def test_safety_checked_runner_allows_contact_enrichment_without_guard(
    db_session: Session,
) -> None:
    handler = EchoHandler()
    job = Job(name=ENRICH_DECISION_MAKERS_JOB, payload={"limit": 1})
    runner = SafetyCheckedWorkerRunner(
        InlineWorkerRunner({ENRICH_DECISION_MAKERS_JOB: handler}),
        OutboundGuard(Settings(outbound_enabled=False)),
        db_session,
    )

    runner.run(job)

    assert handler.handled == [job]


def test_safety_checked_runner_allows_personalization_without_guard(
    db_session: Session,
) -> None:
    handler = EchoHandler()
    job = Job(name=PERSONALIZE_SCORED_LEADS_JOB, payload={"limit": 1})
    runner = SafetyCheckedWorkerRunner(
        InlineWorkerRunner({PERSONALIZE_SCORED_LEADS_JOB: handler}),
        OutboundGuard(Settings(outbound_enabled=False)),
        db_session,
    )

    runner.run(job)

    assert handler.handled == [job]


def test_safety_checked_runner_allows_outreach_plan_without_guard(
    db_session: Session,
) -> None:
    handler = EchoHandler()
    job = Job(name=PLAN_OUTREACH_ENROLLMENTS_JOB, payload={"limit": 1})
    runner = SafetyCheckedWorkerRunner(
        InlineWorkerRunner({PLAN_OUTREACH_ENROLLMENTS_JOB: handler}),
        OutboundGuard(Settings(outbound_enabled=False)),
        db_session,
    )

    runner.run(job)

    assert handler.handled == [job]


def test_safety_checked_runner_allows_booking_plan_without_guard(
    db_session: Session,
) -> None:
    handler = EchoHandler()
    job = Job(name=PLAN_BOOKING_SLOTS_JOB, payload={"limit": 1})
    runner = SafetyCheckedWorkerRunner(
        InlineWorkerRunner({PLAN_BOOKING_SLOTS_JOB: handler}),
        OutboundGuard(Settings(outbound_enabled=False)),
        db_session,
    )

    runner.run(job)

    assert handler.handled == [job]


def test_safety_checked_runner_allows_voice_qualification_without_guard(
    db_session: Session,
) -> None:
    handler = EchoHandler()
    job = Job(name=PLAN_VOICE_QUALIFICATIONS_JOB, payload={"limit": 1})
    runner = SafetyCheckedWorkerRunner(
        InlineWorkerRunner({PLAN_VOICE_QUALIFICATIONS_JOB: handler}),
        OutboundGuard(Settings(outbound_enabled=False)),
        db_session,
    )

    runner.run(job)

    assert handler.handled == [job]


def test_safety_checked_runner_allows_reply_classification_without_guard(
    db_session: Session,
) -> None:
    handler = EchoHandler()
    job = Job(name=CLASSIFY_INBOUND_REPLIES_JOB, payload={"limit": 1})
    runner = SafetyCheckedWorkerRunner(
        InlineWorkerRunner({CLASSIFY_INBOUND_REPLIES_JOB: handler}),
        OutboundGuard(Settings(outbound_enabled=False)),
        db_session,
    )

    runner.run(job)

    assert handler.handled == [job]
