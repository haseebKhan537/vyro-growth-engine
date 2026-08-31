from __future__ import annotations

import json
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tests.test_approval_packet_service import _approve_all_families
from tests.test_dashboard_service import PHI_SNIPPET, PROSPECT_EMAIL, _seed_pipeline
from tests.test_review_queue_service import _seed_optimizer_recommendation
from vyro_growth.config import Settings
from vyro_growth.domain import (
    ActionDecisionStatus,
    ActionReadinessBlockerStatus,
    ActionReadinessStatus,
    ExecutionPlanType,
    PreflightStatus,
    ReviewArtifactType,
    ReviewDecisionStatus,
)
from vyro_growth.models import (
    Activity,
    CampaignEnrollment,
    ExecutionPlan,
    Lead,
    Meeting,
    OperatorReviewDecision,
    OutreachMessage,
    OwnerApprovalPacket,
    PersonalizationDraft,
)
from vyro_growth.services.action_readiness import ActionReadinessFilters, ActionReadinessService
from vyro_growth.services.approval_packets import ApprovalPacketService
from vyro_growth.services.execution_planning import ExecutionPlanningService
from vyro_growth.services.operator_halt import HaltStatus, read_operator_halt, set_operator_halt
from vyro_growth.services.review_queue import ReviewQueueService


def _settings(**overrides: object) -> Settings:
    return Settings(**overrides)


def _seed_plans_and_packets(db: Session) -> None:
    _approve_all_families(db)
    ExecutionPlanningService().generate(db, _settings())
    ApprovalPacketService().generate(db, _settings())


def _counts(db: Session) -> dict[str, int]:
    return {
        "activities": int(db.scalar(select(func.count()).select_from(Activity)) or 0),
        "meetings": int(db.scalar(select(func.count()).select_from(Meeting)) or 0),
        "enrollments": int(db.scalar(select(func.count()).select_from(CampaignEnrollment)) or 0),
        "messages": int(db.scalar(select(func.count()).select_from(OutreachMessage)) or 0),
        "plans": int(db.scalar(select(func.count()).select_from(ExecutionPlan)) or 0),
        "packets": int(db.scalar(select(func.count()).select_from(OwnerApprovalPacket)) or 0),
    }


def test_empty_queue_is_read_only_without_side_effects(db_session: Session) -> None:
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    before = _counts(db_session)

    result = ActionReadinessService().list_queue(db_session, _settings())

    assert result.candidate_count == 0
    assert result.candidates == ()
    assert result.executed_count == 0
    assert result.dry_run_only is True
    assert result.no_execution is True
    assert result.live_action is False
    assert result.read_only is True
    assert result.explicit_live_owner_action_required is True
    assert result.outbound_attempted is False
    assert result.operator_halt_before == HaltStatus.HALTED.value
    assert result.operator_halt_after == HaltStatus.HALTED.value
    assert _counts(db_session) == before
    assert read_operator_halt(db_session) is HaltStatus.HALTED


def test_populated_candidates_are_missing_packet_decision(db_session: Session) -> None:
    _seed_plans_and_packets(db_session)
    before = _counts(db_session)

    result = ActionReadinessService().list_queue(db_session, _settings())

    assert result.candidate_count == 8
    families = {item.plan_family for item in result.candidates}
    assert ExecutionPlanType.OUTREACH_ENROLLMENT.value in families
    assert ExecutionPlanType.OPTIMIZER_APPLY.value in families
    for item in result.candidates:
        assert item.review_decision_status == ActionDecisionStatus.APPROVED.value
        assert item.packet_decision_status == ActionDecisionStatus.MISSING.value
        assert item.readiness_status == (
            ActionReadinessStatus.MISSING_OWNER_PACKET_DECISION.value
        )
        assert item.blocker_status == ActionReadinessBlockerStatus.BLOCKED.value
        assert item.dry_run_only is True
        assert item.no_execution is True
        assert item.executed is False
        assert item.live_action is False
        assert item.owner_approved is False
        assert item.explicit_live_owner_action_required is True
        assert "execution_disabled_in_this_phase" in item.blocker_codes
        assert "missing_owner_packet_decision" in item.missing_approval_codes
        assert "live_action_requires_explicit_owner_action" in item.blocker_codes
    assert _counts(db_session) == before
    assert read_operator_halt(db_session) is HaltStatus.HALTED


