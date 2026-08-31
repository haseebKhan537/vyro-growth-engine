from __future__ import annotations

import json
from uuid import UUID

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tests.test_dashboard_service import PHI_SNIPPET, PROSPECT_EMAIL, _seed_pipeline
from tests.test_review_queue_service import _seed_content_brief, _seed_optimizer_recommendation
from vyro_growth.config import Settings
from vyro_growth.domain import (
    EnrollmentStatus,
    ExecutionPlanType,
    ExecutionReadinessStatus,
    ReviewArtifactType,
    ReviewDecisionStatus,
)
from vyro_growth.models import (
    Activity,
    CampaignEnrollment,
    ExecutionPlan,
    ExecutionPlanRun,
    Lead,
    Meeting,
    OutreachMessage,
    PersonalizationDraft,
)
from vyro_growth.services.execution_planning import (
    ExecutionPlanFilters,
    ExecutionPlanningError,
    ExecutionPlanningService,
)
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


def test_empty_state_creates_dry_run_run_without_side_effects(db_session: Session) -> None:
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    before_activities = db_session.scalar(select(func.count()).select_from(Activity)) or 0

    result = ExecutionPlanningService().generate(db_session, _settings())

    assert result.plan_count == 0
    assert result.plans == ()
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


def test_approved_artifacts_receive_blocked_dry_run_plans(db_session: Session) -> None:
    _seed_pipeline(db_session)
    recommendation = _seed_optimizer_recommendation(db_session)
    brief = _seed_content_brief(db_session)
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    draft = db_session.scalars(select(PersonalizationDraft)).first()
    assert draft is not None
    enrollment = db_session.scalars(
        select(CampaignEnrollment).where(
            CampaignEnrollment.status == EnrollmentStatus.PLANNED.value
        )
    ).first()
    assert enrollment is not None
    _approve(db_session, ReviewArtifactType.PERSONALIZATION_DRAFT.value, draft.id)
    _approve(db_session, ReviewArtifactType.OUTREACH_ENROLLMENT_PLAN.value, enrollment.id)
    _approve(db_session, ReviewArtifactType.OPTIMIZER_RECOMMENDATION.value, recommendation.id)
    _approve(db_session, ReviewArtifactType.CONTENT_BRIEF.value, brief.id)

    result = ExecutionPlanningService().generate(db_session, _settings())

    types = {item.plan_type for item in result.plans}
    assert types == {
        ExecutionPlanType.PERSONALIZATION_DRAFT.value,
        ExecutionPlanType.OUTREACH_ENROLLMENT.value,
        ExecutionPlanType.OPTIMIZER_APPLY.value,
        ExecutionPlanType.CONTENT_PUBLISH.value,
    }
    assert result.plan_count == 4
    assert result.ignored_non_approved_count >= 1
    for item in result.plans:
        assert item.readiness_status == ExecutionReadinessStatus.BLOCKED.value
        assert item.dry_run_only is True
        assert item.no_execution is True
        assert item.executed is False
        assert item.execution_attempted is False
        assert item.outbound_attempted is False
        assert item.owner_approval_required is True
        assert item.owner_approved is False
        codes = {blocker["code"] for blocker in item.blockers}
        assert "execution_disabled_in_this_phase" in codes
        assert "owner_approval_required" in codes
        assert "operator_halt_active" in codes
        assert item.required_owner_approvals


def test_non_approved_artifacts_are_ignored(db_session: Session) -> None:
    _seed_pipeline(db_session)
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    draft = db_session.scalars(select(PersonalizationDraft)).first()
    enrollment = db_session.scalars(
        select(CampaignEnrollment).where(
            CampaignEnrollment.status == EnrollmentStatus.PLANNED.value
        )
    ).first()
    assert draft is not None
    assert enrollment is not None
    _approve(db_session, ReviewArtifactType.PERSONALIZATION_DRAFT.value, draft.id)
    ReviewQueueService().record_decision(
        db_session,
        artifact_type=ReviewArtifactType.OUTREACH_ENROLLMENT_PLAN.value,
        artifact_id=enrollment.id,
        decision=ReviewDecisionStatus.REJECTED.value,
        reviewer="ops",
    )

    result = ExecutionPlanningService().generate(db_session, _settings())

    assert result.plan_count == 1
    assert result.plans[0].source_artifact_id == draft.id
    assert enrollment.id not in {item.source_artifact_id for item in result.plans}
    assert result.ignored_non_approved_count >= 1


def test_generation_is_idempotent(db_session: Session) -> None:
    _seed_pipeline(db_session)
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    draft = db_session.scalars(select(PersonalizationDraft)).first()
    assert draft is not None
    _approve(db_session, ReviewArtifactType.PERSONALIZATION_DRAFT.value, draft.id)
    service = ExecutionPlanningService()

    first = service.generate(db_session, _settings())
    second = service.generate(db_session, _settings())

    assert second.execution_plan_run_id == first.execution_plan_run_id
    assert second.reused_existing is True
    assert db_session.scalar(select(func.count()).select_from(ExecutionPlanRun)) == 1
    assert db_session.scalar(select(func.count()).select_from(ExecutionPlan)) == 1
    activities = db_session.scalars(
        select(Activity).where(Activity.action == "execution_plans_generated")
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
    before_meetings = db_session.scalar(select(func.count()).select_from(Meeting))
    before_messages = db_session.scalar(select(func.count()).select_from(OutreachMessage))
    before_enrollments = db_session.scalar(select(func.count()).select_from(CampaignEnrollment))
    before_stage = db_session.scalar(select(Lead.stage))

    result = ExecutionPlanningService().generate(db_session, _settings())
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


def test_unknown_artifact_type_is_rejected(db_session: Session) -> None:
    with pytest.raises(ExecutionPlanningError) as exc:
        ExecutionPlanningService().generate(
            db_session,
            _settings(),
            filters=ExecutionPlanFilters(artifact_type="not_a_real_type"),
        )
    assert exc.value.code == "unknown_artifact_type"


def test_latest_is_empty_before_generation(db_session: Session) -> None:
    assert ExecutionPlanningService().latest(db_session) is None
