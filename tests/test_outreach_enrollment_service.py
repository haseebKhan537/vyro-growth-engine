from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tests.fixtures.outreach import (
    eligible_lead_bundle,
    sample_contact,
    sample_draft,
    sample_lead,
    sample_organization,
    sample_score,
)
from vyro_growth.config import Settings
from vyro_growth.domain import (
    EnrollmentSkipReason,
    EnrollmentStatus,
    LeadStage,
    PersonalizationReadiness,
)
from vyro_growth.models import (
    Activity,
    CampaignEnrollment,
    OutreachMessage,
    OutreachPlanRun,
    Suppression,
)
from vyro_growth.providers.guarded import GuardedSmartleadProvider
from vyro_growth.providers.smartlead import (
    MalformedSmartleadOutput,
    RetryableSmartleadError,
    StaticSmartleadProvider,
    StubSmartleadProvider,
)
from vyro_growth.providers.smartlead_live import LiveSmartleadProvider
from vyro_growth.services.operator_halt import set_operator_halt
from vyro_growth.services.outbound_guard import OutboundGuard
from vyro_growth.services.outreach_enrollment import OutreachEnrollmentService
from vyro_growth.workers.outbound import outbound_action_for_job
from vyro_growth.workers.outreach_enrollment_handler import PLAN_OUTREACH_ENROLLMENTS_JOB


def _service(provider: object | None = None) -> OutreachEnrollmentService:
    return OutreachEnrollmentService(provider or StubSmartleadProvider())


def test_eligible_lead_creates_dry_run_plan(db_session: Session) -> None:
    _organization, lead, _contact, _draft = eligible_lead_bundle(db_session)
    result = _service().plan_lead(db_session, lead.id)

    assert result.planned_count == 1
    assert result.skipped_count == 0
    item = result.items[0]
    assert item.status is EnrollmentStatus.PLANNED
    assert item.dry_run is True
    assert item.live_send_attempted is False
    enrollment = db_session.get(CampaignEnrollment, item.enrollment_id)
    assert enrollment is not None
    assert enrollment.dry_run is True
    assert enrollment.live_send_attempted is False
    assert enrollment.details_json["fabricated_facts"] is False
    assert enrollment.details_json["outbound_attempted"] is False
    assert db_session.scalar(select(func.count()).select_from(OutreachMessage)) == 0
    activity = db_session.scalar(
        select(Activity).where(Activity.action == "outreach_enrollment_planned")
    )
    assert activity is not None
    refreshed = db_session.get(type(lead), lead.id)
    assert refreshed is not None
    assert refreshed.stage == LeadStage.READY_FOR_OUTREACH.value


def test_missing_personalization_is_skipped(db_session: Session) -> None:
    organization = sample_organization(db_session)
    lead = sample_lead(db_session, organization)
    sample_contact(db_session, organization)
    sample_score(db_session, lead)

    result = _service().plan_lead(db_session, lead.id)

    assert result.items[0].status is EnrollmentStatus.SKIPPED
    assert result.items[0].skip_reason is EnrollmentSkipReason.MISSING_PERSONALIZATION


def test_personalization_not_ready_is_skipped(db_session: Session) -> None:
    _organization, lead, _contact, draft = eligible_lead_bundle(db_session)
    draft.readiness_status = PersonalizationReadiness.NEEDS_MORE_EVIDENCE.value
    db_session.flush()

    result = _service().plan_lead(db_session, lead.id)

    assert result.items[0].skip_reason is EnrollmentSkipReason.PERSONALIZATION_NOT_READY


def test_missing_contact_email_is_skipped(db_session: Session) -> None:
    organization = sample_organization(db_session)
    lead = sample_lead(db_session, organization)
    sample_contact(db_session, organization, email=None, dedupe_key="name:jordan blake")
    sample_score(db_session, lead)
    sample_draft(db_session, lead, organization)

    result = _service().plan_lead(db_session, lead.id)

    assert result.items[0].skip_reason is EnrollmentSkipReason.MISSING_CONTACT_EMAIL


def test_unverified_email_is_skipped_as_no_verified_email(db_session: Session) -> None:
    organization = sample_organization(db_session)
    lead = sample_lead(db_session, organization)
    sample_contact(
        db_session,
        organization,
        email_verified=False,
        email_verification_verdict="unverified",
    )
    sample_score(db_session, lead)
    sample_draft(db_session, lead, organization)

    result = _service().plan_lead(db_session, lead.id)

    assert result.items[0].status is EnrollmentStatus.SKIPPED
    assert result.items[0].skip_reason is EnrollmentSkipReason.NO_VERIFIED_EMAIL
    assert db_session.scalar(select(func.count()).select_from(OutreachMessage)) == 0


