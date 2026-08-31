from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tests.test_dashboard_service import PHI_SNIPPET, PROSPECT_EMAIL, _seed_pipeline
from vyro_growth.config import Settings
from vyro_growth.domain import (
    ContentBriefApprovalStatus,
    EnrollmentStatus,
    RecommendationApprovalStatus,
    ReviewArtifactType,
    ReviewDecisionStatus,
)
from vyro_growth.models import (
    Activity,
    CampaignEnrollment,
    ChannelPlan,
    ContentBrief,
    ContentBriefRun,
    Lead,
    Meeting,
    OperatorReviewDecision,
    OptimizerRecommendation,
    OptimizerRun,
    OutreachMessage,
    PersonalizationDraft,
)
from vyro_growth.services.channel_planning import ChannelPlanningService, ChannelPlanSeeds
from vyro_growth.services.operator_halt import HaltStatus, read_operator_halt, set_operator_halt
from vyro_growth.services.review_queue import ReviewQueueError, ReviewQueueService


def _settings(**overrides: object) -> Settings:
    return Settings(**overrides)


def test_empty_queue_is_safe(db_session: Session) -> None:
    result = ReviewQueueService().list_queue(db_session, _settings())

    assert result.pending_count == 0
    assert result.decided_count == 0
    assert result.items == ()
    assert result.executed_count == 0
    assert result.outbound_attempted is False
    assert result.live_call_attempted is False
    assert result.recommendation_applied is False
    assert result.operator_halt_status == HaltStatus.UNAVAILABLE.value


def test_populated_queue_normalizes_pending_artifacts(db_session: Session) -> None:
    _seed_pipeline(db_session)
    recommendation = _seed_optimizer_recommendation(db_session)
    set_operator_halt(db_session, halted=True, reason="keep-halted")

    result = ReviewQueueService().list_queue(db_session, _settings())

    types = {item.artifact_type for item in result.items}
    assert types == {
        ReviewArtifactType.PERSONALIZATION_DRAFT.value,
        ReviewArtifactType.OUTREACH_ENROLLMENT_PLAN.value,
        ReviewArtifactType.REPLY_FOLLOW_UP_PLAN.value,
        ReviewArtifactType.BOOKING_PLAN.value,
        ReviewArtifactType.VOICE_QUALIFICATION_PLAN.value,
        ReviewArtifactType.OPTIMIZER_RECOMMENDATION.value,
    }
    assert result.pending_count == 6
    assert result.decided_count == 0
    assert any(item.artifact_id == recommendation.id for item in result.items)
    for item in result.items:
        assert item.status == "pending_operator_review"
        assert item.executed is False
        assert item.executable_later is True
        assert "decision_record_only" in item.risk_labels
        assert "not_executed" in item.risk_labels
        assert "operator_halt_active" in item.risk_labels
        assert item.decision is None


def test_skipped_artifacts_are_not_reviewable(db_session: Session) -> None:
    _seed_pipeline(db_session)
    skipped = db_session.scalars(
        select(CampaignEnrollment).where(
            CampaignEnrollment.status == EnrollmentStatus.SKIPPED.value
        )
    ).first()
    assert skipped is not None

    result = ReviewQueueService().list_queue(db_session, _settings())
    assert skipped.id not in {item.artifact_id for item in result.items}

    with pytest.raises(ReviewQueueError, match="not pending operator review") as exc:
        ReviewQueueService().record_decision(
            db_session,
            artifact_type=ReviewArtifactType.OUTREACH_ENROLLMENT_PLAN.value,
            artifact_id=skipped.id,
            decision=ReviewDecisionStatus.APPROVED.value,
        )
    assert exc.value.code == "artifact_not_reviewable"


