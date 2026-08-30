from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tests.fixtures.booking import meeting_request_bundle
from tests.fixtures.outreach import sample_contact, sample_lead, sample_organization
from vyro_growth.config import Settings
from vyro_growth.domain import (
    BookingPlanStatus,
    BookingSkipReason,
    LeadStage,
    ReplyClassificationOutcome,
    ReplyIntent,
)
from vyro_growth.models import (
    Activity,
    BookingPlan,
    BookingPlanRun,
    CampaignEnrollment,
    Meeting,
    OutreachMessage,
    ReplyClassification,
    Suppression,
)
from vyro_growth.providers.calendar_booking import (
    MalformedBookingPlanOutput,
    RetryableBookingCalendarError,
    StaticBookingCalendarProvider,
    StubBookingCalendarProvider,
)
from vyro_growth.providers.google_calendar import LiveGoogleCalendarProvider
from vyro_growth.providers.guarded import GuardedGoogleCalendarProvider
from vyro_growth.services.booking_plan import BookingPlanService
from vyro_growth.services.operator_halt import set_operator_halt
from vyro_growth.services.outbound_guard import OutboundGuard
from vyro_growth.workers.booking_plan_handler import PLAN_BOOKING_SLOTS_JOB
from vyro_growth.workers.outbound import outbound_action_for_job


def _service(provider: object | None = None) -> BookingPlanService:
    return BookingPlanService(provider or StubBookingCalendarProvider())


def test_meeting_request_creates_dry_run_plan(db_session: Session) -> None:
    _organization, lead, _contact, classification = meeting_request_bundle(db_session)
    result = _service().plan_lead(db_session, lead.id)

    assert result.planned_count == 1
    item = result.items[0]
    assert item.status is BookingPlanStatus.PLANNED
    assert item.dry_run is True
    assert item.event_created is False
    assert item.meet_link_created is False
    assert item.live_call_attempted is False
    plan = db_session.get(BookingPlan, item.booking_plan_id)
    assert plan is not None
    assert plan.reply_classification_id == classification.id
    assert plan.dry_run is True
    assert plan.event_created is False
    assert plan.meet_link_created is False
    assert plan.provider_event_id is None
    assert plan.meeting_url is None
    assert plan.proposed_slots
    assert plan.audit_json["fabricated_facts"] is False
    assert plan.audit_json["outbound_attempted"] is False
    db_session.refresh(lead)
    assert lead.stage == LeadStage.MEETING_READY.value
    assert lead.stage != LeadStage.MEETING_BOOKED.value
    assert db_session.scalar(select(func.count()).select_from(Meeting)) == 0
    assert db_session.scalar(select(func.count()).select_from(CampaignEnrollment)) == 0
    outbound_count = db_session.scalar(
        select(func.count())
        .select_from(OutreachMessage)
        .where(OutreachMessage.direction == "outbound")
    )
    assert outbound_count == 0
    activity = db_session.scalar(select(Activity).where(Activity.action == "booking_plan_planned"))
    assert activity is not None


def test_plan_classification_uses_phase_seven_meeting_request(db_session: Session) -> None:
    _organization, lead, _contact, classification = meeting_request_bundle(db_session)
    result = _service().plan_classification(db_session, classification.id)
    assert result.items[0].status is BookingPlanStatus.PLANNED
    db_session.refresh(lead)
    assert lead.stage == LeadStage.MEETING_READY.value


def test_interested_without_meeting_request_is_skipped(db_session: Session) -> None:
    organization = sample_organization(db_session)
    lead = sample_lead(db_session, organization, stage=LeadStage.INTERESTED)
    sample_contact(db_session, organization)
    classification = ReplyClassification(
        lead_id=lead.id,
        intent=ReplyIntent.INTERESTED.value,
        outcome=ReplyClassificationOutcome.CLASSIFIED.value,
        confidence=0.7,
        provider_name="stub",
        schema_version="reply-classification-v1",
        content_hash="interested-only",
        lead_stage_before=LeadStage.CONTACTED.value,
        lead_stage_after=LeadStage.INTERESTED.value,
    )
    db_session.add(classification)
    db_session.flush()

    result = _service().plan_lead(db_session, lead.id)
    assert result.items[0].status is BookingPlanStatus.SKIPPED
    assert result.items[0].skip_reason is BookingSkipReason.INELIGIBLE_CONSENT
    db_session.refresh(lead)
    assert lead.stage == LeadStage.INTERESTED.value


def test_missing_classification_is_skipped(db_session: Session) -> None:
    organization = sample_organization(db_session)
    lead = sample_lead(db_session, organization, stage=LeadStage.INTERESTED)
    sample_contact(db_session, organization)
    result = _service().plan_lead(db_session, lead.id)
    assert result.items[0].skip_reason is BookingSkipReason.MISSING_MEETING_REQUEST


