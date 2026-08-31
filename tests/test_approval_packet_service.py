from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tests.test_dashboard_service import PHI_SNIPPET, PROSPECT_EMAIL, _seed_pipeline
from tests.test_review_queue_service import _seed_content_brief, _seed_optimizer_recommendation
from vyro_growth.config import Settings
from vyro_growth.domain import (
    EnrollmentStatus,
    ExecutionPlanType,
    PreflightStatus,
    RecommendationApprovalStatus,
    ReviewArtifactType,
    ReviewDecisionStatus,
)
from vyro_growth.models import (
    Activity,
    ApprovalPacketRun,
    BookingPlan,
    CampaignEnrollment,
    ChannelPlan,
    ChannelPlanRun,
    Lead,
    Meeting,
    OutreachMessage,
    OwnerApprovalPacket,
    OwnerApprovalPacketDecision,
    PersonalizationDraft,
    ReplyClassification,
    VoiceQualificationPlan,
)
from vyro_growth.services.approval_packets import (
    ApprovalPacketError,
    ApprovalPacketFilters,
    ApprovalPacketService,
)
from vyro_growth.services.execution_planning import ExecutionPlanningService
from vyro_growth.services.operator_halt import HaltStatus, read_operator_halt, set_operator_halt
from vyro_growth.services.review_queue import ReviewQueueService


def _settings(**overrides: object) -> Settings:
    return Settings(**overrides)


def _approve(
    db: Session,
    artifact_type: str,
    artifact_id: UUID,
    *,
    notes: str | None = None,
) -> None:
    ReviewQueueService().record_decision(
        db,
        artifact_type=artifact_type,
        artifact_id=artifact_id,
        decision=ReviewDecisionStatus.APPROVED.value,
        reviewer="ops",
        source="cli",
        reviewer_notes=notes,
    )


def _seed_channel_plan(db: Session) -> ChannelPlan:
    now = datetime.now(tz=UTC)
    run = ChannelPlanRun(
        status="completed",
        model_version="channel-planning-v1",
        snapshot_fingerprint=f"approval-{uuid4().hex}",
        plan_count=1,
        dry_run_only=True,
        no_spend=True,
        started_at=now,
        finished_at=now,
    )
    db.add(run)
    db.flush()
    row = ChannelPlan(
        channel_plan_run_id=run.id,
        plan_key="seo_content:family-medicine:tx",
        channel="seo_content",
        plan_type="landing_page_topic",
        title="SEO topic plan: Family Medicine / TX",
        summary="Dry-run acquisition channel plan. No spend.",
        target_specialty="Family Medicine",
        target_geography="TX",
        priority="medium",
        confidence=0.6,
        generated_at=now,
        approval_status=RecommendationApprovalStatus.PENDING_OPERATOR_REVIEW.value,
        dry_run_only=True,
        no_spend=True,
        launched=False,
    )
    db.add(row)
    db.flush()
    return row


def _approve_all_families(db: Session) -> None:
    _seed_pipeline(db)
    recommendation = _seed_optimizer_recommendation(db)
    brief = _seed_content_brief(db)
    channel = _seed_channel_plan(db)
    set_operator_halt(db, halted=True, reason="keep-halted")
    draft = db.scalars(select(PersonalizationDraft)).first()
    enrollment = db.scalars(
        select(CampaignEnrollment).where(
            CampaignEnrollment.status == EnrollmentStatus.PLANNED.value
        )
    ).first()
    assert draft is not None
    assert enrollment is not None
    reply = db.scalars(select(ReplyClassification)).first()
    booking = db.scalars(select(BookingPlan)).first()
    voice = db.scalars(select(VoiceQualificationPlan)).first()
    assert reply is not None
    assert booking is not None
    assert voice is not None
    _approve(db, ReviewArtifactType.PERSONALIZATION_DRAFT.value, draft.id)
    _approve(db, ReviewArtifactType.OUTREACH_ENROLLMENT_PLAN.value, enrollment.id)
    _approve(db, ReviewArtifactType.REPLY_FOLLOW_UP_PLAN.value, reply.id)
    _approve(db, ReviewArtifactType.BOOKING_PLAN.value, booking.id)
    _approve(db, ReviewArtifactType.VOICE_QUALIFICATION_PLAN.value, voice.id)
    _approve(db, ReviewArtifactType.OPTIMIZER_RECOMMENDATION.value, recommendation.id)
    _approve(db, ReviewArtifactType.ACQUISITION_CHANNEL_PLAN.value, channel.id)
    _approve(db, ReviewArtifactType.CONTENT_BRIEF.value, brief.id)


