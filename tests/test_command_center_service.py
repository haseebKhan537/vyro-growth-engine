from __future__ import annotations

import json
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tests.test_approval_packet_service import _approve_all_families
from tests.test_dashboard_service import PHI_SNIPPET, PROSPECT_EMAIL, _seed_pipeline
from tests.test_monitoring_service import UNSAFE_ERROR, _seed_optimizer_recommendation
from vyro_growth.config import Settings
from vyro_growth.domain import (
    DiscoveryRunStatus,
    FindingCode,
    FindingSeverity,
    NextActionCode,
    PreflightStatus,
    ReviewArtifactType,
)
from vyro_growth.models import (
    Activity,
    CampaignEnrollment,
    DiscoveryRun,
    ExecutionPlan,
    Meeting,
    OutreachMessage,
    OwnerApprovalPacket,
)
from vyro_growth.services.approval_packets import ApprovalPacketService
from vyro_growth.services.command_center import OperatorCommandCenterService
from vyro_growth.services.execution_planning import ExecutionPlanningService
from vyro_growth.services.operator_halt import HaltStatus, read_operator_halt, set_operator_halt


def _settings(**overrides: object) -> Settings:
    return Settings(**overrides)


def _payload(summary: object) -> str:
    return json.dumps(summary, default=str)


def _pipeline_counts(db: Session) -> dict[str, int]:
    return {
        "activities": int(db.scalar(select(func.count()).select_from(Activity)) or 0),
        "meetings": int(db.scalar(select(func.count()).select_from(Meeting)) or 0),
        "enrollments": int(db.scalar(select(func.count()).select_from(CampaignEnrollment)) or 0),
        "messages": int(db.scalar(select(func.count()).select_from(OutreachMessage)) or 0),
        "execution_plans": int(db.scalar(select(func.count()).select_from(ExecutionPlan)) or 0),
        "approval_packets": int(
            db.scalar(select(func.count()).select_from(OwnerApprovalPacket)) or 0
        ),
    }


def test_empty_command_center_is_zeroed_and_safe(db_session: Session) -> None:
    summary = OperatorCommandCenterService().summarize(db_session, _settings())

    assert summary.read_only is True
    assert summary.overall_severity is FindingSeverity.WARNING
    assert summary.pipeline.organizations == 0
    assert summary.pipeline.leads == 0
    assert summary.pipeline.personalization_drafts == 0
    assert summary.pipeline.execution_plans == 0
    assert summary.pipeline.approval_packets == 0
    assert summary.outstanding_review.pending_count == 0
    assert summary.outstanding_review.decided_count == 0
    assert summary.outstanding_review.executed_count == 0
    assert summary.approval_packets.packets == 0
    assert summary.approval_packets.latest_run_status == "not_started"
    assert summary.approval_packets.executed == 0
    assert summary.safety.outbound_enabled is False
    assert summary.safety.operator_halt_status == HaltStatus.UNAVAILABLE.value
    assert summary.safety.phi_fields_present is False
    assert summary.executed_count == 0
    assert summary.outbound_attempted is False
    assert summary.recommendation_applied is False
    assert summary.spend_attempted is False
    assert summary.campaign_launched is False
    assert summary.pages_published is False
    assert summary.ads_launched is False
    assert {run.phase for run in summary.latest_runs} >= {
        "discovery",
        "growth_optimizer",
        "execution_plans",
        "approval_packets",
    }
    assert all(run.status == "not_started" for run in summary.latest_runs)
    codes = {item.code for item in summary.next_actions}
    assert NextActionCode.RECORD_OPERATOR_HALT.value in codes
    assert NextActionCode.KEEP_OUTBOUND_DISABLED.value in codes
    assert NextActionCode.INSPECT_SETTINGS_EXECUTION_PREFLIGHT.value in codes
    assert NextActionCode.INSPECT_OPERATOR_AUDIT_TIMELINE.value in codes
    assert NextActionCode.HANDOFF_IS_NOT_GO_LIVE.value in codes
    assert NextActionCode.RUNBOOK_IS_NOT_DEPLOYMENT.value in codes
    assert NextActionCode.MANIFEST_IS_NOT_BUILD_OR_DEPLOY.value in codes
    assert NextActionCode.RUN_DISCOVERY_WHEN_READY.value in codes
    assert summary.finding_counts.warning >= 1
    assert summary.finding_counts.blocked == 0