def test_record_decision_is_auditable_and_does_not_execute(db_session: Session) -> None:
    _seed_pipeline(db_session)
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    draft = db_session.scalars(select(PersonalizationDraft)).first()
    assert draft is not None
    before_meetings = db_session.scalar(select(func.count()).select_from(Meeting))
    before_messages = db_session.scalar(select(func.count()).select_from(OutreachMessage))
    before_enrollments = db_session.scalar(select(func.count()).select_from(CampaignEnrollment))
    before_stage = db_session.scalar(select(Lead.stage))

    recorded = ReviewQueueService().record_decision(
        db_session,
        artifact_type=ReviewArtifactType.PERSONALIZATION_DRAFT.value,
        artifact_id=draft.id,
        decision=ReviewDecisionStatus.APPROVED.value,
        reviewer="ops",
        source="cli",
        reviewer_notes="Looks ready for a later phase",
    )

    assert recorded.executed is False
    assert recorded.execution_attempted is False
    assert recorded.outbound_attempted is False
    assert recorded.recommendation_applied is False
    assert recorded.decision == ReviewDecisionStatus.APPROVED.value
    assert recorded.reviewer == "ops"
    assert recorded.source == "cli"
    assert recorded.operator_halt_before == HaltStatus.HALTED.value
    assert recorded.operator_halt_after == HaltStatus.HALTED.value

    pending = ReviewQueueService().list_queue(db_session, _settings())
    assert draft.id not in {item.artifact_id for item in pending.items}
    assert pending.decided_count == 1

    decided = ReviewQueueService().list_queue(db_session, _settings(), include_decided=True)
    match = next(item for item in decided.items if item.artifact_id == draft.id)
    assert match.status == ReviewDecisionStatus.APPROVED.value
    assert match.decision is not None
    assert match.decision.reviewer == "ops"
    assert match.executed is False
    assert match.executable_later is True

    stored = db_session.scalar(select(OperatorReviewDecision))
    assert stored is not None
    assert stored.executed is False
    assert stored.outbound_attempted is False
    activities = db_session.scalars(
        select(Activity).where(Activity.action == "operator_review_decision_recorded")
    ).all()
    assert len(activities) == 1
    assert activities[0].details["executed"] is False
    assert db_session.scalar(select(func.count()).select_from(Meeting)) == before_meetings
    assert db_session.scalar(select(func.count()).select_from(OutreachMessage)) == before_messages
    assert (
        db_session.scalar(select(func.count()).select_from(CampaignEnrollment))
        == before_enrollments
    )
    assert db_session.scalar(select(Lead.stage)) == before_stage
    assert read_operator_halt(db_session) is HaltStatus.HALTED


def test_decision_can_be_updated_without_execution(db_session: Session) -> None:
    _seed_pipeline(db_session)
    plan = db_session.scalars(
        select(CampaignEnrollment).where(
            CampaignEnrollment.status == EnrollmentStatus.PLANNED.value
        )
    ).first()
    assert plan is not None
    service = ReviewQueueService()

    first = service.record_decision(
        db_session,
        artifact_type=ReviewArtifactType.OUTREACH_ENROLLMENT_PLAN.value,
        artifact_id=plan.id,
        decision=ReviewDecisionStatus.APPROVED.value,
        reviewer="ops",
    )
    second = service.record_decision(
        db_session,
        artifact_type=ReviewArtifactType.OUTREACH_ENROLLMENT_PLAN.value,
        artifact_id=plan.id,
        decision=ReviewDecisionStatus.NEEDS_CHANGES.value,
        reviewer="ops",
        reviewer_notes="Hold for later review",
    )

    assert first.decision_id == second.decision_id
    assert second.decision == ReviewDecisionStatus.NEEDS_CHANGES.value
    assert db_session.scalar(select(func.count()).select_from(OperatorReviewDecision)) == 1
    stored = db_session.scalar(select(OperatorReviewDecision))
    assert stored is not None
    assert stored.previous_decision == ReviewDecisionStatus.APPROVED.value
    assert stored.executed is False
    activities = db_session.scalars(
        select(Activity).where(Activity.action == "operator_review_decision_recorded")
    ).all()
    assert len(activities) == 2


