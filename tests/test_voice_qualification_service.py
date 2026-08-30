from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tests.fixtures.outreach import sample_contact, sample_lead, sample_organization
from tests.fixtures.voice import (
    CALL_REQUEST_BODY,
    MEETING_ONLY_BODY,
    PHI_CALL_BODY,
    operator_consent_timestamp,
    voice_call_request_bundle,
)
from vyro_growth.config import Settings
from vyro_growth.domain import (
    LeadStage,
    MessageDirection,
    VoiceConsentChannel,
    VoiceConsentSource,
    VoicePlanStatus,
    VoiceSkipReason,
)
from vyro_growth.models import (
    Activity,
    CampaignEnrollment,
    Meeting,
    OutreachMessage,
    Suppression,
    VoiceQualificationPlan,
    VoiceQualificationRun,
)
from vyro_growth.providers.guarded import GuardedVoiceQualificationProvider
from vyro_growth.providers.voice_qualification import (
    RetryableVoiceQualificationError,
    StaticVoiceQualificationProvider,
    StubVoiceQualificationProvider,
)
from vyro_growth.providers.voice_qualification_live import LiveVoiceQualificationProvider
from vyro_growth.services.operator_halt import set_operator_halt
from vyro_growth.services.outbound_guard import OutboundGuard
from vyro_growth.services.voice_qualification import VoiceConsentInput, VoiceQualificationService
from vyro_growth.workers.outbound import outbound_action_for_job
from vyro_growth.workers.voice_qualification_handler import PLAN_VOICE_QUALIFICATIONS_JOB


def _service(provider: object | None = None) -> VoiceQualificationService:
    return VoiceQualificationService(provider or StubVoiceQualificationProvider())


def _operator_consent(phone: str = "5551112222") -> VoiceConsentInput:
    return VoiceConsentInput(
        source=VoiceConsentSource.OPERATOR_REQUEST,
        channel=VoiceConsentChannel.OPERATOR,
        consented_at=operator_consent_timestamp(),
        permitted_phone=phone,
        evidence_reference_id="ops-1",
    )


def test_inbound_call_request_creates_dry_run_plan(db_session: Session) -> None:
    _organization, lead, contact, message = voice_call_request_bundle(db_session)
    result = _service().plan_lead(db_session, lead.id)

    assert result.planned_count == 1
    item = result.items[0]
    assert item.status is VoicePlanStatus.PLANNED
    assert item.dry_run is True
    assert item.live_call_attempted is False
    assert item.call_placed is False
    plan = db_session.get(VoiceQualificationPlan, item.voice_plan_id)
    assert plan is not None
    assert plan.outreach_message_id == message.id
    assert plan.consent_source == VoiceConsentSource.INBOUND_REPLY.value
    assert plan.consent_channel == VoiceConsentChannel.EMAIL.value
    assert plan.consent_evidence_id == str(message.id)
    assert plan.permitted_phone == "5551112222"
    assert plan.dry_run is True
    assert plan.call_placed is False
    assert plan.live_call_attempted is False
    assert plan.audit_json["fabricated_facts"] is False
    assert plan.consent_json["source"] == "inbound_reply"
    assert plan.consent_json["permitted_phone"] == "5551112222"
    db_session.refresh(lead)
    assert lead.stage != LeadStage.MEETING_BOOKED.value
    assert db_session.scalar(select(func.count()).select_from(Meeting)) == 0
    assert db_session.scalar(select(func.count()).select_from(CampaignEnrollment)) == 0
    outbound_count = db_session.scalar(
        select(func.count())
        .select_from(OutreachMessage)
        .where(OutreachMessage.direction == MessageDirection.OUTBOUND.value)
    )
    assert outbound_count == 0
    activity = db_session.scalar(
        select(Activity).where(Activity.action == "voice_qualification_planned")
    )
    assert activity is not None
    assert contact.phone == "5551112222"


def test_plan_message_uses_stored_inbound_call_request(db_session: Session) -> None:
    _organization, lead, _contact, message = voice_call_request_bundle(db_session)
    result = _service().plan_message(db_session, message.id)
    assert result.items[0].status is VoicePlanStatus.PLANNED
    db_session.refresh(lead)
    assert lead.stage != LeadStage.MEETING_BOOKED.value