def test_missing_review_decision_status(db_session: Session) -> None:
    _seed_plans_and_packets(db_session)
    draft = db_session.scalars(select(PersonalizationDraft)).first()
    assert draft is not None
    row = db_session.scalar(
        select(OperatorReviewDecision).where(
            OperatorReviewDecision.artifact_type
            == ReviewArtifactType.PERSONALIZATION_DRAFT.value,
            OperatorReviewDecision.artifact_id == draft.id,
        )
    )
    assert row is not None
    db_session.delete(row)
    db_session.flush()

    result = ActionReadinessService().list_queue(
        db_session,
        _settings(),
        filters=ActionReadinessFilters(
            plan_family=ExecutionPlanType.PERSONALIZATION_DRAFT.value
        ),
    )

    assert result.candidate_count == 1
    item = result.candidates[0]
    assert item.readiness_status == ActionReadinessStatus.MISSING_REVIEW_DECISION.value
    assert item.review_decision_status == ActionDecisionStatus.MISSING.value
    assert "missing_review_decision" in item.missing_approval_codes
    assert item.executed is False
    assert item.live_action is False


def test_rejected_review_decision_is_blocked(db_session: Session) -> None:
    _seed_plans_and_packets(db_session)
    draft = db_session.scalars(select(PersonalizationDraft)).first()
    assert draft is not None
    row = db_session.scalar(
        select(OperatorReviewDecision).where(
            OperatorReviewDecision.artifact_type
            == ReviewArtifactType.PERSONALIZATION_DRAFT.value,
            OperatorReviewDecision.artifact_id == draft.id,
        )
    )
    assert row is not None
    row.decision = ReviewDecisionStatus.REJECTED.value
    db_session.flush()

    result = ActionReadinessService().list_queue(
        db_session,
        _settings(),
        filters=ActionReadinessFilters(
            plan_family=ExecutionPlanType.PERSONALIZATION_DRAFT.value
        ),
    )

    assert result.candidate_count == 1
    item = result.candidates[0]
    assert item.readiness_status == ActionReadinessStatus.BLOCKED.value
    assert item.review_decision_status == ActionDecisionStatus.REJECTED.value
    assert "review_decision_not_approved" in item.missing_approval_codes
    assert item.executed is False
    assert item.live_action is False


def test_packet_decision_approved_stays_preflight_blocked(db_session: Session) -> None:
    _seed_plans_and_packets(db_session)
    packet = db_session.scalars(select(OwnerApprovalPacket)).first()
    assert packet is not None
    ApprovalPacketService().record_decision(
        db_session,
        packet_id=packet.id,
        decision=ReviewDecisionStatus.APPROVED.value,
        reviewer="ops",
        source="cli",
    )

    result = ActionReadinessService().list_queue(
        db_session,
        _settings(),
        filters=ActionReadinessFilters(plan_family=packet.plan_family),
    )
    item = next(
        candidate
        for candidate in result.candidates
        if candidate.approval_packet_id == packet.id
    )

    assert item.packet_decision_status == ActionDecisionStatus.APPROVED.value
    assert item.readiness_status == ActionReadinessStatus.PREFLIGHT_BLOCKED.value
    assert item.preflight_status == PreflightStatus.BLOCKED.value
    assert item.owner_approved is False
    assert item.executed is False
    assert item.live_action is False
    assert packet.owner_approved is False


def test_approved_but_halted_when_preflight_awaits_owner(db_session: Session) -> None:
    _seed_plans_and_packets(db_session)
    packet = db_session.scalars(select(OwnerApprovalPacket)).first()
    assert packet is not None
    ApprovalPacketService().record_decision(
        db_session,
        packet_id=packet.id,
        decision=ReviewDecisionStatus.APPROVED.value,
        reviewer="ops",
    )
    packet.preflight_status = PreflightStatus.AWAITING_OWNER_DECISION.value
    db_session.flush()

    result = ActionReadinessService().get_candidate(
        db_session,
        _settings(),
        packet.source_execution_plan_id,
    )

    assert result is not None
    assert result.readiness_status == ActionReadinessStatus.APPROVED_BUT_HALTED.value
    assert result.blocker_status == ActionReadinessBlockerStatus.BLOCKED.value
    assert "operator_halt_active" in result.blocker_codes
    assert result.executed is False
    assert result.live_action is False
    assert result.owner_approved is False
    assert read_operator_halt(db_session) is HaltStatus.HALTED


