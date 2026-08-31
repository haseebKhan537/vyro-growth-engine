from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from vyro_growth.api.monitoring import (
    LatestJobStatusResponse,
    MonitoringReadinessResponse,
    MonitoringSafetyResponse,
    OperationalFindingResponse,
    SanitizedFailureResponse,
    _failure_to_response,
    _finding_to_response,
    _job_status_to_response,
    _readiness_to_response,
    _safety_to_response,
)
from vyro_growth.config import Settings
from vyro_growth.services.command_center import (
    ApprovalPacketSummary,
    CommandCenterSummary,
    FindingCounts,
    NextAction,
    OperatorCommandCenterService,
    OutstandingReviewSummary,
    PipelineCounts,
)


class PipelineCountsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    organizations: int
    leads: int
    discovery_runs: int
    website_enrichment_runs: int
    decision_maker_contacts: int
    latest_scores: int
    personalization_drafts: int
    outreach_plans_planned: int
    reply_classifications: int
    booking_plans: int
    voice_qualification_plans: int
    optimizer_recommendations: int
    channel_plans: int
    content_briefs: int
    execution_plans: int
    approval_packets: int


class FindingCountsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    blocked: int
    warning: int
    info: int
    total: int


class OutstandingReviewResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pending_count: int
    decided_count: int
    approved_count: int
    rejected_count: int
    needs_changes_count: int
    by_artifact_type: dict[str, int] = Field(default_factory=dict)
    executed_count: int = 0


class ApprovalPacketSummaryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    packets: int
    by_preflight_status: dict[str, int] = Field(default_factory=dict)
    by_plan_family: dict[str, int] = Field(default_factory=dict)
    owner_approved: int = 0
    executed: int = 0
    latest_run_status: str
    latest_run_id: UUID | None = None


class NextActionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    label: str
    severity: str
    phase: str | None = None


class CommandCenterResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    generated_at: datetime
    read_only: bool = True
    overall_severity: str
    safety: MonitoringSafetyResponse
    readiness: MonitoringReadinessResponse
    pipeline: PipelineCountsResponse
    latest_runs: list[LatestJobStatusResponse]
    recent_failures: list[SanitizedFailureResponse]
    finding_counts: FindingCountsResponse
    findings: list[OperationalFindingResponse]
    outstanding_review: OutstandingReviewResponse
    approval_packets: ApprovalPacketSummaryResponse
    next_actions: list[NextActionResponse]
    executed_count: int = 0
    outbound_attempted: bool = False
    live_call_attempted: bool = False
    recommendation_applied: bool = False
    spend_attempted: bool = False
    campaign_launched: bool = False
    pages_published: bool = False
    ads_launched: bool = False


def _pipeline_to_response(item: PipelineCounts) -> PipelineCountsResponse:
    return PipelineCountsResponse(
        organizations=item.organizations,
        leads=item.leads,
        discovery_runs=item.discovery_runs,
        website_enrichment_runs=item.website_enrichment_runs,
        decision_maker_contacts=item.decision_maker_contacts,
        latest_scores=item.latest_scores,
        personalization_drafts=item.personalization_drafts,
        outreach_plans_planned=item.outreach_plans_planned,
        reply_classifications=item.reply_classifications,
        booking_plans=item.booking_plans,
        voice_qualification_plans=item.voice_qualification_plans,
        optimizer_recommendations=item.optimizer_recommendations,
        channel_plans=item.channel_plans,
        content_briefs=item.content_briefs,
        execution_plans=item.execution_plans,
        approval_packets=item.approval_packets,
    )


def _finding_counts_to_response(item: FindingCounts) -> FindingCountsResponse:
    return FindingCountsResponse(
        blocked=item.blocked,
        warning=item.warning,
        info=item.info,
        total=item.total,
    )


def _outstanding_to_response(item: OutstandingReviewSummary) -> OutstandingReviewResponse:
    return OutstandingReviewResponse(
        pending_count=item.pending_count,
        decided_count=item.decided_count,
        approved_count=item.approved_count,
        rejected_count=item.rejected_count,
        needs_changes_count=item.needs_changes_count,
        by_artifact_type=item.by_artifact_type,
        executed_count=0,
    )


def _packets_to_response(item: ApprovalPacketSummary) -> ApprovalPacketSummaryResponse:
    return ApprovalPacketSummaryResponse(
        packets=item.packets,
        by_preflight_status=item.by_preflight_status,
        by_plan_family=item.by_plan_family,
        owner_approved=item.owner_approved,
        executed=0,  # Phase 19 never reports execution even if a stored row is marked.
        latest_run_status=item.latest_run_status,
        latest_run_id=item.latest_run_id,
    )


def _next_action_to_response(item: NextAction) -> NextActionResponse:
    return NextActionResponse(
        code=item.code,
        label=item.label,
        severity=item.severity,
        phase=item.phase,
    )


def command_center_to_response(summary: CommandCenterSummary) -> CommandCenterResponse:
    return CommandCenterResponse(
        generated_at=summary.generated_at,
        read_only=True,
        overall_severity=summary.overall_severity.value,
        safety=_safety_to_response(summary.safety),
        readiness=_readiness_to_response(summary.readiness),
        pipeline=_pipeline_to_response(summary.pipeline),
        latest_runs=[_job_status_to_response(item) for item in summary.latest_runs],
        recent_failures=[_failure_to_response(item) for item in summary.recent_failures],
        finding_counts=_finding_counts_to_response(summary.finding_counts),
        findings=[_finding_to_response(item) for item in summary.findings],
        outstanding_review=_outstanding_to_response(summary.outstanding_review),
        approval_packets=_packets_to_response(summary.approval_packets),
        next_actions=[_next_action_to_response(item) for item in summary.next_actions],
        executed_count=0,
        outbound_attempted=False,
        live_call_attempted=False,
        recommendation_applied=False,
        spend_attempted=False,
        campaign_launched=False,
        pages_published=False,
        ads_launched=False,
    )


def build_command_center_response(
    db: Session,
    settings: Settings,
    *,
    service: OperatorCommandCenterService | None = None,
) -> CommandCenterResponse:
    command_center = service or OperatorCommandCenterService()
    return command_center_to_response(command_center.summarize(db, settings))