def test_meeting_only_reply_is_not_voice_consent(db_session: Session) -> None:
    _organization, lead, _contact, _message = voice_call_request_bundle(
        db_session,
        body=MEETING_ONLY_BODY,
    )
    result = _service().plan_lead(db_session, lead.id)
    assert result.items[0].status is VoicePlanStatus.SKIPPED
    assert result.items[0].skip_reason is VoiceSkipReason.INELIGIBLE_CONSENT_CONTEXT


def test_missing_consent_proof_is_skipped(db_session: Session) -> None:
    organization = sample_organization(db_session)
    lead = sample_lead(db_session, organization, stage=LeadStage.INTERESTED)
    sample_contact(db_session, organization, phone="5551112222")
    result = _service().plan_lead(db_session, lead.id)
    assert result.items[0].status is VoicePlanStatus.SKIPPED
    assert result.items[0].skip_reason is VoiceSkipReason.MISSING_CONSENT_PROOF
    activity = db_session.scalar(
        select(Activity).where(Activity.action == "voice_qualification_skipped")
    )
    assert activity is not None


def test_operator_request_requires_consent_proof(db_session: Session) -> None:
    organization = sample_organization(db_session)
    lead = sample_lead(db_session, organization, stage=LeadStage.INTERESTED)
    sample_contact(db_session, organization, phone="5551112222")
    result = _service().plan_lead(db_session, lead.id, operator_request=True)
    assert result.items[0].skip_reason is VoiceSkipReason.MISSING_CONSENT_PROOF


def test_operator_request_with_consent_proof_is_planned(db_session: Session) -> None:
    organization = sample_organization(db_session)
    lead = sample_lead(db_session, organization, stage=LeadStage.INTERESTED)
    sample_contact(db_session, organization, phone="5551112222")
    result = _service().plan_lead(
        db_session,
        lead.id,
        operator_request=True,
        request_key="ops-1",
        consent=_operator_consent(),
    )
    assert result.items[0].status is VoicePlanStatus.PLANNED
    plan = db_session.get(VoiceQualificationPlan, result.items[0].voice_plan_id)
    assert plan is not None
    assert plan.consent_source == VoiceConsentSource.OPERATOR_REQUEST.value
    assert plan.consent_evidence_id == "ops-1"
    assert plan.facts_json.get("specialty") == "Family Medicine"


def test_meeting_permission_context_is_planned(db_session: Session) -> None:
    organization = sample_organization(db_session)
    lead = sample_lead(db_session, organization, stage=LeadStage.INTERESTED)
    sample_contact(db_session, organization, phone="5551112222")
    meeting = Meeting(
        lead_id=lead.id,
        starts_at=datetime(2026, 9, 8, 15, 0, tzinfo=UTC),
        status="scheduled",
    )
    db_session.add(meeting)
    db_session.flush()
    result = _service().plan_meeting(
        db_session,
        meeting.id,
        consent=VoiceConsentInput(
            source=VoiceConsentSource.MEETING_PERMISSION,
            channel=VoiceConsentChannel.BOOKING,
            consented_at=datetime(2026, 9, 1, 12, 0, tzinfo=UTC),
            permitted_phone="5551112222",
            evidence_reference_id=str(meeting.id),
        ),
    )
    assert result.items[0].status is VoicePlanStatus.PLANNED
    plan = db_session.get(VoiceQualificationPlan, result.items[0].voice_plan_id)
    assert plan is not None
    assert plan.meeting_id == meeting.id
    assert plan.consent_source == VoiceConsentSource.MEETING_PERMISSION.value
    assert db_session.scalar(select(func.count()).select_from(Meeting)) == 1


def test_missing_business_phone_is_skipped(db_session: Session) -> None:
    _organization, lead, contact, _message = voice_call_request_bundle(db_session, phone=None)
    contact.phone = None
    db_session.flush()
    result = _service().plan_lead(db_session, lead.id)
    assert result.items[0].skip_reason is VoiceSkipReason.MISSING_BUSINESS_PHONE