def test_inferred_unverified_email_is_not_enrollable(db_session: Session) -> None:
    organization = sample_organization(db_session)
    lead = sample_lead(db_session, organization)
    sample_contact(
        db_session,
        organization,
        email="sam.rivera@austinfamily.example",
        email_origin="inferred",
        email_verified=False,
        email_verification_verdict="unverified",
        dedupe_key="email:sam.rivera@austinfamily.example",
    )
    sample_score(db_session, lead)
    sample_draft(db_session, lead, organization)

    result = _service().plan_lead(db_session, lead.id)

    assert result.items[0].status is EnrollmentStatus.SKIPPED
    assert result.items[0].skip_reason is EnrollmentSkipReason.INFERRED_EMAIL_UNVERIFIED
    assert db_session.scalar(select(func.count()).select_from(CampaignEnrollment)) == 1
    enrollment = db_session.scalar(select(CampaignEnrollment))
    assert enrollment is not None
    assert enrollment.details_json["email_verification_required"] is True
    assert "sam.rivera@austinfamily.example" not in str(enrollment.details_json)


def test_ineligible_stage_is_skipped(db_session: Session) -> None:
    organization = sample_organization(db_session)
    lead = sample_lead(db_session, organization, stage=LeadStage.DISCOVERED)
    sample_contact(db_session, organization)
    sample_score(db_session, lead)
    sample_draft(db_session, lead, organization)

    result = _service().plan_lead(db_session, lead.id)

    assert result.items[0].skip_reason is EnrollmentSkipReason.INELIGIBLE_STAGE


def test_disqualified_score_is_skipped(db_session: Session) -> None:
    organization = sample_organization(db_session)
    lead = sample_lead(db_session, organization)
    sample_contact(db_session, organization)
    sample_score(db_session, lead, total=5, band="disqualified")
    sample_draft(db_session, lead, organization)

    result = _service().plan_lead(db_session, lead.id)

    assert result.items[0].skip_reason is EnrollmentSkipReason.INELIGIBLE_SCORE


def test_email_suppression_is_recorded(db_session: Session) -> None:
    _organization, lead, contact, _draft = eligible_lead_bundle(db_session)
    db_session.add(Suppression(email=contact.email, reason="unsubscribe", permanent=True))
    db_session.flush()

    result = _service().plan_lead(db_session, lead.id)

    assert result.items[0].status is EnrollmentStatus.SUPPRESSED
    assert result.suppressed_count == 1
    activity = db_session.scalar(
        select(Activity).where(Activity.action == "outreach_enrollment_suppressed")
    )
    assert activity is not None


def test_domain_suppression_is_recorded(db_session: Session) -> None:
    _organization, lead, _contact, _draft = eligible_lead_bundle(db_session)
    db_session.add(Suppression(domain="austinfamily.example", reason="domain_opt_out"))
    db_session.flush()

    result = _service().plan_lead(db_session, lead.id)
    assert result.items[0].status is EnrollmentStatus.SUPPRESSED


def test_organization_suppression_is_recorded(db_session: Session) -> None:
    organization, lead, _contact, _draft = eligible_lead_bundle(db_session)
    db_session.add(
        Suppression(organization_id=organization.id, reason="org_block", permanent=True)
    )
    db_session.flush()

    result = _service().plan_lead(db_session, lead.id)
    assert result.items[0].status is EnrollmentStatus.SUPPRESSED


def test_rerun_is_idempotent(db_session: Session) -> None:
    _organization, lead, _contact, _draft = eligible_lead_bundle(db_session)
    service = _service()
    first = service.plan_lead(db_session, lead.id)
    second = service.plan_lead(db_session, lead.id)

    assert first.items[0].enrollment_id == second.items[0].enrollment_id
    assert second.items[0].reused is True
    assert db_session.scalar(select(func.count()).select_from(CampaignEnrollment)) == 1
    assert db_session.scalar(select(func.count()).select_from(OutreachPlanRun)) == 2
    assert db_session.scalar(select(func.count()).select_from(OutreachMessage)) == 0


def test_malformed_provider_output_is_skipped(db_session: Session) -> None:
    _organization, lead, _contact, _draft = eligible_lead_bundle(db_session)
    provider = StaticSmartleadProvider({"accepted": "yes"})
    result = _service(provider).plan_lead(db_session, lead.id)
    assert result.items[0].skip_reason is EnrollmentSkipReason.MALFORMED_PROVIDER_OUTPUT
    assert provider.requests


def test_retryable_provider_failure_is_skipped(db_session: Session) -> None:
    _organization, lead, _contact, _draft = eligible_lead_bundle(db_session)
    provider = StaticSmartleadProvider(error=RetryableSmartleadError("429"))
    result = _service(provider).plan_lead(db_session, lead.id)
    assert result.items[0].skip_reason is EnrollmentSkipReason.PROVIDER_RETRYABLE_ERROR