def test_empty_state_creates_dry_run_run_without_side_effects(db_session: Session) -> None:
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    before_activities = db_session.scalar(select(func.count()).select_from(Activity)) or 0

    result = ApprovalPacketService().generate(db_session, _settings())

    assert result.packet_count == 0
    assert result.packets == ()
    assert result.executed_count == 0
    assert result.dry_run_only is True
    assert result.no_execution is True
    assert result.execution_attempted is False
    assert result.outbound_attempted is False
    assert result.recommendation_applied is False
    assert result.operator_halt_before == HaltStatus.HALTED.value
    assert result.operator_halt_after == HaltStatus.HALTED.value
    assert (
        db_session.scalar(select(func.count()).select_from(Activity)) == before_activities + 1
    )
    assert read_operator_halt(db_session) is HaltStatus.HALTED


def test_execution_plans_receive_blocked_approval_packets(db_session: Session) -> None:
    _approve_all_families(db_session)
    ExecutionPlanningService().generate(db_session, _settings())

    result = ApprovalPacketService().generate(db_session, _settings())

    families = {item.plan_family for item in result.packets}
    assert families == {
        ExecutionPlanType.PERSONALIZATION_DRAFT.value,
        ExecutionPlanType.OUTREACH_ENROLLMENT.value,
        ExecutionPlanType.REPLY_FOLLOW_UP.value,
        ExecutionPlanType.BOOKING.value,
        ExecutionPlanType.VOICE_QUALIFICATION.value,
        ExecutionPlanType.OPTIMIZER_APPLY.value,
        ExecutionPlanType.ACQUISITION_CHANNEL_LAUNCH.value,
        ExecutionPlanType.CONTENT_PUBLISH.value,
    }
    assert result.packet_count == 8
    for item in result.packets:
        assert item.preflight_status == PreflightStatus.BLOCKED.value
        assert item.dry_run_only is True
        assert item.no_execution is True
        assert item.executed is False
        assert item.execution_attempted is False
        assert item.outbound_attempted is False
        assert item.owner_approval_required is True
        assert item.owner_approved is False
        codes = {finding["code"] for finding in item.findings}
        assert "execution_disabled_in_this_phase" in codes
        assert "owner_decision_required" in codes
        assert item.required_owner_decisions
        assert item.preflight_checklist
        assert item.missing_prerequisites
        assert item.source_execution_plan_id
        assert item.source_execution_plan_run_id
        assert item.source_artifact_type
        assert item.source_artifact_id
        assert item.idempotency_key


def test_generation_is_idempotent(db_session: Session) -> None:
    _seed_pipeline(db_session)
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    draft = db_session.scalars(select(PersonalizationDraft)).first()
    assert draft is not None
    _approve(db_session, ReviewArtifactType.PERSONALIZATION_DRAFT.value, draft.id)
    ExecutionPlanningService().generate(db_session, _settings())
    service = ApprovalPacketService()

    first = service.generate(db_session, _settings())
    second = service.generate(db_session, _settings())

    assert second.approval_packet_run_id == first.approval_packet_run_id
    assert second.reused_existing is True
    assert db_session.scalar(select(func.count()).select_from(ApprovalPacketRun)) == 1
    assert db_session.scalar(select(func.count()).select_from(OwnerApprovalPacket)) == 1
    activities = db_session.scalars(
        select(Activity).where(Activity.action == "approval_packets_generated")
    ).all()
    assert len(activities) == 1