def test_operator_request_plans_without_meeting_request(db_session: Session) -> None:
    organization = sample_organization(db_session)
    lead = sample_lead(db_session, organization, stage=LeadStage.INTERESTED)
    sample_contact(db_session, organization)
    result = _service().plan_lead(
        db_session,
        lead.id,
        operator_request=True,
        request_key="ops-1",
        requested_window={"starts_at": "2026-09-15T16:00:00+00:00"},
    )
    assert result.items[0].status is BookingPlanStatus.PLANNED
    plan = db_session.get(BookingPlan, result.items[0].booking_plan_id)
    assert plan is not None
    assert plan.request_source == "operator_request"
    assert plan.request_key == "ops-1"
    assert plan.requested_window == {"starts_at": "2026-09-15T16:00:00+00:00"}
    assert plan.proposed_slots[0]["starts_at_iso"].startswith("2026-09-15T16:00:00")


def test_email_suppression_is_recorded(db_session: Session) -> None:
    _organization, lead, contact, _classification = meeting_request_bundle(db_session)
    db_session.add(Suppression(email=contact.email, reason="unsubscribe", permanent=True))
    db_session.flush()

    result = _service().plan_lead(db_session, lead.id)
    assert result.items[0].status is BookingPlanStatus.SUPPRESSED
    assert result.suppressed_count == 1
    activity = db_session.scalar(
        select(Activity).where(Activity.action == "booking_plan_suppressed")
    )
    assert activity is not None
    db_session.refresh(lead)
    assert lead.stage == LeadStage.INTERESTED.value


def test_domain_and_organization_suppression(db_session: Session) -> None:
    organization, lead, _contact, _classification = meeting_request_bundle(db_session)
    db_session.add(Suppression(domain="austinfamily.example", reason="domain_opt_out"))
    db_session.flush()
    result = _service().plan_lead(db_session, lead.id)
    assert result.items[0].status is BookingPlanStatus.SUPPRESSED

    other_org, other_lead, _other_contact, _other = meeting_request_bundle(
        db_session,
        npi="1234567893",
        email="other@clinic.example",
    )
    db_session.add(Suppression(organization_id=other_org.id, reason="org_block", permanent=True))
    db_session.flush()
    other = _service().plan_lead(db_session, other_lead.id)
    assert other.items[0].status is BookingPlanStatus.SUPPRESSED


def test_rerun_is_idempotent(db_session: Session) -> None:
    _organization, lead, _contact, _classification = meeting_request_bundle(db_session)
    service = _service()
    first = service.plan_lead(db_session, lead.id)
    second = service.plan_lead(db_session, lead.id)

    assert first.items[0].booking_plan_id == second.items[0].booking_plan_id
    assert second.items[0].reused is True
    assert db_session.scalar(select(func.count()).select_from(BookingPlan)) == 1
    assert db_session.scalar(select(func.count()).select_from(BookingPlanRun)) == 2
    assert db_session.scalar(select(func.count()).select_from(Meeting)) == 0


def test_malformed_and_retryable_provider_failures(db_session: Session) -> None:
    _organization, lead, _contact, _classification = meeting_request_bundle(db_session)
    malformed = _service(StaticBookingCalendarProvider({"accepted": "yes"})).plan_lead(
        db_session, lead.id
    )
    assert malformed.items[0].skip_reason is BookingSkipReason.MALFORMED_PROVIDER_OUTPUT

    retryable = _service(
        StaticBookingCalendarProvider(error=RetryableBookingCalendarError("429"))
    ).plan_lead(db_session, lead.id)
    assert retryable.items[0].skip_reason is BookingSkipReason.PROVIDER_RETRYABLE_ERROR

    ungrounded = _service(
        StaticBookingCalendarProvider(error=MalformedBookingPlanOutput("meet url"))
    ).plan_lead(db_session, lead.id)
    assert ungrounded.items[0].skip_reason is BookingSkipReason.MALFORMED_PROVIDER_OUTPUT


def test_event_and_meet_creation_claims_are_blocked(db_session: Session) -> None:
    _organization, lead, _contact, _classification = meeting_request_bundle(db_session)
    event_result = _service(
        StaticBookingCalendarProvider(
            {
                "accepted": True,
                "dry_run": True,
                "live_call_attempted": False,
                "event_created": True,
                "meet_link_created": False,
                "provider_name": "google_calendar_guarded",
            }
        )
    ).plan_lead(db_session, lead.id)
    assert event_result.items[0].status is BookingPlanStatus.BLOCKED
    assert event_result.items[0].skip_reason is BookingSkipReason.EVENT_CREATION_REJECTED
    assert event_result.items[0].event_created is False

    _organization_b, lead_b, _contact_b, _class_b = meeting_request_bundle(
        db_session, npi="1999999991", email="second@clinic.example"
    )
    meet_result = _service(
        StaticBookingCalendarProvider(
            {
                "accepted": True,
                "dry_run": True,
                "live_call_attempted": False,
                "event_created": False,
                "meet_link_created": True,
                "provider_name": "google_calendar_guarded",
            }
        )
    ).plan_lead(db_session, lead_b.id)
    assert meet_result.items[0].skip_reason is BookingSkipReason.MEET_LINK_REJECTED
    assert db_session.scalar(select(func.count()).select_from(Meeting)) == 0