def test_suspected_phi_is_blocked_and_not_persisted(db_session: Session) -> None:
    _organization, lead, _contact, message = voice_call_request_bundle(
        db_session,
        body=PHI_CALL_BODY,
    )
    result = _service().plan_lead(db_session, lead.id)
    assert result.items[0].status is VoicePlanStatus.BLOCKED
    assert result.items[0].skip_reason is VoiceSkipReason.SUSPECTED_PHI
    plan = db_session.get(VoiceQualificationPlan, result.items[0].voice_plan_id)
    assert plan is not None
    assert "diabetes" not in str(plan.facts_json).lower()
    assert "diabetes" not in str(plan.audit_json).lower()
    assert "diabetes" not in str(plan.consent_json).lower()
    activity = db_session.scalar(
        select(Activity).where(Activity.action == "voice_qualification_blocked")
    )
    assert activity is not None
    assert "diabetes" not in str(activity.details).lower()
    assert message.body == PHI_CALL_BODY


def test_phone_suppression_is_recorded(db_session: Session) -> None:
    _organization, lead, _contact, _message = voice_call_request_bundle(db_session)
    db_session.add(Suppression(phone="5551112222", reason="do_not_call", permanent=True))
    db_session.flush()
    result = _service().plan_lead(db_session, lead.id)
    assert result.items[0].status is VoicePlanStatus.SUPPRESSED
    assert result.suppressed_count == 1
    activity = db_session.scalar(
        select(Activity).where(Activity.action == "voice_qualification_suppressed")
    )
    assert activity is not None


def test_organization_suppression_is_recorded(db_session: Session) -> None:
    organization, lead, _contact, _message = voice_call_request_bundle(db_session)
    db_session.add(
        Suppression(organization_id=organization.id, reason="org_block", permanent=True)
    )
    db_session.flush()
    result = _service().plan_lead(db_session, lead.id)
    assert result.items[0].status is VoicePlanStatus.SUPPRESSED


def test_rerun_is_idempotent(db_session: Session) -> None:
    _organization, lead, _contact, _message = voice_call_request_bundle(db_session)
    service = _service()
    first = service.plan_lead(db_session, lead.id)
    second = service.plan_lead(db_session, lead.id)
    assert first.items[0].voice_plan_id == second.items[0].voice_plan_id
    assert second.items[0].reused is True
    assert db_session.scalar(select(func.count()).select_from(VoiceQualificationPlan)) == 1
    assert db_session.scalar(select(func.count()).select_from(VoiceQualificationRun)) == 2
    assert db_session.scalar(select(func.count()).select_from(Meeting)) == 0


def test_malformed_provider_output_is_skipped(db_session: Session) -> None:
    _organization, lead, _contact, _message = voice_call_request_bundle(db_session)
    provider = StaticVoiceQualificationProvider({"accepted": "yes"})
    result = _service(provider).plan_lead(db_session, lead.id)
    assert result.items[0].skip_reason is VoiceSkipReason.MALFORMED_PROVIDER_OUTPUT
    assert provider.requests


def test_retryable_provider_failure_is_skipped(db_session: Session) -> None:
    _organization, lead, _contact, _message = voice_call_request_bundle(db_session)
    provider = StaticVoiceQualificationProvider(error=RetryableVoiceQualificationError("429"))
    result = _service(provider).plan_lead(db_session, lead.id)
    assert result.items[0].skip_reason is VoiceSkipReason.PROVIDER_RETRYABLE_ERROR


def test_live_call_claim_is_blocked(db_session: Session) -> None:
    _organization, lead, _contact, _message = voice_call_request_bundle(db_session)
    provider = StaticVoiceQualificationProvider(
        {
            "accepted": True,
            "dry_run": False,
            "live_call_attempted": True,
            "call_placed": False,
            "provider_name": "voice_guarded",
            "facts": {},
            "raw": {"sent": False},
        }
    )
    result = _service(provider).plan_lead(db_session, lead.id)
    assert result.items[0].status is VoicePlanStatus.BLOCKED
    assert result.items[0].skip_reason is VoiceSkipReason.LIVE_CALL_REJECTED
    assert result.items[0].call_placed is False


