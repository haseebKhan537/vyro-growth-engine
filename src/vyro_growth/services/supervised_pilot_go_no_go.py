"""Read-only supervised pilot go/no-go packet export.

Phase 59 combines the supervised pilot plan, candidate readiness, provider
setup, rehearsal outcome, launch readiness / go-live index, review and
action-readiness queues, owner approval / settings-request rollups, and
operator halt state into one sanitized decision-support packet. It reuses
those services as source material and never recalculates readiness. It
never executes, applies settings, lifts halt, enables outbound, calls
providers, scrapes, builds, publishes, deploys, spends, or changes live
state. This packet is not permission to go live and not an execution
surface.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy.orm import Session

from vyro_growth.config import Settings
from vyro_growth.domain import FindingSeverity, NextActionCode
from vyro_growth.observability import sanitize_mapping, sanitize_operator_text
from vyro_growth.services.action_readiness import (
    ActionReadinessFilters,
    ActionReadinessResult,
    ActionReadinessService,
)
from vyro_growth.services.approval_packets import (
    ApprovalPacketRunResult,
    ApprovalPacketService,
)
from vyro_growth.services.operator_halt import HaltStatus, read_operator_halt
from vyro_growth.services.release_artifact_manifest import LocalGitMetadata
from vyro_growth.services.review_queue import ReviewQueueResult, ReviewQueueService
from vyro_growth.services.settings_change_requests import (
    SettingsChangeRequestList,
    SettingsChangeRequestService,
)
from vyro_growth.services.supervised_pilot_candidates import (
    CLI_COMMAND as CANDIDATES_CLI_COMMAND,
)
from vyro_growth.services.supervised_pilot_candidates import (
    HTML_ROUTE as CANDIDATES_HTML_ROUTE,
)
from vyro_growth.services.supervised_pilot_candidates import (
    HTTP_ROUTE as CANDIDATES_HTTP_ROUTE,
)
from vyro_growth.services.supervised_pilot_candidates import (
    SupervisedPilotCandidates,
    SupervisedPilotCandidateService,
)
from vyro_growth.services.supervised_pilot_plan import (
    CLI_COMMAND as PILOT_CLI_COMMAND,
)
from vyro_growth.services.supervised_pilot_plan import (
    HTML_ROUTE as PILOT_HTML_ROUTE,
)
from vyro_growth.services.supervised_pilot_plan import (
    HTTP_ROUTE as PILOT_HTTP_ROUTE,
)
from vyro_growth.services.supervised_pilot_plan import PREREQUISITE_KEYS

logger = structlog.get_logger(__name__)

PACKET_KIND = "supervised_pilot_go_no_go"
PACKET_PURPOSE = "manual_owner_supervised_pilot_go_no_go_review_only"
GO_NO_GO_NOT_GO_LIVE_CODE = NextActionCode.SUPERVISED_PILOT_GO_NO_GO_IS_NOT_GO_LIVE.value
EXECUTION_DISABLED_CODE = "execution_disabled_in_this_phase"
CLI_COMMAND = "supervised-pilot-go-no-go"
HTTP_ROUTE = "/internal/supervised-pilot-go-no-go"
HTML_ROUTE = "/internal/operator-supervised-pilot-go-no-go"
KNOWN_PREREQUISITE_STATUSES: tuple[str, ...] = (
    FindingSeverity.INFO.value,
    "ready_for_owner_review",
    FindingSeverity.WARNING.value,
    FindingSeverity.BLOCKED.value,
)
RELATED_COMMANDS: tuple[str, ...] = (
    "launch-readiness",
    "go-live-readiness-index",
    "launch-blockers-plan",
    "staged-rollout-plan",
    "owner-launch-dossier",
    "provider-setup-checklist",
    "go-live-rehearsal-checklist",
    "rehearsal-outcome-report",
    PILOT_CLI_COMMAND,
    CANDIDATES_CLI_COMMAND,
    "action-readiness",
    "settings-execution-preflight",
    "dashboard-summary",
    "check-config",
    "smoke-dry-run",
    CLI_COMMAND,
    "supervised-pilot-first-send-preflight",
    "supervised-pilot-launch-rehearsal-control-map",
    "supervised-pilot-first-send-owner-authorization-packet",
    "system-status",
)
RELATED_ROUTES: tuple[str, ...] = (
    "/internal/launch-readiness",
    "/internal/operator-go-live-readiness-index",
    "/internal/go-live-readiness-index",
    "/internal/operator-launch-blockers-plan",
    "/internal/launch-blockers-plan",
    "/internal/operator-staged-rollout-plan",
    "/internal/staged-rollout-plan",
    "/internal/operator-owner-launch-dossier",
    "/internal/owner-launch-dossier",
    "/internal/operator-provider-setup-checklist",
    "/internal/provider-setup-checklist",
    "/internal/operator-go-live-rehearsal-checklist",
    "/internal/go-live-rehearsal-checklist",
    "/internal/operator-rehearsal-outcome-report",
    "/internal/rehearsal-outcome-report",
    PILOT_HTML_ROUTE,
    PILOT_HTTP_ROUTE,
    CANDIDATES_HTML_ROUTE,
    CANDIDATES_HTTP_ROUTE,
    "/internal/operator-action-readiness",
    "/internal/action-readiness",
    "/internal/operator-review-queue",
    "/internal/review-queue",
    "/internal/operator-approval-packets",
    "/internal/operator-settings-change-requests",
    HTML_ROUTE,
    HTTP_ROUTE,
    "/internal/operator-supervised-pilot-first-send-preflight",
    "/internal/supervised-pilot-first-send-preflight",
    "/internal/operator-supervised-pilot-launch-rehearsal-control-map",
    "/internal/supervised-pilot-launch-rehearsal-control-map",
    "/internal/supervised-pilot-first-send-owner-authorization-packet",
)
_STATUS_RANK = {
    FindingSeverity.INFO.value: 0,
    "ready_for_owner_review": 1,
    "open": 1,
    "missing": 2,
    "closed": 2,
    FindingSeverity.WARNING.value: 2,
    FindingSeverity.BLOCKED.value: 3,
}


@dataclass(frozen=True)
class GoNoGoCount:
    key: str
    count: int


@dataclass(frozen=True)
class GoNoGoGate:
    code: str
    status: str
    label: str
    blocking: bool
    command_name: str | None
    json_route: str | None
    html_route: str | None


@dataclass(frozen=True)
class GoNoGoNextAction:
    code: str
    status: str
    label: str
    command_name: str | None
    json_route: str | None
    html_route: str | None
    config_name: str | None


@dataclass(frozen=True)
class SupervisedPilotGoNoGo:
    generated_at: datetime
    packet_kind: str
    purpose: str
    overall_status: str
    read_only: bool
    no_execution: bool
    no_go_live: bool
    no_deployment: bool
    no_outbound: bool
    no_provider_calls: bool
    no_spend: bool
    dry_run_only: bool
    executed: int
    execution_attempted: bool
    outbound_attempted: bool
    live_call_attempted: bool
    recommendation_applied: bool
    spend_attempted: bool
    spend_allowed: bool
    campaign_launched: bool
    pages_published: bool
    ads_launched: bool
    owner_approved: bool
    settings_applied: bool
    halt_changed: bool
    live_action: bool
    execution_allowed: bool
    future_execution_phase_exists: bool
    future_deployment_phase_exists: bool
    go_live_permitted: bool
    deployment_allowed: bool
    deployment_attempted: bool
    deployed: bool
    build_allowed: bool
    artifact_publish_allowed: bool
    container_build_attempted: bool
    artifact_publish_attempted: bool
    outbound_enabled: bool
    live_providers_enabled: bool
    manual_review_only: bool
    supervised_pilot_go_no_go_is_not_go_live: bool
    export_is_not_permission_to_go_live: bool
    export_is_not_execution: bool
    supervised_pilot_plan_is_not_go_live: bool
    supervised_pilot_candidates_is_not_go_live: bool
    rehearsal_outcome_report_is_not_go_live: bool
    go_live_rehearsal_checklist_is_not_go_live: bool
    provider_setup_checklist_is_not_go_live: bool
    operator_halt_status: str
    operator_halt_before: str
    operator_halt_after: str
    prerequisite_counts_by_status: tuple[GoNoGoCount, ...]
    missing_prerequisite_codes: tuple[str, ...]
    candidate_counts_by_readiness: tuple[GoNoGoCount, ...]
    blocked_reason_counts: tuple[GoNoGoCount, ...]
    ready_for_review_count: int
    blocked_candidate_count: int
    total_candidate_count: int
    review_queue_pending_count: int
    review_queue_decided_count: int
    review_queue_counts_by_artifact_type: tuple[GoNoGoCount, ...]
    action_readiness_candidate_count: int
    action_readiness_counts_by_status: tuple[GoNoGoCount, ...]
    action_readiness_counts_by_blocker: tuple[GoNoGoCount, ...]
    approval_packet_count: int
    approval_packet_counts_by_preflight: tuple[GoNoGoCount, ...]
    settings_request_count: int
    settings_request_pending_count: int
    settings_request_counts_by_type: tuple[GoNoGoCount, ...]
    settings_request_counts_by_decision: tuple[GoNoGoCount, ...]
    go_no_go_gates: tuple[GoNoGoGate, ...]
    owner_decision_prerequisites: tuple[str, ...]
    remaining_owner_approval_types: tuple[str, ...]
    closed_provider_flag_names: tuple[str, ...]
    missing_credential_names: tuple[str, ...]
    missing_config_names: tuple[str, ...]
    blocker_codes: tuple[str, ...]
    gate_codes: tuple[str, ...]
    cli_command: str
    http_route: str
    source_pilot_plan_command: str
    source_pilot_plan_route: str
    source_pilot_plan_html_route: str
    source_pilot_plan_overall_status: str
    source_candidates_command: str
    source_candidates_route: str
    source_candidates_html_route: str
    source_candidates_overall_status: str
    source_outcome_command: str
    source_outcome_route: str
    source_outcome_overall_status: str
    source_rehearsal_command: str
    source_rehearsal_route: str
    source_rehearsal_overall_status: str
    source_launch_readiness_command: str
    source_launch_readiness_route: str
    source_launch_readiness_overall_status: str
    source_index_command: str
    source_index_route: str
    source_index_overall_status: str
    source_provider_setup_command: str
    source_provider_setup_route: str
    source_provider_setup_overall_status: str
    related_commands: tuple[str, ...]
    related_routes: tuple[str, ...]
    local_git: LocalGitMetadata
    next_actions: tuple[GoNoGoNextAction, ...]


class SupervisedPilotGoNoGoService:
    """Compose a sanitized go/no-go packet from existing review surfaces."""

    def __init__(
        self,
        *,
        candidates: SupervisedPilotCandidateService | None = None,
        action_readiness: ActionReadinessService | None = None,
        review_queue: ReviewQueueService | None = None,
        approval_packets: ApprovalPacketService | None = None,
        settings_requests: SettingsChangeRequestService | None = None,
    ) -> None:
        self.candidates = candidates or SupervisedPilotCandidateService()
        self.action_readiness = action_readiness or ActionReadinessService()
        self.review_queue = review_queue or ReviewQueueService()
        self.approval_packets = approval_packets or ApprovalPacketService()
        self.settings_requests = settings_requests or SettingsChangeRequestService()

    def build(self, db: Session, settings: Settings) -> SupervisedPilotGoNoGo:
        halt_before = read_operator_halt(db)
        candidates = self.candidates.build(db, settings)
        action_queue = self.action_readiness.list_queue(
            db, settings, filters=ActionReadinessFilters()
        )
        review_queue = self.review_queue.list_queue(db, settings, include_decided=True)
        approval_run = self.approval_packets.latest(db)
        settings_list = self.settings_requests.list_requests(db, settings)
        halt_after = read_operator_halt(db)
        if halt_after != halt_before:
            raise RuntimeError("supervised pilot go/no-go must not change operator halt status")
        packet = _from_sources(
            candidates,
            action_queue,
            review_queue,
            approval_run,
            settings_list,
            halt_before=halt_before,
            halt_after=halt_after,
        )
        logger.info(
            "supervised_pilot_go_no_go_built",
            read_only=True,
            no_execution=True,
            no_go_live=True,
            no_outbound=True,
            no_provider_calls=True,
            no_spend=True,
            overall_status=packet.overall_status,
            operator_halt_status=packet.operator_halt_status,
            outbound_enabled=packet.outbound_enabled,
            go_live_permitted=False,
            execution_allowed=False,
            deployment_allowed=False,
            settings_applied=False,
            halt_changed=False,
            owner_approved=False,
            spend_allowed=False,
            executed=0,
            ready_for_review_count=packet.ready_for_review_count,
            blocking_gate_count=sum(1 for item in packet.go_no_go_gates if item.blocking),
            supervised_pilot_go_no_go_is_not_go_live=True,
        )
        return packet


def _from_sources(
    candidates: SupervisedPilotCandidates,
    action_queue: ActionReadinessResult,
    review_queue: ReviewQueueResult,
    approval_run: ApprovalPacketRunResult | None,
    settings_list: SettingsChangeRequestList,
    *,
    halt_before: HaltStatus,
    halt_after: HaltStatus,
) -> SupervisedPilotGoNoGo:
    missing_prereqs = tuple(candidates.missing_prerequisite_codes)
    prerequisite_counts = _prerequisite_counts(missing_prereqs)
    action_status_counts = _counts_from_mapping(action_queue.by_readiness_status)
    action_blocker_counts = _counts_from_mapping(action_queue.by_blocker_status)
    review_type_counts = _counts_from_mapping(review_queue.by_artifact_type)
    approval_preflight_counts = _approval_preflight_counts(approval_run)
    settings_type_counts = _counts_from_mapping(settings_list.by_request_type)
    settings_decision_counts = _counts_from_mapping(settings_list.by_decision_status)
    owner_prereqs = _owner_decision_prerequisites(
        candidates.remaining_owner_approval_types,
        approval_run,
        settings_list,
    )
    gates = _gates(
        candidates,
        action_queue,
        review_queue,
        settings_list,
        owner_prereqs=owner_prereqs,
        halt_after=halt_after,
    )
    overall_status = _overall_status(gates)
    next_actions = _next_actions(candidates, overall_status, gates)
    return SupervisedPilotGoNoGo(
        generated_at=datetime.now(tz=UTC),
        packet_kind=PACKET_KIND,
        purpose=PACKET_PURPOSE,
        overall_status=overall_status,
        read_only=True,
        no_execution=True,
        no_go_live=True,
        no_deployment=True,
        no_outbound=True,
        no_provider_calls=True,
        no_spend=True,
        dry_run_only=True,
        executed=0,
        execution_attempted=False,
        outbound_attempted=False,
        live_call_attempted=False,
        recommendation_applied=False,
        spend_attempted=False,
        spend_allowed=False,
        campaign_launched=False,
        pages_published=False,
        ads_launched=False,
        owner_approved=False,
        settings_applied=False,
        halt_changed=False,
        live_action=False,
        execution_allowed=False,
        future_execution_phase_exists=False,
        future_deployment_phase_exists=False,
        go_live_permitted=False,
        deployment_allowed=False,
        deployment_attempted=False,
        deployed=False,
        build_allowed=False,
        artifact_publish_allowed=False,
        container_build_attempted=False,
        artifact_publish_attempted=False,
        outbound_enabled=candidates.outbound_enabled,
        live_providers_enabled=candidates.live_providers_enabled,
        manual_review_only=True,
        supervised_pilot_go_no_go_is_not_go_live=True,
        export_is_not_permission_to_go_live=True,
        export_is_not_execution=True,
        supervised_pilot_plan_is_not_go_live=True,
        supervised_pilot_candidates_is_not_go_live=True,
        rehearsal_outcome_report_is_not_go_live=True,
        go_live_rehearsal_checklist_is_not_go_live=True,
        provider_setup_checklist_is_not_go_live=True,
        operator_halt_status=halt_after.value,
        operator_halt_before=halt_before.value,
        operator_halt_after=halt_after.value,
        prerequisite_counts_by_status=prerequisite_counts,
        missing_prerequisite_codes=missing_prereqs,
        candidate_counts_by_readiness=tuple(
            GoNoGoCount(key=item.key, count=item.count)
            for item in candidates.candidate_counts_by_readiness
        ),
        blocked_reason_counts=tuple(
            GoNoGoCount(key=item.key, count=item.count) for item in candidates.blocked_counts
        ),
        ready_for_review_count=candidates.candidate_scope.ready_for_review_count,
        blocked_candidate_count=candidates.candidate_scope.blocked_candidate_count,
        total_candidate_count=candidates.candidate_scope.total_candidate_count,
        review_queue_pending_count=review_queue.pending_count,
        review_queue_decided_count=review_queue.decided_count,
        review_queue_counts_by_artifact_type=review_type_counts,
        action_readiness_candidate_count=action_queue.candidate_count,
        action_readiness_counts_by_status=action_status_counts,
        action_readiness_counts_by_blocker=action_blocker_counts,
        approval_packet_count=0 if approval_run is None else approval_run.packet_count,
        approval_packet_counts_by_preflight=approval_preflight_counts,
        settings_request_count=settings_list.request_count,
        settings_request_pending_count=settings_list.pending_count,
        settings_request_counts_by_type=settings_type_counts,
        settings_request_counts_by_decision=settings_decision_counts,
        go_no_go_gates=gates,
        owner_decision_prerequisites=owner_prereqs,
        remaining_owner_approval_types=tuple(candidates.remaining_owner_approval_types),
        closed_provider_flag_names=tuple(candidates.closed_provider_flag_names),
        missing_credential_names=tuple(candidates.missing_credential_names),
        missing_config_names=tuple(candidates.missing_config_names),
        blocker_codes=_unique_sorted(
            (*candidates.blocker_codes, *(item.code for item in gates if item.blocking))
        ),
        gate_codes=_unique_sorted((*candidates.gate_codes, *(item.code for item in gates))),
        cli_command=CLI_COMMAND,
        http_route=HTTP_ROUTE,
        source_pilot_plan_command=candidates.source_pilot_plan_command,
        source_pilot_plan_route=candidates.source_pilot_plan_route,
        source_pilot_plan_html_route=candidates.source_pilot_plan_html_route,
        source_pilot_plan_overall_status=candidates.source_pilot_plan_overall_status,
        source_candidates_command=CANDIDATES_CLI_COMMAND,
        source_candidates_route=CANDIDATES_HTTP_ROUTE,
        source_candidates_html_route=CANDIDATES_HTML_ROUTE,
        source_candidates_overall_status=candidates.overall_status,
        source_outcome_command=candidates.source_outcome_command,
        source_outcome_route=candidates.source_outcome_route,
        source_outcome_overall_status=candidates.source_outcome_overall_status,
        source_rehearsal_command=candidates.source_rehearsal_command,
        source_rehearsal_route=candidates.source_rehearsal_route,
        source_rehearsal_overall_status=candidates.source_rehearsal_overall_status,
        source_launch_readiness_command=candidates.source_launch_readiness_command,
        source_launch_readiness_route=candidates.source_launch_readiness_route,
        source_launch_readiness_overall_status=candidates.source_launch_readiness_overall_status,
        source_index_command=candidates.source_index_command,
        source_index_route=candidates.source_index_route,
        source_index_overall_status=candidates.source_index_overall_status,
        source_provider_setup_command=candidates.source_provider_setup_command,
        source_provider_setup_route=candidates.source_provider_setup_route,
        source_provider_setup_overall_status=candidates.source_provider_setup_overall_status,
        related_commands=RELATED_COMMANDS,
        related_routes=RELATED_ROUTES,
        local_git=candidates.local_git,
        next_actions=next_actions,
    )


def _prerequisite_counts(missing_prereqs: Sequence[str]) -> tuple[GoNoGoCount, ...]:
    missing = set(missing_prereqs)
    tally: Counter[str] = Counter({key: 0 for key in KNOWN_PREREQUISITE_STATUSES})
    for key in PREREQUISITE_KEYS:
        if key in missing:
            tally[FindingSeverity.BLOCKED.value] += 1
        else:
            tally["ready_for_owner_review"] += 1
    return tuple(GoNoGoCount(key=key, count=tally[key]) for key in sorted(tally))


def _approval_preflight_counts(
    approval_run: ApprovalPacketRunResult | None,
) -> tuple[GoNoGoCount, ...]:
    tally: Counter[str] = Counter()
    if approval_run is not None:
        for packet in approval_run.packets:
            key = _safe_text(packet.preflight_status)
            if key:
                tally[key] += 1
    return tuple(GoNoGoCount(key=key, count=tally[key]) for key in sorted(tally))


def _owner_decision_prerequisites(
    remaining_approval_types: Sequence[str],
    approval_run: ApprovalPacketRunResult | None,
    settings_list: SettingsChangeRequestList,
) -> tuple[str, ...]:
    codes = list(remaining_approval_types)
    if approval_run is not None:
        for packet in approval_run.packets:
            codes.extend(packet.required_owner_decisions)
            if packet.decision is None:
                codes.append("owner_approval_packet")
    if settings_list.pending_count:
        codes.extend(settings_list.by_request_type.keys())
        codes.append("settings_change_request")
    return _unique_sorted(codes)


def _gates(
    candidates: SupervisedPilotCandidates,
    action_queue: ActionReadinessResult,
    review_queue: ReviewQueueResult,
    settings_list: SettingsChangeRequestList,
    *,
    owner_prereqs: Sequence[str],
    halt_after: HaltStatus,
) -> tuple[GoNoGoGate, ...]:
    blocked_action = int(action_queue.by_readiness_status.get(FindingSeverity.BLOCKED.value, 0))
    outbound_status = (
        FindingSeverity.BLOCKED.value
        if candidates.outbound_enabled
        else FindingSeverity.INFO.value
    )
    halt_status = (
        FindingSeverity.INFO.value
        if halt_after is HaltStatus.HALTED
        else FindingSeverity.WARNING.value
    )
    providers_status = (
        FindingSeverity.BLOCKED.value
        if candidates.live_providers_enabled
        else FindingSeverity.INFO.value
    )
    review_status = (
        FindingSeverity.WARNING.value
        if review_queue.pending_count
        else FindingSeverity.INFO.value
    )
    action_status = (
        FindingSeverity.BLOCKED.value
        if blocked_action
        else (
            FindingSeverity.WARNING.value
            if action_queue.candidate_count
            else FindingSeverity.INFO.value
        )
    )
    approval_status = (
        FindingSeverity.WARNING.value
        if owner_prereqs
        else FindingSeverity.INFO.value
    )
    credential_status = (
        FindingSeverity.BLOCKED.value
        if candidates.missing_credential_names
        else FindingSeverity.INFO.value
    )
    config_status = (
        FindingSeverity.BLOCKED.value
        if candidates.missing_config_names
        else FindingSeverity.INFO.value
    )
    settings_status = (
        FindingSeverity.WARNING.value
        if settings_list.pending_count
        else FindingSeverity.INFO.value
    )
    candidate_status = _safe_text(candidates.overall_status) or FindingSeverity.INFO.value
    if candidates.candidate_scope.ready_for_review_count == 0:
        candidate_status = _worst_status(candidate_status, FindingSeverity.WARNING.value)
    return (
        _gate(
            "outbound_disabled",
            outbound_status,
            (
                "OUTBOUND_ENABLED remains false. This packet does not "
                "enable outbound and is not permission to go live."
            ),
            blocking=candidates.outbound_enabled,
            command_name="launch-readiness",
            json_route="/internal/launch-readiness",
        ),
        _gate(
            "operator_halt",
            halt_status,
            (
                "Operator halt is read and left unchanged. This packet "
                "does not lift halt."
            ),
            blocking=False,
            command_name="system-status",
            json_route="/internal/dashboard/safety",
        ),
        _gate(
            "live_providers_closed",
            providers_status,
            (
                "Live-provider flags remain closed. This packet does not "
                "enable providers or call them."
            ),
            blocking=candidates.live_providers_enabled,
            command_name="provider-setup-checklist",
            json_route="/internal/provider-setup-checklist",
            html_route="/internal/operator-provider-setup-checklist",
        ),
        _gate(
            "execution_disabled",
            FindingSeverity.INFO.value,
            (
                "Execution remains disabled. This packet does not run "
                "commands, apply settings, deploy, send, or spend."
            ),
            blocking=False,
            command_name=CLI_COMMAND,
            json_route=HTTP_ROUTE,
            html_route=HTML_ROUTE,
        ),
        _gate(
            "supervised_pilot_plan",
            candidates.source_pilot_plan_overall_status,
            "Review the source supervised pilot launch plan as codes only.",
            blocking=_is_blocking(candidates.source_pilot_plan_overall_status),
            command_name=PILOT_CLI_COMMAND,
            json_route=PILOT_HTTP_ROUTE,
            html_route=PILOT_HTML_ROUTE,
        ),
        _gate(
            "candidate_readiness",
            candidate_status,
            "Review candidate readiness counts and blocked-reason codes only.",
            blocking=_is_blocking(candidate_status),
            command_name=CANDIDATES_CLI_COMMAND,
            json_route=CANDIDATES_HTTP_ROUTE,
            html_route=CANDIDATES_HTML_ROUTE,
        ),
        _gate(
            "provider_setup",
            candidates.source_provider_setup_overall_status,
            "Review provider setup checklist status using config names only.",
            blocking=_is_blocking(candidates.source_provider_setup_overall_status),
            command_name=candidates.source_provider_setup_command,
            json_route=candidates.source_provider_setup_route,
            html_route="/internal/operator-provider-setup-checklist",
        ),
        _gate(
            "rehearsal_outcome",
            candidates.source_outcome_overall_status,
            "Review the rehearsal outcome report as counts and codes only.",
            blocking=_is_blocking(candidates.source_outcome_overall_status),
            command_name=candidates.source_outcome_command,
            json_route=candidates.source_outcome_route,
            html_route="/internal/operator-rehearsal-outcome-report",
        ),
        _gate(
            "launch_readiness",
            candidates.source_launch_readiness_overall_status,
            "Review launch readiness using statuses, codes, and flag names only.",
            blocking=_is_blocking(candidates.source_launch_readiness_overall_status),
            command_name=candidates.source_launch_readiness_command,
            json_route=candidates.source_launch_readiness_route,
        ),
        _gate(
            "go_live_index",
            candidates.source_index_overall_status,
            "Review the go-live readiness index. It is not permission to go live.",
            blocking=_is_blocking(candidates.source_index_overall_status),
            command_name=candidates.source_index_command,
            json_route=candidates.source_index_route,
            html_route="/internal/operator-go-live-readiness-index",
        ),
        _gate(
            "review_queue",
            review_status,
            "Review-queue pending counts only. This packet does not record decisions.",
            blocking=False,
            command_name="action-readiness",
            json_route="/internal/review-queue",
            html_route="/internal/operator-review-queue",
        ),
        _gate(
            "action_readiness",
            action_status,
            "Action-readiness counts only. This packet does not execute approved items.",
            blocking=bool(blocked_action),
            command_name="action-readiness",
            json_route="/internal/action-readiness",
            html_route="/internal/operator-action-readiness",
        ),
        _gate(
            "owner_approvals",
            approval_status,
            "Owner decision prerequisites remain as approval type and code names only.",
            blocking=False,
            command_name="settings-execution-preflight",
            json_route="/internal/settings-execution-preflight",
            html_route="/internal/operator-approval-packets",
        ),
        _gate(
            "missing_credentials",
            credential_status,
            "Missing credential variable names only. Values are never exported.",
            blocking=bool(candidates.missing_credential_names),
            command_name="check-config",
            json_route="/internal/launch-readiness",
        ),
        _gate(
            "missing_config",
            config_status,
            "Missing config names only. Raw env values are never exported.",
            blocking=bool(candidates.missing_config_names),
            command_name="check-config",
            json_route="/internal/launch-readiness",
        ),
        _gate(
            "settings_requests",
            settings_status,
            "Settings-request counts by type and decision only. No apply or execute.",
            blocking=False,
            command_name="settings-execution-preflight",
            json_route="/internal/operator-settings-change-requests",
            html_route="/internal/operator-settings-change-requests",
        ),
        _gate(
            "packet_is_not_go_live",
            FindingSeverity.INFO.value,
            (
                "This supervised pilot go/no-go packet is owner review "
                "only. It is not permission to go live and not an "
                "execution surface."
            ),
            blocking=False,
            command_name=CLI_COMMAND,
            json_route=HTTP_ROUTE,
            html_route=HTML_ROUTE,
        ),
    )


def _gate(
    code: str,
    status: str,
    label: str,
    *,
    blocking: bool,
    command_name: str | None = None,
    json_route: str | None = None,
    html_route: str | None = None,
) -> GoNoGoGate:
    cleaned_status = _safe_text(status) or FindingSeverity.INFO.value
    return GoNoGoGate(
        code=_safe_text(code),
        status=cleaned_status,
        label=_safe_text(label),
        blocking=bool(blocking) or _is_blocking(cleaned_status),
        command_name=_safe_optional(command_name),
        json_route=_safe_optional(json_route),
        html_route=_safe_optional(html_route),
    )


def _overall_status(gates: Sequence[GoNoGoGate]) -> str:
    statuses = [item.status for item in gates]
    worst = _worst_status(*statuses) if statuses else FindingSeverity.INFO.value
    if worst == FindingSeverity.BLOCKED.value:
        return FindingSeverity.BLOCKED.value
    if worst == FindingSeverity.WARNING.value:
        return FindingSeverity.WARNING.value
    if worst == "ready_for_owner_review":
        return "ready_for_owner_review"
    return FindingSeverity.INFO.value


def _next_actions(
    candidates: SupervisedPilotCandidates,
    overall_status: str,
    gates: Sequence[GoNoGoGate],
) -> tuple[GoNoGoNextAction, ...]:
    actions = [
        _action(
            GO_NO_GO_NOT_GO_LIVE_CODE,
            FindingSeverity.INFO.value,
            (
                "This supervised pilot go/no-go packet is a sanitized "
                "owner-review export. It is not permission to go live "
                "and not an execution surface."
            ),
            command_name=CLI_COMMAND,
            json_route=HTTP_ROUTE,
            html_route=HTML_ROUTE,
        ),
        _action(
            EXECUTION_DISABLED_CODE,
            FindingSeverity.INFO.value,
            (
                "Execution remains disabled. This packet does not "
                "select candidates, run commands, apply settings, lift "
                "halt, enable outbound, deploy, build, publish, send, "
                "or spend."
            ),
            command_name=CLI_COMMAND,
            json_route=HTTP_ROUTE,
            html_route=HTML_ROUTE,
        ),
        _action(
            NextActionCode.SUPERVISED_PILOT_PLAN_IS_NOT_GO_LIVE.value,
            candidates.source_pilot_plan_overall_status,
            (
                "Review the source supervised pilot launch plan. "
                "Planning export only; it is not permission to go live."
            ),
            command_name=PILOT_CLI_COMMAND,
            json_route=PILOT_HTTP_ROUTE,
            html_route=PILOT_HTML_ROUTE,
        ),
        _action(
            NextActionCode.SUPERVISED_PILOT_CANDIDATES_IS_NOT_GO_LIVE.value,
            candidates.overall_status,
            (
                "Review the source supervised pilot candidate readiness "
                "export. Count-only review; it is not permission to go live."
            ),
            command_name=CANDIDATES_CLI_COMMAND,
            json_route=CANDIDATES_HTTP_ROUTE,
            html_route=CANDIDATES_HTML_ROUTE,
        ),
        _action(
            NextActionCode.KEEP_OUTBOUND_DISABLED.value,
            FindingSeverity.INFO.value,
            "Keep OUTBOUND_ENABLED=false.",
            command_name="launch-readiness",
            json_route="/internal/launch-readiness",
            config_name="OUTBOUND_ENABLED",
        ),
    ]
    seen = {item.code for item in actions}
    for gate in gates:
        if not gate.blocking or gate.code in seen:
            continue
        seen.add(gate.code)
        actions.append(
            _action(
                gate.code,
                gate.status,
                gate.label,
                command_name=gate.command_name,
                json_route=gate.json_route,
                html_route=gate.html_route,
            )
        )
    if overall_status == FindingSeverity.BLOCKED.value:
        actions.append(
            _action(
                "review_go_no_go_blockers",
                overall_status,
                (
                    "A first controlled pilot remains blocked. Review "
                    "blocking gate codes, missing config names, and "
                    "blocked-reason counts only."
                ),
                command_name=CLI_COMMAND,
                json_route=HTTP_ROUTE,
            )
        )
    return tuple(actions)


def _action(
    code: str,
    status: str,
    label: str,
    *,
    command_name: str | None = None,
    json_route: str | None = None,
    html_route: str | None = None,
    config_name: str | None = None,
) -> GoNoGoNextAction:
    return GoNoGoNextAction(
        code=_safe_text(code),
        status=_safe_text(status) or FindingSeverity.INFO.value,
        label=_safe_text(label),
        command_name=_safe_optional(command_name),
        json_route=_safe_optional(json_route),
        html_route=_safe_optional(html_route),
        config_name=_safe_optional(config_name),
    )


def _counts_from_mapping(mapping: dict[str, int]) -> tuple[GoNoGoCount, ...]:
    cleaned: dict[str, int] = {}
    for raw, value in mapping.items():
        key = _safe_text(raw)
        if key:
            cleaned[key] = int(value)
    return tuple(GoNoGoCount(key=key, count=cleaned[key]) for key in sorted(cleaned))


def _is_blocking(status: str) -> bool:
    return _safe_text(status) == FindingSeverity.BLOCKED.value


def _worst_status(*values: str) -> str:
    cleaned = [_safe_text(item) or FindingSeverity.INFO.value for item in values if item]
    if not cleaned:
        return FindingSeverity.INFO.value
    return max(cleaned, key=lambda item: _STATUS_RANK.get(item, 0))


def _unique_sorted(values: Iterable[str | None]) -> tuple[str, ...]:
    cleaned = [_safe_text(item) for item in values if item]
    return tuple(sorted({item for item in cleaned if item}))


def _safe_optional(value: str | None) -> str | None:
    cleaned = _safe_text(value) if value is not None else ""
    return cleaned or None


def _safe_text(value: object) -> str:
    if value is None:
        return ""
    text = sanitize_operator_text(str(value))
    return text or ""


def _bool_text(value: object) -> str:
    return "true" if value else "false"


def supervised_pilot_go_no_go_payload(packet: SupervisedPilotGoNoGo) -> dict[str, Any]:
    return {
        "generated_at": packet.generated_at.isoformat(),
        "packet_kind": packet.packet_kind,
        "purpose": packet.purpose,
        "overall_status": packet.overall_status,
        "read_only": True,
        "no_execution": True,
        "no_go_live": True,
        "no_deployment": True,
        "no_outbound": True,
        "no_provider_calls": True,
        "no_spend": True,
        "dry_run_only": True,
        "executed": 0,
        "execution_attempted": False,
        "outbound_attempted": False,
        "live_call_attempted": False,
        "recommendation_applied": False,
        "spend_attempted": False,
        "spend_allowed": False,
        "campaign_launched": False,
        "pages_published": False,
        "ads_launched": False,
        "owner_approved": False,
        "settings_applied": False,
        "halt_changed": False,
        "live_action": False,
        "execution_allowed": False,
        "future_execution_phase_exists": False,
        "future_deployment_phase_exists": False,
        "go_live_permitted": False,
        "deployment_allowed": False,
        "deployment_attempted": False,
        "deployed": False,
        "build_allowed": False,
        "artifact_publish_allowed": False,
        "container_build_attempted": False,
        "artifact_publish_attempted": False,
        "outbound_enabled": packet.outbound_enabled,
        "live_providers_enabled": packet.live_providers_enabled,
        "manual_review_only": True,
        "supervised_pilot_go_no_go_is_not_go_live": True,
        "export_is_not_permission_to_go_live": True,
        "export_is_not_execution": True,
        "supervised_pilot_plan_is_not_go_live": True,
        "supervised_pilot_candidates_is_not_go_live": True,
        "rehearsal_outcome_report_is_not_go_live": True,
        "go_live_rehearsal_checklist_is_not_go_live": True,
        "provider_setup_checklist_is_not_go_live": True,
        "operator_halt_status": packet.operator_halt_status,
        "operator_halt_before": packet.operator_halt_before,
        "operator_halt_after": packet.operator_halt_after,
        "prerequisite_counts_by_status": [
            _count_payload(item) for item in packet.prerequisite_counts_by_status
        ],
        "missing_prerequisite_codes": list(packet.missing_prerequisite_codes),
        "candidate_counts_by_readiness": [
            _count_payload(item) for item in packet.candidate_counts_by_readiness
        ],
        "blocked_reason_counts": [
            _count_payload(item) for item in packet.blocked_reason_counts
        ],
        "ready_for_review_count": packet.ready_for_review_count,
        "blocked_candidate_count": packet.blocked_candidate_count,
        "total_candidate_count": packet.total_candidate_count,
        "review_queue_pending_count": packet.review_queue_pending_count,
        "review_queue_decided_count": packet.review_queue_decided_count,
        "review_queue_counts_by_artifact_type": [
            _count_payload(item) for item in packet.review_queue_counts_by_artifact_type
        ],
        "action_readiness_candidate_count": packet.action_readiness_candidate_count,
        "action_readiness_counts_by_status": [
            _count_payload(item) for item in packet.action_readiness_counts_by_status
        ],
        "action_readiness_counts_by_blocker": [
            _count_payload(item) for item in packet.action_readiness_counts_by_blocker
        ],
        "approval_packet_count": packet.approval_packet_count,
        "approval_packet_counts_by_preflight": [
            _count_payload(item) for item in packet.approval_packet_counts_by_preflight
        ],
        "settings_request_count": packet.settings_request_count,
        "settings_request_pending_count": packet.settings_request_pending_count,
        "settings_request_counts_by_type": [
            _count_payload(item) for item in packet.settings_request_counts_by_type
        ],
        "settings_request_counts_by_decision": [
            _count_payload(item) for item in packet.settings_request_counts_by_decision
        ],
        "go_no_go_gates": [_gate_payload(item) for item in packet.go_no_go_gates],
        "owner_decision_prerequisites": list(packet.owner_decision_prerequisites),
        "remaining_owner_approval_types": list(packet.remaining_owner_approval_types),
        "closed_provider_flag_names": list(packet.closed_provider_flag_names),
        "missing_credential_names": list(packet.missing_credential_names),
        "missing_config_names": list(packet.missing_config_names),
        "blocker_codes": list(packet.blocker_codes),
        "gate_codes": list(packet.gate_codes),
        "cli_command": CLI_COMMAND,
        "http_route": HTTP_ROUTE,
        "source_pilot_plan_command": packet.source_pilot_plan_command,
        "source_pilot_plan_route": packet.source_pilot_plan_route,
        "source_pilot_plan_html_route": packet.source_pilot_plan_html_route,
        "source_pilot_plan_overall_status": packet.source_pilot_plan_overall_status,
        "source_candidates_command": packet.source_candidates_command,
        "source_candidates_route": packet.source_candidates_route,
        "source_candidates_html_route": packet.source_candidates_html_route,
        "source_candidates_overall_status": packet.source_candidates_overall_status,
        "source_outcome_command": packet.source_outcome_command,
        "source_outcome_route": packet.source_outcome_route,
        "source_outcome_overall_status": packet.source_outcome_overall_status,
        "source_rehearsal_command": packet.source_rehearsal_command,
        "source_rehearsal_route": packet.source_rehearsal_route,
        "source_rehearsal_overall_status": packet.source_rehearsal_overall_status,
        "source_launch_readiness_command": packet.source_launch_readiness_command,
        "source_launch_readiness_route": packet.source_launch_readiness_route,
        "source_launch_readiness_overall_status": packet.source_launch_readiness_overall_status,
        "source_index_command": packet.source_index_command,
        "source_index_route": packet.source_index_route,
        "source_index_overall_status": packet.source_index_overall_status,
        "source_provider_setup_command": packet.source_provider_setup_command,
        "source_provider_setup_route": packet.source_provider_setup_route,
        "source_provider_setup_overall_status": packet.source_provider_setup_overall_status,
        "related_commands": list(packet.related_commands),
        "related_routes": list(packet.related_routes),
        "local_git": {
            "available": packet.local_git.available,
            "current_branch": packet.local_git.current_branch,
            "current_sha": packet.local_git.current_sha,
            "working_tree_status": packet.local_git.working_tree_status,
            "git_provider_called": False,
            "github_actions_called": False,
        },
        "next_actions": [_action_payload(action) for action in packet.next_actions],
    }


def _count_payload(item: GoNoGoCount) -> dict[str, Any]:
    return {"key": item.key, "count": item.count}


def _gate_payload(item: GoNoGoGate) -> dict[str, Any]:
    return {
        "code": item.code,
        "status": item.status,
        "label": item.label,
        "blocking": item.blocking,
        "command_name": item.command_name,
        "json_route": item.json_route,
        "html_route": item.html_route,
    }


def _action_payload(action: GoNoGoNextAction) -> dict[str, Any]:
    return {
        "code": action.code,
        "status": action.status,
        "label": action.label,
        "command_name": action.command_name,
        "json_route": action.json_route,
        "html_route": action.html_route,
        "config_name": action.config_name,
    }


def format_supervised_pilot_go_no_go(
    packet: SupervisedPilotGoNoGo,
    *,
    as_json: bool = False,
) -> str:
    payload = sanitize_mapping(supervised_pilot_go_no_go_payload(packet))
    if as_json:
        return json.dumps(payload, sort_keys=True)
    return _format_markdown(packet, payload)


def _format_markdown(packet: SupervisedPilotGoNoGo, payload: dict[str, Any]) -> str:
    lines = [
        "# Supervised pilot go/no-go packet",
        "",
        "This export is a sanitized go/no-go review packet over the "
        "supervised pilot plan, candidate readiness, provider setup, "
        "rehearsal outcome, launch readiness, go-live index, review and "
        "action-readiness queues, owner approval and settings-request "
        "rollups, and operator halt state. It reuses those services as "
        "source material and never executes commands, applies settings, "
        "lifts halt, enables outbound, deploys, builds, publishes, sends, "
        "or spends. It is not permission to go live and not an execution "
        "surface.",
        "",
        f"- overall: {payload['overall_status']}",
        f"- packet_kind: {payload['packet_kind']}",
        f"- purpose: {payload['purpose']}",
        f"- read_only: {_bool_text(payload['read_only'])}",
        f"- no_execution: {_bool_text(payload['no_execution'])}",
        f"- no_go_live: {_bool_text(payload['no_go_live'])}",
        f"- no_deployment: {_bool_text(payload['no_deployment'])}",
        f"- no_outbound: {_bool_text(payload['no_outbound'])}",
        f"- no_provider_calls: {_bool_text(payload['no_provider_calls'])}",
        f"- no_spend: {_bool_text(payload['no_spend'])}",
        f"- dry_run_only: {_bool_text(payload['dry_run_only'])}",
        f"- executed: {payload['executed']}",
        f"- owner_approved: {_bool_text(payload['owner_approved'])}",
        f"- settings_applied: {_bool_text(payload['settings_applied'])}",
        f"- halt_changed: {_bool_text(payload['halt_changed'])}",
        f"- live_action: {_bool_text(payload['live_action'])}",
        f"- execution_allowed: {_bool_text(payload['execution_allowed'])}",
        f"- go_live_permitted: {_bool_text(payload['go_live_permitted'])}",
        f"- deployment_allowed: {_bool_text(payload['deployment_allowed'])}",
        f"- spend_allowed: {_bool_text(payload['spend_allowed'])}",
        f"- manual_review_only: {_bool_text(payload['manual_review_only'])}",
        (
            "- supervised_pilot_go_no_go_is_not_go_live: "
            f"{_bool_text(payload['supervised_pilot_go_no_go_is_not_go_live'])}"
        ),
        (
            "- export_is_not_permission_to_go_live: "
            f"{_bool_text(payload['export_is_not_permission_to_go_live'])}"
        ),
        f"- export_is_not_execution: {_bool_text(payload['export_is_not_execution'])}",
        (
            "- operator_halt: "
            f"status={payload['operator_halt_status']} "
            f"before={payload['operator_halt_before']} "
            f"after={payload['operator_halt_after']}"
        ),
        f"- outbound_enabled: {_bool_text(payload['outbound_enabled'])}",
        f"- live_providers_enabled: {_bool_text(payload['live_providers_enabled'])}",
        f"- cli_command: {payload['cli_command']}",
        f"- http_route: {payload['http_route']}",
        f"- source_pilot_plan_command: {payload['source_pilot_plan_command']}",
        f"- source_candidates_command: {payload['source_candidates_command']}",
        f"- source_outcome_command: {payload['source_outcome_command']}",
        f"- source_rehearsal_command: {payload['source_rehearsal_command']}",
        f"- source_launch_readiness_command: {payload['source_launch_readiness_command']}",
        f"- source_index_command: {payload['source_index_command']}",
        f"- source_provider_setup_command: {payload['source_provider_setup_command']}",
        f"- blocker_codes: {_format_codes(packet.blocker_codes)}",
        f"- gate_codes: {_format_codes(packet.gate_codes)}",
        f"- missing_prerequisite_codes: {_format_codes(packet.missing_prerequisite_codes)}",
        (
            "- owner_decision_prerequisites: "
            f"{_format_codes(packet.owner_decision_prerequisites)}"
        ),
        f"- remaining_owner_approval_types: {_format_codes(packet.remaining_owner_approval_types)}",
        f"- missing_credential_names: {_format_codes(packet.missing_credential_names)}",
        f"- missing_config_names: {_format_codes(packet.missing_config_names)}",
        f"- closed_provider_flag_names: {_format_codes(packet.closed_provider_flag_names)}",
        "",
        "## Live-blocking flags",
        f"- OUTBOUND_ENABLED={_bool_text(packet.outbound_enabled)}",
        f"- operator_halt_status={packet.operator_halt_status}",
        f"- live_providers_enabled={_bool_text(packet.live_providers_enabled)}",
        "- read_only=true",
        "- no_execution=true",
        "- no_go_live=true",
        "- no_outbound=true",
        "- no_provider_calls=true",
        "- no_spend=true",
        "- manual_review_only=true",
        "- execution_allowed=false",
        "- go_live_permitted=false",
        "- deployment_allowed=false",
        "- spend_allowed=false",
        "- settings_applied=false",
        "- halt_changed=false",
        "- owner_approved=false",
        "- supervised_pilot_go_no_go_is_not_go_live=true",
        "- export_is_not_permission_to_go_live=true",
        "- export_is_not_execution=true",
        f"- local_git_available: {_bool_text(packet.local_git.available)}",
        f"- current_branch: {packet.local_git.current_branch}",
        f"- current_sha: {packet.local_git.current_sha}",
        f"- working_tree_status: {packet.local_git.working_tree_status}",
        f"- git_provider_called: {_bool_text(packet.local_git.git_provider_called)}",
        f"- github_actions_called: {_bool_text(packet.local_git.github_actions_called)}",
        "",
        "## Prerequisite category summary",
    ]
    _append_counts(lines, packet.prerequisite_counts_by_status)
    lines.extend(
        [
            "",
            "## Candidate readiness summary",
            f"- ready_for_review_count: {packet.ready_for_review_count}",
            f"- blocked_candidate_count: {packet.blocked_candidate_count}",
            f"- total_candidate_count: {packet.total_candidate_count}",
        ]
    )
    _append_counts(lines, packet.candidate_counts_by_readiness)
    lines.extend(["", "## Blocked-count reasons"])
    _append_counts(lines, packet.blocked_reason_counts)
    lines.extend(
        [
            "",
            "## Review and action readiness queues",
            f"- review_queue_pending_count: {packet.review_queue_pending_count}",
            f"- review_queue_decided_count: {packet.review_queue_decided_count}",
            f"- action_readiness_candidate_count: {packet.action_readiness_candidate_count}",
            f"- approval_packet_count: {packet.approval_packet_count}",
            f"- settings_request_count: {packet.settings_request_count}",
            f"- settings_request_pending_count: {packet.settings_request_pending_count}",
        ]
    )
    lines.extend(["", "## Go/no-go gates"])
    for gate in packet.go_no_go_gates:
        command_name = gate.command_name or "-"
        json_route = gate.json_route or "-"
        html_route = gate.html_route or "-"
        lines.append(
            f"- [{gate.status}] {gate.code} blocking={_bool_text(gate.blocking)} "
            f"command={command_name} json_route={json_route} "
            f"html_route={html_route} label={gate.label}"
        )
    lines.extend(["", "## Owner next actions"])
    for action in packet.next_actions:
        command_name = action.command_name or "-"
        json_route = action.json_route or "-"
        html_route = action.html_route or "-"
        config_name = action.config_name or "-"
        lines.append(
            f"- [{action.status}] {action.code} command={command_name} "
            f"json_route={json_route} html_route={html_route} "
            f"config_name={config_name} label={action.label}"
        )
    if not packet.next_actions:
        lines.append("- next_actions: none")
    return "\n".join(lines)


def _append_counts(lines: list[str], items: Sequence[GoNoGoCount]) -> None:
    if not items:
        lines.append("- counts: none")
        return
    for item in items:
        lines.append(f"- {item.key}: {item.count}")


def _format_codes(values: Sequence[str]) -> str:
    return ",".join(values) if values else "-"