def test_non_retryable_provider_failure_is_skipped(db_session: Session) -> None:
    _organization, lead, _contact, _draft = eligible_lead_bundle(db_session)
    provider = StaticSmartleadProvider(error=MalformedSmartleadOutput("ungrounded"))
    result = _service(provider).plan_lead(db_session, lead.id)
    assert result.items[0].skip_reason is EnrollmentSkipReason.MALFORMED_PROVIDER_OUTPUT


def test_live_send_claim_is_blocked(db_session: Session) -> None:
    _organization, lead, _contact, _draft = eligible_lead_bundle(db_session)
    provider = StaticSmartleadProvider(
        {
            "accepted": True,
            "dry_run": False,
            "live_call_attempted": True,
            "provider_name": "smartlead_guarded",
            "raw": {"sent": False},
        }
    )
    result = _service(provider).plan_lead(db_session, lead.id)
    assert result.items[0].status is EnrollmentStatus.BLOCKED
    assert result.items[0].skip_reason is EnrollmentSkipReason.LIVE_SEND_REJECTED
    assert result.items[0].live_send_attempted is False


def test_operator_halt_blocks_live_boundary(db_session: Session) -> None:
    _organization, lead, _contact, _draft = eligible_lead_bundle(db_session)
    set_operator_halt(db_session, halted=True, reason="incident")
    inner = StubSmartleadProvider()
    inner.live = True
    settings = Settings(outbound_enabled=True, outbound_halted=False, smartlead_live_enabled=True)
    provider = GuardedSmartleadProvider(
        inner,
        OutboundGuard(settings),
        db_session,
        settings,
    )
    result = OutreachEnrollmentService(provider, settings=settings).plan_lead(db_session, lead.id)
    assert result.items[0].status is EnrollmentStatus.BLOCKED
    assert result.items[0].skip_reason is EnrollmentSkipReason.OPERATOR_GLOBAL_HALT
    assert inner.requests == []


def test_outbound_disabled_blocks_live_boundary(db_session: Session) -> None:
    _organization, lead, _contact, _draft = eligible_lead_bundle(db_session)
    set_operator_halt(db_session, halted=False, reason="test_clear")
    inner = StubSmartleadProvider()
    inner.live = True
    settings = Settings(outbound_enabled=False, smartlead_live_enabled=True)
    provider = GuardedSmartleadProvider(
        inner,
        OutboundGuard(settings),
        db_session,
        settings,
    )
    result = OutreachEnrollmentService(provider, settings=settings).plan_lead(db_session, lead.id)
    assert result.items[0].status is EnrollmentStatus.BLOCKED
    assert result.items[0].skip_reason is EnrollmentSkipReason.GLOBAL_OUTBOUND_DISABLED
    assert inner.requests == []


def test_live_adapter_without_client_is_blocked(db_session: Session) -> None:
    _organization, lead, _contact, _draft = eligible_lead_bundle(db_session)
    set_operator_halt(db_session, halted=False, reason="test_clear")
    settings = Settings(
        outbound_enabled=True,
        outbound_halted=False,
        smartlead_live_enabled=True,
        smartlead_api_key="placeholder",
        smartlead_api_base_url="https://smartlead.test/api/v1",
    )
    live = LiveSmartleadProvider.from_settings(settings)
    provider = GuardedSmartleadProvider(
        live,
        OutboundGuard(settings),
        db_session,
        settings,
    )
    result = OutreachEnrollmentService(provider, settings=settings).plan_lead(db_session, lead.id)
    assert result.items[0].status is EnrollmentStatus.BLOCKED
    assert result.items[0].skip_reason is EnrollmentSkipReason.LIVE_SMARTLEAD_NOT_IMPLEMENTED


def test_dry_run_plan_job_is_not_an_outbound_job() -> None:
    assert outbound_action_for_job(PLAN_OUTREACH_ENROLLMENTS_JOB) is None


def test_stub_does_not_require_outbound_enabled(db_session: Session) -> None:
    _organization, lead, _contact, _draft = eligible_lead_bundle(db_session)
    settings = Settings(outbound_enabled=False)
    result = OutreachEnrollmentService(
        StubSmartleadProvider(),
        settings=settings,
    ).plan_lead(db_session, lead.id)
    assert result.items[0].status is EnrollmentStatus.PLANNED
    enrollment = db_session.get(CampaignEnrollment, result.items[0].enrollment_id)
    assert enrollment is not None
    assert enrollment.details_json["outbound_decision"] == "global_outbound_disabled"
    assert enrollment.details_json["live_send_allowed"] is False