def test_populated_command_center_counts_and_next_actions(db_session: Session) -> None:
    _seed_pipeline(db_session)
    _seed_optimizer_recommendation(db_session)
    set_operator_halt(db_session, halted=True, reason="incident")

    summary = OperatorCommandCenterService().summarize(db_session, _settings())

    assert summary.pipeline.organizations == 1
    assert summary.pipeline.leads == 1
    assert summary.pipeline.personalization_drafts == 1
    assert summary.pipeline.outreach_plans_planned == 1
    assert summary.pipeline.reply_classifications == 1
    assert summary.pipeline.booking_plans == 1
    assert summary.pipeline.voice_qualification_plans == 1
    assert summary.pipeline.optimizer_recommendations == 1
    assert summary.outstanding_review.pending_count == 6
    assert summary.outstanding_review.approved_count == 0
    assert summary.outstanding_review.by_artifact_type[
        ReviewArtifactType.PERSONALIZATION_DRAFT.value
    ] == 1
    assert summary.safety.operator_halt_status == HaltStatus.HALTED.value
    assert summary.readiness.ready_for_manual_rollout is True
    assert any(
        run.phase == "discovery" and run.status != "not_started" for run in summary.latest_runs
    )
    codes = {item.code for item in summary.next_actions}
    assert NextActionCode.REVIEW_PENDING_ARTIFACTS.value in codes
    assert NextActionCode.KEEP_OUTBOUND_DISABLED.value in codes
    assert NextActionCode.RUN_DISCOVERY_WHEN_READY.value not in codes
    finding_codes = {item.code for item in summary.findings}
    assert FindingCode.PENDING_OPERATOR_REVIEW in finding_codes
    assert FindingCode.OPERATOR_HALT_ACTIVE in finding_codes
    assert summary.finding_counts.info >= 1


def test_command_center_summarizes_approval_packets_without_executing(
    db_session: Session,
) -> None:
    _approve_all_families(db_session)
    ExecutionPlanningService().generate(db_session, _settings())
    ApprovalPacketService().generate(db_session, _settings())
    before = _pipeline_counts(db_session)

    summary = OperatorCommandCenterService().summarize(db_session, _settings())

    assert summary.pipeline.execution_plans == 8
    assert summary.pipeline.approval_packets == 8
    assert summary.outstanding_review.pending_count == 0
    assert summary.outstanding_review.approved_count == 8
    assert summary.approval_packets.packets == 8
    assert summary.approval_packets.latest_run_status != "not_started"
    assert summary.approval_packets.by_preflight_status[PreflightStatus.BLOCKED.value] == 8
    assert summary.approval_packets.owner_approved == 0
    assert summary.approval_packets.executed == 0
    codes = {item.code for item in summary.next_actions}
    assert NextActionCode.OWNER_REVIEW_APPROVAL_PACKETS.value in codes
    assert NextActionCode.INSPECT_ACTION_READINESS.value in codes
    assert NextActionCode.KEEP_OUTBOUND_DISABLED.value in codes
    assert summary.executed_count == 0
    assert summary.outbound_attempted is False
    assert _pipeline_counts(db_session) == before
    assert read_operator_halt(db_session) is HaltStatus.HALTED


def test_command_center_is_read_only_and_preserves_halt(db_session: Session) -> None:
    _seed_pipeline(db_session)
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    before = _pipeline_counts(db_session)

    OperatorCommandCenterService().summarize(db_session, Settings(outbound_enabled=False))

    assert _pipeline_counts(db_session) == before
    assert read_operator_halt(db_session) is HaltStatus.HALTED


def test_command_center_redacts_phi_secrets_and_prospect_fields(db_session: Session) -> None:
    _seed_pipeline(db_session)
    now = datetime.now(tz=UTC)
    db_session.add(
        DiscoveryRun(
            source="nppes",
            status=DiscoveryRunStatus.FAILED.value,
            query_params={"state": "TX", "city": "Austin"},
            error_message=UNSAFE_ERROR,
            started_at=now,
            finished_at=now,
        )
    )
    db_session.flush()
    set_operator_halt(db_session, halted=True, reason=f"halt {PROSPECT_EMAIL} {PHI_SNIPPET}")

    summary = OperatorCommandCenterService().summarize(db_session, _settings())
    payload = _payload(summary.__dict__)

    assert PHI_SNIPPET not in payload
    assert PROSPECT_EMAIL not in payload
    assert "diabetes" not in payload.lower()
    assert "sk-testsecret12345" not in payload
    assert "5551112222" not in payload
    assert "practice_summary" not in payload
    assert "opening_line" not in payload
    assert "evidence_snippet" not in payload
    assert summary.recent_failures
    assert all(
        item.error_message is None or "sk-testsecret12345" not in item.error_message
        for item in summary.recent_failures
    )
    assert all("@" not in action.label for action in summary.next_actions)


def test_outbound_enabled_adds_blocked_next_action(db_session: Session) -> None:
    set_operator_halt(db_session, halted=True, reason="keep-halted")

    summary = OperatorCommandCenterService().summarize(
        db_session, Settings(outbound_enabled=True)
    )

    assert summary.overall_severity is FindingSeverity.BLOCKED
    codes = {item.code for item in summary.next_actions}
    assert NextActionCode.DISABLE_OUTBOUND.value in codes
    assert summary.finding_counts.blocked >= 1
    assert summary.outbound_attempted is False
    assert read_operator_halt(db_session) is HaltStatus.HALTED