def test_ready_pending_still_requires_explicit_owner_action(db_session: Session) -> None:
    _seed_plans_and_packets(db_session)
    packet = db_session.scalars(select(OwnerApprovalPacket)).first()
    assert packet is not None
    ApprovalPacketService().record_decision(
        db_session,
        packet_id=packet.id,
        decision=ReviewDecisionStatus.APPROVED.value,
        reviewer="ops",
    )
    packet.preflight_status = PreflightStatus.AWAITING_OWNER_DECISION.value
    db_session.flush()
    set_operator_halt(db_session, halted=False, reason="cleared-for-readiness-view")
    before = _counts(db_session)
    before_stage = db_session.scalar(select(Lead.stage))

    result = ActionReadinessService().get_candidate(
        db_session,
        _settings(),
        packet.source_execution_plan_id,
    )

    assert result is not None
    assert result.readiness_status == (
        ActionReadinessStatus.READY_PENDING_EXPLICIT_LIVE_OWNER_ACTION.value
    )
    assert result.blocker_status == ActionReadinessBlockerStatus.PHASE_SAFETY_ONLY.value
    assert result.explicit_live_owner_action_required is True
    assert result.executed is False
    assert result.live_action is False
    assert result.owner_approved is False
    assert result.no_execution is True
    assert "live_action_requires_explicit_owner_action" in result.blocker_codes
    assert _counts(db_session) == before
    assert db_session.scalar(select(Lead.stage)) == before_stage
    assert read_operator_halt(db_session) is HaltStatus.CLEARED
    stored = db_session.get(OwnerApprovalPacket, packet.id)
    assert stored is not None
    assert stored.owner_approved is False
    assert stored.executed is False


def test_filters_limit_plan_family_and_readiness(db_session: Session) -> None:
    _seed_plans_and_packets(db_session)
    service = ActionReadinessService()

    family = service.list_queue(
        db_session,
        _settings(),
        filters=ActionReadinessFilters(
            plan_family=ExecutionPlanType.CONTENT_PUBLISH.value
        ),
    )
    readiness = service.list_queue(
        db_session,
        _settings(),
        filters=ActionReadinessFilters(
            readiness_status=ActionReadinessStatus.MISSING_OWNER_PACKET_DECISION.value
        ),
    )
    unknown = service.list_queue(
        db_session,
        _settings(),
        filters=ActionReadinessFilters(plan_family="execute_now"),
    )

    blockers = service.list_queue(
        db_session,
        _settings(),
        filters=ActionReadinessFilters(
            blocker_status=ActionReadinessBlockerStatus.BLOCKED.value
        ),
    )
    decisions = service.list_queue(
        db_session,
        _settings(),
        filters=ActionReadinessFilters(
            decision_status=ActionDecisionStatus.APPROVED.value
        ),
    )
    assert family.candidate_count == 1
    assert family.candidates[0].plan_family == ExecutionPlanType.CONTENT_PUBLISH.value
    assert readiness.candidate_count == 8
    assert blockers.candidate_count == 8
    assert decisions.candidate_count == 8
    assert unknown.candidate_count == 8


def test_output_is_sanitized_and_does_not_execute(db_session: Session) -> None:
    _seed_pipeline(db_session)
    recommendation = _seed_optimizer_recommendation(db_session)
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    ReviewQueueService().record_decision(
        db_session,
        artifact_type=ReviewArtifactType.OPTIMIZER_RECOMMENDATION.value,
        artifact_id=recommendation.id,
        decision=ReviewDecisionStatus.APPROVED.value,
        reviewer="ops",
        reviewer_notes=f"Call {PROSPECT_EMAIL} about {PHI_SNIPPET} sk-secretkeyvalue",
    )
    ExecutionPlanningService().generate(db_session, _settings())
    generated = ApprovalPacketService().generate(db_session, _settings())
    packet = generated.packets[0]
    stored = db_session.get(OwnerApprovalPacket, packet.id)
    assert stored is not None
    stored.proposed_action = f"Email {PROSPECT_EMAIL} about {PHI_SNIPPET}"
    db_session.flush()
    before = _counts(db_session)

    result = ActionReadinessService().list_queue(db_session, _settings())
    payload = json.dumps(result, default=str)

    assert PHI_SNIPPET not in payload
    assert PROSPECT_EMAIL not in payload
    assert "diabetes" not in payload.lower()
    assert "sk-secretkeyvalue" not in payload
    assert "practice_summary" not in payload
    for item in result.candidates:
        assert item.sanitized_label
        assert "@" not in item.sanitized_label
        assert item.executed is False
        assert item.live_action is False
        assert item.owner_approved is False
    assert _counts(db_session) == before
    assert read_operator_halt(db_session) is HaltStatus.HALTED


def test_get_candidate_unknown_id_returns_none(db_session: Session) -> None:
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    missing = ActionReadinessService().get_candidate(
        db_session,
        _settings(),
        UUID("00000000-0000-0000-0000-000000000001"),
    )
    assert missing is None
    assert read_operator_halt(db_session) is HaltStatus.HALTED