def test_invalid_artifact_handling(db_session: Session) -> None:
    service = ReviewQueueService()
    missing_id = uuid4()

    with pytest.raises(ReviewQueueError) as unknown:
        service.record_decision(
            db_session,
            artifact_type="not_a_real_type",
            artifact_id=missing_id,
            decision=ReviewDecisionStatus.APPROVED.value,
        )
    assert unknown.value.code == "unknown_artifact_type"

    with pytest.raises(ReviewQueueError) as missing:
        service.record_decision(
            db_session,
            artifact_type=ReviewArtifactType.BOOKING_PLAN.value,
            artifact_id=missing_id,
            decision=ReviewDecisionStatus.APPROVED.value,
        )
    assert missing.value.code == "artifact_not_found"

    with pytest.raises(ReviewQueueError) as invalid:
        service.list_queue(db_session, _settings(), artifact_type="not_a_real_type")
    assert invalid.value.code == "unknown_artifact_type"

    with pytest.raises(ReviewQueueError) as bad_decision:
        service.record_decision(
            db_session,
            artifact_type=ReviewArtifactType.BOOKING_PLAN.value,
            artifact_id=missing_id,
            decision="ship_it",
        )
    assert bad_decision.value.code == "invalid_decision"


def test_output_is_sanitized(db_session: Session) -> None:
    _seed_pipeline(db_session)
    _seed_optimizer_recommendation(db_session)
    result = ReviewQueueService().list_queue(db_session, _settings())
    payload = json.dumps(result.__dict__, default=str)
    recorded = ReviewQueueService().record_decision(
        db_session,
        artifact_type=ReviewArtifactType.VOICE_QUALIFICATION_PLAN.value,
        artifact_id=next(
            item.artifact_id
            for item in result.items
            if item.artifact_type == ReviewArtifactType.VOICE_QUALIFICATION_PLAN.value
        ),
        decision=ReviewDecisionStatus.REJECTED.value,
        reviewer_notes=f"Call {PROSPECT_EMAIL} about {PHI_SNIPPET} sk-secretkeyvalue",
    )
    decision_payload = json.dumps(recorded.__dict__, default=str)

    for text in (payload, decision_payload):
        assert PHI_SNIPPET not in text
        assert PROSPECT_EMAIL not in text
        assert "diabetes" not in text.lower()
        assert "jordan.blake" not in text.lower()
        assert "practice_summary" not in text
        assert "opening_line" not in text
        assert "permitted_phone" not in text
        assert "evidence_snippet" not in text
        assert "5551112222" not in text
        assert "sk-secretkeyvalue" not in text
    assert recorded.reviewer_notes == "[REDACTED_UNSAFE_TEXT]"


def test_content_briefs_appear_in_queue_and_approval_does_not_publish(
    db_session: Session,
) -> None:
    brief = _seed_content_brief(db_session)
    set_operator_halt(db_session, halted=True, reason="keep-halted")

    listed = ReviewQueueService().list_queue(
        db_session,
        _settings(),
        artifact_type=ReviewArtifactType.CONTENT_BRIEF.value,
    )
    recorded = ReviewQueueService().record_decision(
        db_session,
        artifact_type=ReviewArtifactType.CONTENT_BRIEF.value,
        artifact_id=brief.id,
        decision=ReviewDecisionStatus.APPROVED.value,
        reviewer="ops",
    )

    assert listed.pending_count == 1
    assert listed.items[0].artifact_id == brief.id
    assert listed.items[0].executed is False
    assert "not_published" in listed.items[0].risk_labels
    assert recorded.executed is False
    assert recorded.execution_attempted is False
    assert recorded.outbound_attempted is False
    db_session.refresh(brief)
    assert brief.published is False
    assert brief.publish_attempted is False
    assert read_operator_halt(db_session) is HaltStatus.HALTED


