"""Read-only operator command center summary.

Phase 19 aggregates existing safe pipeline artifacts for an internal dashboard.
It never sends email, enrolls campaigns, generates sendable replies, books
meetings, creates video-meet links, places calls, publishes content, launches
ads, spends money, deploys, applies optimizer recommendations, or changes
live/scoring/campaign/provider/deployment settings.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from vyro_growth.config import Settings
from vyro_growth.domain import (
    FindingCode,
    FindingSeverity,
    NextActionCode,
    ReviewDecisionStatus,
    ReviewItemStatus,
)
from vyro_growth.models import (
    ChannelPlan,
    ContentBrief,
    ExecutionPlan,
    OptimizerRecommendation,
    OwnerApprovalPacket,
)
from vyro_growth.observability import sanitize_operator_text
from vyro_growth.services.dashboard import DashboardAnalyticsService, DashboardSummary
from vyro_growth.services.monitoring import (
    LatestJobStatus,
    MonitoringReadiness,
    MonitoringSafety,
    OperationalFinding,
    OperatorMonitoringService,
    SanitizedFailure,
)
from vyro_growth.services.review_queue import ReviewQueueService

logger = structlog.get_logger(__name__)

_SEVERITY_RANK = {
    FindingSeverity.INFO: 0,
    FindingSeverity.WARNING: 1,
    FindingSeverity.BLOCKED: 2,
}

_NEXT_ACTION_LABELS: dict[NextActionCode, str] = {
    NextActionCode.DISABLE_OUTBOUND: (
        "Keep outbound disabled. Do not execute live pipeline actions."
    ),
    NextActionCode.DISABLE_LIVE_PROVIDERS: (
        "Disable live-provider flags before any owner review of live actions."
    ),
    NextActionCode.INVESTIGATE_LIVE_ARTIFACTS: (
        "Investigate stored live calendar, video-meet, send, or call artifacts."
    ),
    NextActionCode.RECORD_OPERATOR_HALT: (
        "Record the persistent operator halt before any rollout."
    ),
    NextActionCode.REVIEW_FAILED_RUNS: (
        "Review sanitized failed runs in operator monitoring."
    ),
    NextActionCode.CHECK_RUNTIME_CONFIG: "Run vyro-growth check-config.",
    NextActionCode.REVIEW_PENDING_ARTIFACTS: (
        "Review pending dry-run artifacts in the operator review queue."
    ),
    NextActionCode.PLAN_APPROVED_EXECUTION: (
        "Generate dry-run execution plans for approved review items."
    ),
    NextActionCode.GENERATE_APPROVAL_PACKETS: (
        "Generate live-readiness owner approval packets (no execution)."
    ),
    NextActionCode.OWNER_REVIEW_APPROVAL_PACKETS: (
        "Owner-review live-readiness packets. Do not execute underlying actions."
    ),
    NextActionCode.INSPECT_ACTION_READINESS: (
        "Inspect the approved action readiness queue. Read-only; do not execute."
    ),
    NextActionCode.RUN_DISCOVERY_WHEN_READY: (
        "Run bounded practice discovery when ready (no outbound)."
    ),
    NextActionCode.KEEP_OUTBOUND_DISABLED: "Keep OUTBOUND_ENABLED=false.",
    NextActionCode.KEEP_LIVE_PROVIDERS_DISABLED: "Keep every live-provider flag disabled.",
    NextActionCode.KEEP_OPERATOR_HALT: (
        "Keep operator halt active until a separate explicit owner action."
    ),
    NextActionCode.RESTORE_CI_SMOKE_GATE: (
        "Restore the documented CI smoke-dry-run job and check-smoke-output gate."
    ),
    NextActionCode.CONFIGURE_REQUIRED_CREDENTIALS: (
        "Configure the named required credential in local env. Do not paste values here."
    ),
    NextActionCode.REVIEW_SETTINGS_CHANGE_REQUESTS: (
        "Review pending live settings change requests at "
        "/internal/operator-settings-change-requests. "
        "Inspect remaining execution blockers at "
        "/internal/operator-settings-execution-preflight. "
        "Recording a decision does not apply them."
    ),
    NextActionCode.INSPECT_SETTINGS_EXECUTION_PREFLIGHT: (
        "Inspect remaining settings-execution blockers at "
        "/internal/operator-settings-execution-preflight. "
        "Read-only dry-run view; do not execute."
    ),
    NextActionCode.INSPECT_OPERATOR_AUDIT_TIMELINE: (
        "Inspect the operator activity audit timeline at "
        "/internal/operator-audit-timeline. Read-only; do not execute."
    ),
    NextActionCode.HANDOFF_IS_NOT_GO_LIVE: (
        "Inspect the owner go-live handoff packet at "
        "/internal/operator-owner-handoff-packet. "
        "Read-only manual-review view; it is not permission or machinery "
        "for going live."
    ),
    NextActionCode.BINDER_IS_NOT_GO_LIVE: (
        "Inspect the compliance evidence binder at "
        "/internal/operator-compliance-evidence-binder. "
        "Read-only owner-review view; it is not permission or machinery "
        "for going live."
    ),
    NextActionCode.RUNBOOK_IS_NOT_DEPLOYMENT: (
        "Inspect the release-candidate deployment runbook at "
        "/internal/operator-release-candidate-runbook. "
        "Read-only owner-review view; it is not a deployment mechanism or "
        "permission to go live."
    ),
    NextActionCode.MANIFEST_IS_NOT_BUILD_OR_DEPLOY: (
        "Inspect the release artifact manifest at "
        "/internal/operator-release-artifact-manifest. "
        "Read-only owner-review view; it is not a build, artifact "
        "publishing, or deployment mechanism."
    ),
    NextActionCode.GO_LIVE_READINESS_INDEX_IS_NOT_PERMISSION: (
        "Inspect the go-live readiness index at "
        "/internal/operator-go-live-readiness-index. "
        "Read-only owner-review view; it is not permission to go live "
        "and is not an execution surface."
    ),
    NextActionCode.LAUNCH_BLOCKERS_PLAN_IS_NOT_PERMISSION: (
        "Inspect the launch blockers remediation plan at "
        "/internal/operator-launch-blockers-plan or "
        "/internal/launch-blockers-plan or via `vyro-growth "
        "launch-blockers-plan`. Read-only planning view; it is not "
        "permission to go live and is not an execution surface."
    ),
}


@dataclass(frozen=True)
class PipelineCounts:
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


@dataclass(frozen=True)
class FindingCounts:
    blocked: int
    warning: int
    info: int
    total: int


@dataclass(frozen=True)
class OutstandingReviewSummary:
    pending_count: int
    decided_count: int
    approved_count: int
    rejected_count: int
    needs_changes_count: int
    by_artifact_type: dict[str, int]
    executed_count: int


@dataclass(frozen=True)
class ApprovalPacketSummary:
    packets: int
    by_preflight_status: dict[str, int]
    by_plan_family: dict[str, int]
    owner_approved: int
    executed: int
    latest_run_status: str
    latest_run_id: UUID | None


@dataclass(frozen=True)
class NextAction:
    code: str
    label: str
    severity: str
    phase: str | None = None


@dataclass(frozen=True)
class CommandCenterSummary:
    generated_at: datetime
    read_only: bool
    overall_severity: FindingSeverity
    safety: MonitoringSafety
    readiness: MonitoringReadiness
    pipeline: PipelineCounts
    latest_runs: tuple[LatestJobStatus, ...]
    recent_failures: tuple[SanitizedFailure, ...]
    finding_counts: FindingCounts
    findings: tuple[OperationalFinding, ...]
    outstanding_review: OutstandingReviewSummary
    approval_packets: ApprovalPacketSummary
    next_actions: tuple[NextAction, ...]
    executed_count: int
    outbound_attempted: bool
    live_call_attempted: bool
    recommendation_applied: bool
    spend_attempted: bool
    campaign_launched: bool
    pages_published: bool
    ads_launched: bool


class OperatorCommandCenterService:
    """Read-only cross-pipeline summary. Does not write rows or call live providers."""

    def __init__(
        self,
        *,
        dashboard: DashboardAnalyticsService | None = None,
        monitoring: OperatorMonitoringService | None = None,
        review_queue: ReviewQueueService | None = None,
    ) -> None:
        self.dashboard = dashboard or DashboardAnalyticsService()
        self.monitoring = monitoring or OperatorMonitoringService(dashboard=self.dashboard)
        self.review_queue = review_queue or ReviewQueueService()

    def summarize(self, db: Session, settings: Settings) -> CommandCenterSummary:
        snapshot = self.monitoring.snapshot(db, settings)
        dashboard = self.dashboard.summarize(db, settings)
        queue = self.review_queue.list_queue(db, settings, include_decided=True)
        pipeline = _pipeline_counts(db, dashboard)
        outstanding = _outstanding_review(queue.pending_count, queue.decided_count, queue.items)
        packets = _approval_packet_summary(snapshot.latest_runs, db)
        findings = snapshot.findings
        next_actions = _next_actions(
            findings=findings,
            safety=snapshot.safety,
            pipeline=pipeline,
            outstanding=outstanding,
            packets=packets,
        )
        summary = CommandCenterSummary(
            generated_at=datetime.now(tz=UTC),
            read_only=True,
            overall_severity=snapshot.overall_severity,
            safety=snapshot.safety,
            readiness=snapshot.readiness,
            pipeline=pipeline,
            latest_runs=snapshot.latest_runs,
            recent_failures=snapshot.recent_failures,
            finding_counts=_finding_counts(findings),
            findings=findings,
            outstanding_review=outstanding,
            approval_packets=packets,
            next_actions=next_actions,
            executed_count=0,
            outbound_attempted=False,
            live_call_attempted=False,
            recommendation_applied=False,
            spend_attempted=False,
            campaign_launched=False,
            pages_published=False,
            ads_launched=False,
        )
        logger.info(
            "operator_command_center_built",
            read_only=True,
            overall_severity=summary.overall_severity.value,
            pending_review=outstanding.pending_count,
            approval_packets=packets.packets,
            outbound_enabled=snapshot.safety.outbound_enabled,
            operator_halt_status=snapshot.safety.operator_halt_status,
        )
        return summary


def _pipeline_counts(db: Session, dashboard: DashboardSummary) -> PipelineCounts:
    return PipelineCounts(
        organizations=dashboard.discovery.organizations,
        leads=dashboard.discovery.leads,
        discovery_runs=dashboard.discovery.discovery_runs,
        website_enrichment_runs=dashboard.website_enrichment.enrichment_runs,
        decision_maker_contacts=dashboard.decision_maker_enrichment.contacts,
        latest_scores=dashboard.scoring.latest_scores,
        personalization_drafts=dashboard.personalization.drafts,
        outreach_plans_planned=dashboard.outreach_plans.planned_count,
        reply_classifications=dashboard.reply_classifications.classifications,
        booking_plans=dashboard.booking_plans.plans,
        voice_qualification_plans=dashboard.voice_qualification_plans.plans,
        optimizer_recommendations=_count_rows(db, OptimizerRecommendation),
        channel_plans=_count_rows(db, ChannelPlan),
        content_briefs=_count_rows(db, ContentBrief),
        execution_plans=_count_rows(db, ExecutionPlan),
        approval_packets=_count_rows(db, OwnerApprovalPacket),
    )


def _outstanding_review(
    pending_count: int,
    decided_count: int,
    items: tuple[Any, ...],
) -> OutstandingReviewSummary:
    pending_status = ReviewItemStatus.PENDING_OPERATOR_REVIEW.value
    by_type: dict[str, int] = {}
    approved = 0
    rejected = 0
    needs_changes = 0
    for item in items:
        if item.status == pending_status:
            by_type[item.artifact_type] = by_type.get(item.artifact_type, 0) + 1
            continue
        decision = item.decision.decision if item.decision is not None else None
        if decision == ReviewDecisionStatus.APPROVED.value:
            approved += 1
        elif decision == ReviewDecisionStatus.REJECTED.value:
            rejected += 1
        elif decision == ReviewDecisionStatus.NEEDS_CHANGES.value:
            needs_changes += 1
    return OutstandingReviewSummary(
        pending_count=pending_count,
        decided_count=decided_count,
        approved_count=approved,
        rejected_count=rejected,
        needs_changes_count=needs_changes,
        by_artifact_type=by_type,
        executed_count=0,
    )


def _approval_packet_summary(
    latest_runs: tuple[LatestJobStatus, ...], packet_db: Session
) -> ApprovalPacketSummary:
    latest = next((run for run in latest_runs if run.phase == "approval_packets"), None)
    status = latest.status if latest is not None and latest.status is not None else "not_started"
    return ApprovalPacketSummary(
        packets=_count_rows(packet_db, OwnerApprovalPacket),
        by_preflight_status=_counts_by(packet_db, OwnerApprovalPacket.preflight_status),
        by_plan_family=_counts_by(packet_db, OwnerApprovalPacket.plan_family),
        owner_approved=_count_rows(
            packet_db, OwnerApprovalPacket, OwnerApprovalPacket.owner_approved.is_(True)
        ),
        executed=_count_rows(
            packet_db, OwnerApprovalPacket, OwnerApprovalPacket.executed.is_(True)
        ),
        latest_run_status=status,
        latest_run_id=latest.run_id if latest is not None else None,
    )


def _finding_counts(findings: tuple[OperationalFinding, ...]) -> FindingCounts:
    blocked = sum(1 for item in findings if item.severity is FindingSeverity.BLOCKED)
    warning = sum(1 for item in findings if item.severity is FindingSeverity.WARNING)
    info = sum(1 for item in findings if item.severity is FindingSeverity.INFO)
    return FindingCounts(
        blocked=blocked,
        warning=warning,
        info=info,
        total=len(findings),
    )


def _next_actions(
    *,
    findings: tuple[OperationalFinding, ...],
    safety: MonitoringSafety,
    pipeline: PipelineCounts,
    outstanding: OutstandingReviewSummary,
    packets: ApprovalPacketSummary,
) -> tuple[NextAction, ...]:
    selected: dict[NextActionCode, NextAction] = {}

    def add(
        code: NextActionCode,
        severity: FindingSeverity,
        *,
        phase: str | None = None,
        label: str | None = None,
    ) -> None:
        current = selected.get(code)
        if current is not None and _SEVERITY_RANK[FindingSeverity(current.severity)] >= (
            _SEVERITY_RANK[severity]
        ):
            return
        text = sanitize_operator_text(label or _NEXT_ACTION_LABELS[code]) or _NEXT_ACTION_LABELS[
            code
        ]
        selected[code] = NextAction(
            code=code.value,
            label=text,
            severity=severity.value,
            phase=phase,
        )

    for finding in findings:
        match finding.code:
            case FindingCode.OUTBOUND_ENABLED:
                add(NextActionCode.DISABLE_OUTBOUND, FindingSeverity.BLOCKED)
            case FindingCode.LIVE_PROVIDER_ENABLED:
                add(NextActionCode.DISABLE_LIVE_PROVIDERS, FindingSeverity.BLOCKED)
            case FindingCode.LIVE_OUTBOUND_ARTIFACT:
                add(NextActionCode.INVESTIGATE_LIVE_ARTIFACTS, FindingSeverity.BLOCKED)
            case FindingCode.CONFIG_NOT_READY:
                add(NextActionCode.CHECK_RUNTIME_CONFIG, FindingSeverity.WARNING)
            case FindingCode.OPERATOR_HALT_UNAVAILABLE:
                add(NextActionCode.RECORD_OPERATOR_HALT, FindingSeverity.WARNING)
            case FindingCode.RECENT_FAILURES:
                add(NextActionCode.REVIEW_FAILED_RUNS, FindingSeverity.WARNING)
            case FindingCode.PENDING_OPERATOR_REVIEW:
                add(
                    NextActionCode.REVIEW_PENDING_ARTIFACTS,
                    FindingSeverity.INFO,
                    label=(
                        f"Review {outstanding.pending_count} pending dry-run artifact(s) "
                        "in the operator review queue."
                    ),
                )
            case FindingCode.EXECUTION_PLANS_DRY_RUN:
                if packets.packets == 0:
                    add(
                        NextActionCode.GENERATE_APPROVAL_PACKETS,
                        FindingSeverity.INFO,
                        phase="approval_packets",
                    )
                else:
                    add(
                        NextActionCode.OWNER_REVIEW_APPROVAL_PACKETS,
                        FindingSeverity.INFO,
                        phase="approval_packets",
                    )
            case FindingCode.APPROVAL_PACKETS_DRY_RUN:
                add(
                    NextActionCode.OWNER_REVIEW_APPROVAL_PACKETS,
                    FindingSeverity.INFO,
                    phase="approval_packets",
                )
                add(
                    NextActionCode.INSPECT_ACTION_READINESS,
                    FindingSeverity.INFO,
                    phase="action_readiness",
                )
            case _:
                pass

    if outstanding.pending_count and NextActionCode.REVIEW_PENDING_ARTIFACTS not in selected:
        add(
            NextActionCode.REVIEW_PENDING_ARTIFACTS,
            FindingSeverity.INFO,
            label=(
                f"Review {outstanding.pending_count} pending dry-run artifact(s) "
                "in the operator review queue."
            ),
        )
    if outstanding.approved_count and pipeline.execution_plans == 0:
        add(
            NextActionCode.PLAN_APPROVED_EXECUTION,
            FindingSeverity.INFO,
            phase="execution_plans",
        )
    if pipeline.execution_plans and packets.packets == 0:
        add(
            NextActionCode.GENERATE_APPROVAL_PACKETS,
            FindingSeverity.INFO,
            phase="approval_packets",
        )
    if packets.packets and NextActionCode.INSPECT_ACTION_READINESS not in selected:
        add(
            NextActionCode.INSPECT_ACTION_READINESS,
            FindingSeverity.INFO,
            phase="action_readiness",
        )
    if pipeline.organizations == 0:
        add(NextActionCode.RUN_DISCOVERY_WHEN_READY, FindingSeverity.INFO, phase="discovery")
    if not safety.outbound_enabled:
        add(NextActionCode.KEEP_OUTBOUND_DISABLED, FindingSeverity.INFO)
    add(
        NextActionCode.INSPECT_SETTINGS_EXECUTION_PREFLIGHT,
        FindingSeverity.INFO,
        phase="settings_execution_preflight",
    )
    add(
        NextActionCode.INSPECT_OPERATOR_AUDIT_TIMELINE,
        FindingSeverity.INFO,
        phase="operator_audit_timeline",
    )
    add(
        NextActionCode.HANDOFF_IS_NOT_GO_LIVE,
        FindingSeverity.INFO,
        phase="owner_handoff",
    )
    add(
        NextActionCode.RUNBOOK_IS_NOT_DEPLOYMENT,
        FindingSeverity.INFO,
        phase="release_candidate_runbook",
    )
    add(
        NextActionCode.MANIFEST_IS_NOT_BUILD_OR_DEPLOY,
        FindingSeverity.INFO,
        phase="release_artifact_manifest",
    )
    add(
        NextActionCode.GO_LIVE_READINESS_INDEX_IS_NOT_PERMISSION,
        FindingSeverity.INFO,
        phase="go_live_readiness_index",
    )
    add(
        NextActionCode.LAUNCH_BLOCKERS_PLAN_IS_NOT_PERMISSION,
        FindingSeverity.INFO,
        phase="launch_blockers_plan",
    )

    return tuple(
        sorted(
            selected.values(),
            key=lambda item: (-_SEVERITY_RANK[FindingSeverity(item.severity)], item.code),
        )
    )


def _count_rows(db: Session, model: type[Any], *clauses: Any) -> int:
    stmt = select(func.count()).select_from(model)
    if clauses:
        stmt = stmt.where(*clauses)
    return int(db.scalar(stmt) or 0)


def _counts_by(db: Session, column: Any) -> dict[str, int]:
    rows = db.execute(select(column, func.count()).group_by(column)).all()
    result: dict[str, int] = {}
    for key, count in rows:
        label = "unset" if key is None or key == "" else str(key)
        result[label] = int(count)
    return result