def test_live_booking_claim_is_blocked(db_session: Session) -> None:
    _organization, lead, _contact, _classification = meeting_request_bundle(db_session)
    result = _service(
        StaticBookingCalendarProvider(
            {
                "accepted": True,
                "dry_run": False,
                "live_call_attempted": True,
                "event_created": False,
                "meet_link_created": False,
                "provider_name": "google_calendar_guarded",
            }
        )
    ).plan_lead(db_session, lead.id)
    assert result.items[0].status is BookingPlanStatus.BLOCKED
    assert result.items[0].skip_reason is BookingSkipReason.LIVE_BOOKING_REJECTED
    assert result.items[0].live_call_attempted is False


def test_operator_halt_blocks_live_boundary(db_session: Session) -> None:
    _organization, lead, _contact, _classification = meeting_request_bundle(db_session)
    set_operator_halt(db_session, halted=True, reason="incident")
    inner = StubBookingCalendarProvider()
    inner.live = True
    settings = Settings(
        outbound_enabled=True,
        outbound_halted=False,
        google_calendar_live_enabled=True,
    )
    provider = GuardedGoogleCalendarProvider(
        inner,
        OutboundGuard(settings),
        db_session,
        settings,
    )
    result = BookingPlanService(provider, settings=settings).plan_lead(db_session, lead.id)
    assert result.items[0].status is BookingPlanStatus.BLOCKED
    assert result.items[0].skip_reason is BookingSkipReason.OPERATOR_GLOBAL_HALT
    assert inner.requests == []


def test_outbound_disabled_blocks_live_boundary(db_session: Session) -> None:
    _organization, lead, _contact, _classification = meeting_request_bundle(db_session)
    set_operator_halt(db_session, halted=False, reason="test_clear")
    inner = StubBookingCalendarProvider()
    inner.live = True
    settings = Settings(outbound_enabled=False, google_calendar_live_enabled=True)
    provider = GuardedGoogleCalendarProvider(
        inner,
        OutboundGuard(settings),
        db_session,
        settings,
    )
    result = BookingPlanService(provider, settings=settings).plan_lead(db_session, lead.id)
    assert result.items[0].status is BookingPlanStatus.BLOCKED
    assert result.items[0].skip_reason is BookingSkipReason.GLOBAL_OUTBOUND_DISABLED
    assert inner.requests == []


def test_live_adapter_without_client_is_blocked(db_session: Session) -> None:
    _organization, lead, _contact, _classification = meeting_request_bundle(db_session)
    set_operator_halt(db_session, halted=False, reason="test_clear")
    settings = Settings(
        outbound_enabled=True,
        outbound_halted=False,
        google_calendar_live_enabled=True,
        google_calendar_api_key="placeholder",
        google_calendar_api_base_url="https://calendar.test/api/v1",
    )
    live = LiveGoogleCalendarProvider.from_settings(settings)
    provider = GuardedGoogleCalendarProvider(
        live,
        OutboundGuard(settings),
        db_session,
        settings,
    )
    result = BookingPlanService(provider, settings=settings).plan_lead(db_session, lead.id)
    assert result.items[0].status is BookingPlanStatus.BLOCKED
    assert result.items[0].skip_reason is BookingSkipReason.LIVE_GOOGLE_NOT_IMPLEMENTED


def test_dry_run_plan_job_is_not_an_outbound_job() -> None:
    assert outbound_action_for_job(PLAN_BOOKING_SLOTS_JOB) is None


def test_stub_does_not_require_outbound_enabled(db_session: Session) -> None:
    _organization, lead, _contact, _classification = meeting_request_bundle(db_session)
    settings = Settings(outbound_enabled=False)
    result = BookingPlanService(StubBookingCalendarProvider(), settings=settings).plan_lead(
        db_session, lead.id
    )
    assert result.items[0].status is BookingPlanStatus.PLANNED
    plan = db_session.get(BookingPlan, result.items[0].booking_plan_id)
    assert plan is not None
    assert plan.audit_json["outbound_decision"] == "global_outbound_disabled"
    assert plan.audit_json["live_booking_allowed"] is False


def test_never_advances_to_meeting_booked(db_session: Session) -> None:
    _organization, lead, _contact, _classification = meeting_request_bundle(
        db_session, stage=LeadStage.MEETING_READY
    )
    result = _service().plan_lead(db_session, lead.id)
    assert result.items[0].status is BookingPlanStatus.PLANNED
    db_session.refresh(lead)
    assert lead.stage == LeadStage.MEETING_READY.value