def test_channel_plans_appear_in_queue_and_approval_does_not_launch(
    db_session: Session,
) -> None:
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    planned = ChannelPlanningService().plan(
        db_session,
        seeds=ChannelPlanSeeds(specialty="Family Medicine", geography="TX"),
    )
    assert planned.plan_count > 0
    first = planned.plans[0]
    before_launched = db_session.scalar(select(func.count()).select_from(ChannelPlan))

    result = ReviewQueueService().list_queue(
        db_session,
        _settings(),
        artifact_type=ReviewArtifactType.ACQUISITION_CHANNEL_PLAN.value,
    )
    assert result.pending_count == planned.plan_count
    assert all(
        item.artifact_type == ReviewArtifactType.ACQUISITION_CHANNEL_PLAN.value
        for item in result.items
    )
    assert "no_spend" in result.items[0].risk_labels
    assert "not_launched" in result.items[0].risk_labels

    recorded = ReviewQueueService().record_decision(
        db_session,
        artifact_type=ReviewArtifactType.ACQUISITION_CHANNEL_PLAN.value,
        artifact_id=first.id,
        decision=ReviewDecisionStatus.APPROVED.value,
        reviewer="ops",
        source="cli",
        reviewer_notes="Looks like a later-phase concept",
    )
    assert recorded.executed is False
    assert recorded.execution_attempted is False
    assert recorded.outbound_attempted is False
    row = db_session.get(ChannelPlan, first.id)
    assert row is not None
    assert row.launched is False
    assert row.spend_attempted is False
    assert row.campaign_launched is False
    assert row.pages_published is False
    assert row.approval_status == RecommendationApprovalStatus.PENDING_OPERATOR_REVIEW.value
    assert db_session.scalar(select(func.count()).select_from(ChannelPlan)) == before_launched
    assert read_operator_halt(db_session) is HaltStatus.HALTED


def test_list_queue_does_not_write_rows(db_session: Session) -> None:
    _seed_pipeline(db_session)
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    before_activities = db_session.scalar(select(func.count()).select_from(Activity))
    before_decisions = db_session.scalar(select(func.count()).select_from(OperatorReviewDecision))

    ReviewQueueService().list_queue(db_session, _settings())

    assert db_session.scalar(select(func.count()).select_from(Activity)) == before_activities
    assert (
        db_session.scalar(select(func.count()).select_from(OperatorReviewDecision))
        == before_decisions
    )
    assert read_operator_halt(db_session) is HaltStatus.HALTED


def _seed_optimizer_recommendation(db: Session) -> OptimizerRecommendation:
    now = datetime.now(tz=UTC)
    run = OptimizerRun(
        status="completed",
        model_version="growth-optimizer-v1",
        snapshot_fingerprint=f"review-{uuid4().hex}",
        recommendation_count=1,
        dry_run_only=True,
        outbound_attempted=False,
        live_call_attempted=False,
        started_at=now,
        finished_at=now,
    )
    db.add(run)
    db.flush()
    row = OptimizerRecommendation(
        optimizer_run_id=run.id,
        recommendation_key="website_enrichment_gap",
        category="website_enrichment_gap",
        priority="medium",
        confidence=0.7,
        title="Review website enrichment coverage gaps",
        rationale="Counts only. No prospect copy.",
        source_metrics_json={"organizations": 1},
        generated_at=now,
        approval_status=RecommendationApprovalStatus.PENDING_OPERATOR_REVIEW.value,
        applied=False,
    )
    db.add(row)
    db.flush()
    return row


def _seed_content_brief(db: Session) -> ContentBrief:
    now = datetime.now(tz=UTC)
    run = ContentBriefRun(
        status="completed",
        model_version="content-brief-v1",
        snapshot_fingerprint=f"review-{uuid4().hex}",
        brief_count=1,
        dry_run_only=True,
        published=False,
        publish_attempted=False,
        outbound_attempted=False,
        ads_launched=False,
        spend_attempted=False,
        started_at=now,
        finished_at=now,
    )
    db.add(run)
    db.flush()
    row = ContentBrief(
        content_brief_run_id=run.id,
        brief_key="specialty_landing_page:family-medicine",
        brief_type="specialty_landing_page",
        specialty="Family Medicine",
        geography="TX",
        priority="low",
        confidence=0.6,
        title="Specialty landing page brief: Family Medicine / TX",
        summary="Review-only outline. No page is published.",
        outline_sections=["Audience: Family Medicine / TX."],
        recommended_cta="Invite a practice decision-maker to request a conversation.",
        compliance_notes=["Review-only brief. Do not publish this page or article."],
        source_references={"source_kind": "operator_seed"},
        generated_at=now,
        approval_status=ContentBriefApprovalStatus.PENDING_OPERATOR_REVIEW.value,
        published=False,
        publish_attempted=False,
        dry_run_only=True,
    )
    db.add(row)
    db.flush()
    return row