def test_output_is_sanitized_and_does_not_execute(db_session: Session) -> None:
    _seed_pipeline(db_session)
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    draft = db_session.scalars(select(PersonalizationDraft)).first()
    assert draft is not None
    _approve(
        db_session,
        ReviewArtifactType.PERSONALIZATION_DRAFT.value,
        draft.id,
        notes=f"Call {PROSPECT_EMAIL} about {PHI_SNIPPET} sk-secretkeyvalue",
    )
    ExecutionPlanningService().generate(db_session, _settings())
    before_meetings = db_session.scalar(select(func.count()).select_from(Meeting))
    before_messages = db_session.scalar(select(func.count()).select_from(OutreachMessage))
    before_enrollments = db_session.scalar(select(func.count()).select_from(CampaignEnrollment))
    before_stage = db_session.scalar(select(Lead.stage))

    result = ApprovalPacketService().generate(db_session, _settings())
    payload = json.dumps(result.__dict__, default=str)

    assert PHI_SNIPPET not in payload
    assert PROSPECT_EMAIL not in payload
    assert "diabetes" not in payload.lower()
    assert "jordan.blake" not in payload.lower()
    assert "practice_summary" not in payload
    assert "opening_line" not in payload
    assert "5551112222" not in payload
    assert "sk-secretkeyvalue" not in payload
    assert result.executed_count == 0
    assert result.outbound_attempted is False
    assert db_session.scalar(select(func.count()).select_from(Meeting)) == before_meetings
    assert db_session.scalar(select(func.count()).select_from(OutreachMessage)) == before_messages
    assert (
        db_session.scalar(select(func.count()).select_from(CampaignEnrollment))
        == before_enrollments
    )
    assert db_session.scalar(select(Lead.stage)) == before_stage
    assert read_operator_halt(db_session) is HaltStatus.HALTED


def test_missing_secret_is_reported_without_exposing_value(db_session: Session) -> None:
    _seed_pipeline(db_session)
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    enrollment = db_session.scalars(
        select(CampaignEnrollment).where(
            CampaignEnrollment.status == EnrollmentStatus.PLANNED.value
        )
    ).first()
    assert enrollment is not None
    _approve(db_session, ReviewArtifactType.OUTREACH_ENROLLMENT_PLAN.value, enrollment.id)
    ExecutionPlanningService().generate(db_session, _settings())

    secret = "sk-secretkeyvalue-should-never-leak"
    with_secret = ApprovalPacketService().generate(
        db_session,
        _settings(smartlead_api_key=secret),
        filters=ApprovalPacketFilters(plan_type=ExecutionPlanType.OUTREACH_ENROLLMENT.value),
    )
    without_secret = ApprovalPacketService().generate(
        db_session,
        _settings(smartlead_api_key=""),
        filters=ApprovalPacketFilters(plan_type=ExecutionPlanType.OUTREACH_ENROLLMENT.value),
    )

    present_codes = {
        item["code"]: item.get("present")
        for packet in with_secret.packets
        for item in packet.preflight_checklist
    }
    absent_codes = {
        item["code"]: item.get("present")
        for packet in without_secret.packets
        for item in packet.preflight_checklist
    }
    assert present_codes.get("campaign_provider_api_key_configured") is True
    assert absent_codes.get("campaign_provider_api_key_configured") is False
    with_payload = json.dumps(with_secret.__dict__, default=str)
    without_payload = json.dumps(without_secret.__dict__, default=str)
    assert secret not in with_payload
    assert secret not in without_payload
    assert "sk-secretkeyvalue" not in with_payload
    finding_codes = {item["code"] for packet in without_secret.packets for item in packet.findings}
    assert "required_credential_absent" in finding_codes


def test_unknown_plan_type_is_rejected(db_session: Session) -> None:
    with pytest.raises(ApprovalPacketError) as exc:
        ApprovalPacketService().generate(
            db_session,
            _settings(),
            filters=ApprovalPacketFilters(plan_type="not_a_real_type"),
        )
    assert exc.value.code == "unknown_plan_type"


def test_latest_is_empty_before_generation(db_session: Session) -> None:
    assert ApprovalPacketService().latest(db_session) is None


def test_operator_halt_is_preserved(db_session: Session) -> None:
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    ApprovalPacketService().generate(db_session, _settings())
    assert read_operator_halt(db_session) is HaltStatus.HALTED