def test_operator_halt_blocks_live_boundary(db_session: Session) -> None:
    _organization, lead, _contact, _message = voice_call_request_bundle(db_session)
    set_operator_halt(db_session, halted=True, reason="incident")
    inner = StubVoiceQualificationProvider()
    inner.live = True
    settings = Settings(outbound_enabled=True, outbound_halted=False, voice_live_enabled=True)
    provider = GuardedVoiceQualificationProvider(
        inner,
        OutboundGuard(settings),
        db_session,
        settings,
    )
    result = VoiceQualificationService(provider, settings=settings).plan_lead(db_session, lead.id)
    assert result.items[0].status is VoicePlanStatus.BLOCKED
    assert result.items[0].skip_reason is VoiceSkipReason.OPERATOR_GLOBAL_HALT
    assert inner.requests == []


def test_outbound_disabled_blocks_live_boundary(db_session: Session) -> None:
    _organization, lead, _contact, _message = voice_call_request_bundle(db_session)
    set_operator_halt(db_session, halted=False, reason="test_clear")
    inner = StubVoiceQualificationProvider()
    inner.live = True
    settings = Settings(outbound_enabled=False, voice_live_enabled=True)
    provider = GuardedVoiceQualificationProvider(
        inner,
        OutboundGuard(settings),
        db_session,
        settings,
    )
    result = VoiceQualificationService(provider, settings=settings).plan_lead(db_session, lead.id)
    assert result.items[0].status is VoicePlanStatus.BLOCKED
    assert result.items[0].skip_reason is VoiceSkipReason.GLOBAL_OUTBOUND_DISABLED
    assert inner.requests == []


def test_live_adapter_without_client_is_blocked(db_session: Session) -> None:
    _organization, lead, _contact, _message = voice_call_request_bundle(db_session)
    set_operator_halt(db_session, halted=False, reason="test_clear")
    settings = Settings(
        outbound_enabled=True,
        outbound_halted=False,
        voice_live_enabled=True,
        voice_api_key="placeholder",
        voice_api_base_url="https://voice.test/api/v1",
    )
    live = LiveVoiceQualificationProvider.from_settings(settings)
    provider = GuardedVoiceQualificationProvider(
        live,
        OutboundGuard(settings),
        db_session,
        settings,
    )
    result = VoiceQualificationService(provider, settings=settings).plan_lead(db_session, lead.id)
    assert result.items[0].status is VoicePlanStatus.BLOCKED
    assert result.items[0].skip_reason is VoiceSkipReason.LIVE_VOICE_NOT_IMPLEMENTED


def test_dry_run_voice_job_is_not_an_outbound_job() -> None:
    assert outbound_action_for_job(PLAN_VOICE_QUALIFICATIONS_JOB) is None


def test_stub_does_not_require_outbound_enabled(db_session: Session) -> None:
    _organization, lead, _contact, _message = voice_call_request_bundle(db_session)
    settings = Settings(outbound_enabled=False)
    result = VoiceQualificationService(
        StubVoiceQualificationProvider(),
        settings=settings,
    ).plan_lead(db_session, lead.id)
    assert result.items[0].status is VoicePlanStatus.PLANNED
    plan = db_session.get(VoiceQualificationPlan, result.items[0].voice_plan_id)
    assert plan is not None
    assert plan.audit_json["outbound_decision"] == "global_outbound_disabled"
    assert plan.audit_json["live_call_allowed"] is False


def test_stub_does_not_invent_facts(db_session: Session) -> None:
    _organization, lead, _contact, _message = voice_call_request_bundle(db_session)
    result = _service().plan_lead(db_session, lead.id)
    plan = db_session.get(VoiceQualificationPlan, result.items[0].voice_plan_id)
    assert plan is not None
    assert "denial" not in str(plan.facts_json).lower()
    assert "payer mix" not in str(plan.facts_json).lower()
    assert plan.facts_json.get("specialty") == "Family Medicine"
    assert plan.audit_json["fabricated_facts"] is False
    assert CALL_REQUEST_BODY not in str(plan.facts_json)