def test_record_decision_is_auditable_and_does_not_execute(db_session: Session) -> None:
    _approve_all_families(db_session)
    ExecutionPlanningService().generate(db_session, _settings())
    generated = ApprovalPacketService().generate(db_session, _settings())
    packet = generated.packets[0]
    before_meetings = db_session.scalar(select(func.count()).select_from(Meeting)) or 0
    before_enrollments = (
        db_session.scalar(select(func.count()).select_from(CampaignEnrollment)) or 0
    )
    before_messages = db_session.scalar(select(func.count()).select_from(OutreachMessage)) or 0

    recorded = ApprovalPacketService().record_decision(
        db_session,
        packet_id=packet.id,
        decision=ReviewDecisionStatus.APPROVED.value,
        reviewer="ops",
        source="cli",
        reviewer_notes="Record only",
    )
    stored_packet = db_session.get(OwnerApprovalPacket, packet.id)
    viewed = ApprovalPacketService().get_packet(db_session, packet.id)

    assert recorded.decision == ReviewDecisionStatus.APPROVED.value
    assert recorded.executed is False
    assert recorded.owner_approved is False
    assert recorded.operator_halt_before == HaltStatus.HALTED.value
    assert recorded.operator_halt_after == HaltStatus.HALTED.value
    assert stored_packet is not None
    assert stored_packet.owner_approved is False
    assert stored_packet.executed is False
    assert viewed is not None
    assert viewed.decision is not None
    assert viewed.decision.reviewer == "ops"
    assert viewed.owner_approved is False
    activities = db_session.scalars(
        select(Activity).where(Activity.action == "owner_approval_packet_decision_recorded")
    ).all()
    assert len(activities) == 1
    assert activities[0].details["executed"] is False
    assert activities[0].details["owner_approved"] is False
    assert db_session.scalar(select(func.count()).select_from(Meeting)) == before_meetings
    assert (
        db_session.scalar(select(func.count()).select_from(CampaignEnrollment))
        == before_enrollments
    )
    assert db_session.scalar(select(func.count()).select_from(OutreachMessage)) == before_messages
    assert read_operator_halt(db_session) is HaltStatus.HALTED


def test_packet_decision_can_be_updated_without_execution(db_session: Session) -> None:
    _approve_all_families(db_session)
    ExecutionPlanningService().generate(db_session, _settings())
    packet = ApprovalPacketService().generate(db_session, _settings()).packets[0]
    service = ApprovalPacketService()
    first = service.record_decision(
        db_session,
        packet_id=packet.id,
        decision=ReviewDecisionStatus.APPROVED.value,
        reviewer="ops",
    )
    second = service.record_decision(
        db_session,
        packet_id=packet.id,
        decision=ReviewDecisionStatus.NEEDS_CHANGES.value,
        reviewer="ops",
    )
    stored = db_session.scalar(select(OwnerApprovalPacketDecision))

    assert first.decision_id == second.decision_id
    assert second.decision == ReviewDecisionStatus.NEEDS_CHANGES.value
    assert stored is not None
    assert stored.previous_decision == ReviewDecisionStatus.APPROVED.value
    assert stored.executed is False
    assert stored.owner_approved is False
    assert db_session.scalar(select(func.count()).select_from(OwnerApprovalPacketDecision)) == 1


def test_packet_decision_rejects_invalid_and_missing(db_session: Session) -> None:
    service = ApprovalPacketService()
    with pytest.raises(ApprovalPacketError) as missing:
        service.record_decision(
            db_session,
            packet_id=uuid4(),
            decision=ReviewDecisionStatus.APPROVED.value,
        )
    assert missing.value.code == "packet_not_found"

    _approve_all_families(db_session)
    ExecutionPlanningService().generate(db_session, _settings())
    packet = service.generate(db_session, _settings()).packets[0]
    with pytest.raises(ApprovalPacketError) as bad_decision:
        service.record_decision(
            db_session,
            packet_id=packet.id,
            decision="ship_it",
        )
    assert bad_decision.value.code == "invalid_decision"
    assert db_session.scalar(select(func.count()).select_from(OwnerApprovalPacketDecision)) == 0


def test_packet_decision_notes_are_sanitized(db_session: Session) -> None:
    _approve_all_families(db_session)
    ExecutionPlanningService().generate(db_session, _settings())
    packet = ApprovalPacketService().generate(db_session, _settings()).packets[0]
    recorded = ApprovalPacketService().record_decision(
        db_session,
        packet_id=packet.id,
        decision=ReviewDecisionStatus.REJECTED.value,
        reviewer="ops",
        reviewer_notes=f"Call {PROSPECT_EMAIL} about {PHI_SNIPPET} sk-testsecret12345",
    )
    payload = json.dumps(recorded.__dict__, default=str)
    assert recorded.reviewer_notes == "[REDACTED_UNSAFE_TEXT]"
    assert PROSPECT_EMAIL not in payload
    assert PHI_SNIPPET not in payload
    assert "sk-testsecret12345" not in payload
    assert recorded.executed is False
    assert recorded.owner_approved is False
