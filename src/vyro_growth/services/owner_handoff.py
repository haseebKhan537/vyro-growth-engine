"""Read-only owner go-live handoff packet export.

Phase 32 consolidates existing launch-readiness, settings-change, settings
execution-preflight, owner approval-packet, and action-readiness summaries
into one sanitized owner-review artifact. It never applies settings, lifts
halt, executes packets or requests, calls providers, or goes live.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Never
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from vyro_growth.config import Settings, any_live_provider_enabled
from vyro_growth.domain import (
    ActionReadinessBlockerStatus,
    FindingSeverity,
    NextActionCode,
    SecretPresenceStatus,
    SettingsChangeDecisionStatus,
)
from vyro_growth.models import OwnerApprovalPacket, OwnerApprovalPacketDecision
from vyro_growth.observability import sanitize_mapping
from vyro_growth.services.action_readiness import ActionReadinessResult, ActionReadinessService
from vyro_growth.services.launch_readiness import LaunchReadinessChecklist, LaunchReadinessService
from vyro_growth.services.operator_halt import HaltStatus, read_operator_halt
from vyro_growth.services.settings_change_requests import (
    SettingsChangeRequestList,
    SettingsChangeRequestService,
)
from vyro_growth.services.settings_execution_preflight import (
    SettingsExecutionPreflight,
    SettingsExecutionPreflightService,
)

logger = structlog.get_logger(__name__)

PACKET_KIND = "owner_go_live_handoff"
PACKET_PURPOSE = "manual_owner_review_only"
HANDOFF_NOT_GO_LIVE_CODE = NextActionCode.HANDOFF_IS_NOT_GO_LIVE.value
EXECUTION_DISABLED_CODE = "execution_disabled_in_this_phase"
SECTION_LAUNCH = "launch_readiness"
SECTION_SETTINGS_REQUESTS = "settings_change_requests"
SECTION_SETTINGS_PREFLIGHT = "settings_execution_preflight"
SECTION_PACKETS = "owner_approval_packets"
SECTION_ACTION_READINESS = "approved_action_readiness"
SECTION_HANDOFF = "owner_handoff"

_SEVERITY_RANK = {
    FindingSeverity.INFO.value: 0,
    FindingSeverity.WARNING.value: 1,
    FindingSeverity.BLOCKED.value: 2,
}


@dataclass(frozen=True)
class HandoffLaunchReadinessSummary:
    overall_status: str
    operator_halt_status: str
    outbound_enabled: bool
    live_providers_enabled: bool
    config_ok: bool
    ci_smoke_gate_present: bool
    ci_smoke_gate_documented: bool
    ci_smoke_gate_job_name: str
    pending_owner_approval_packets: int
    action_readiness_candidate_count: int
    action_readiness_blocked_count: int
    pending_settings_change_request_count: int
    finding_codes: tuple[str, ...]
    blocker_codes: tuple[str, ...]
    next_action_codes: tuple[str, ...]
    missing_credential_names: tuple[str, ...]
    closed_provider_flag_names: tuple[str, ...]
    no_execution: bool
    owner_approved: bool
    live_action: bool


@dataclass(frozen=True)
class HandoffSettingsRequestItem:
    request_id: UUID
    request_type: str
    request_status: str
    decision_status: str
    requested_setting_names: tuple[str, ...]
    desired_boolean: bool | None
    desired_status: str | None
    finding_code: str | None
    next_action_code: str | None
    requested_at: datetime
    record_only: bool
    no_execution: bool
    executed: bool
    settings_applied: bool
    owner_approved: bool
    live_action: bool


@dataclass(frozen=True)
class HandoffSettingsRequestSummary:
    request_count: int
    pending_count: int
    approved_count: int
    rejected_count: int
    needs_changes_count: int
    by_request_type: dict[str, int]
    by_status: dict[str, int]
    by_decision_status: dict[str, int]
    request_ids: tuple[str, ...]
    setting_names: tuple[str, ...]
    record_only: bool
    no_execution: bool
    settings_applied: bool
    owner_approved: bool
    requests: tuple[HandoffSettingsRequestItem, ...]


@dataclass(frozen=True)
class HandoffSettingsPreflightItem:
    request_id: UUID
    request_type: str
    decision_status: str
    execution_status: str
    requested_setting_names: tuple[str, ...]
    desired_boolean: bool | None
    desired_status: str | None
    blocker_codes: tuple[str, ...]
    missing_approval_codes: tuple[str, ...]
    missing_gate_codes: tuple[str, ...]
    missing_credential_names: tuple[str, ...]
    closed_provider_flag_names: tuple[str, ...]
    requested_at: datetime
    simulated_at: datetime
    no_execution: bool
    dry_run_only: bool
    executed: bool
    settings_applied: bool
    owner_approved: bool
    execution_allowed: bool
    live_action: bool


@dataclass(frozen=True)
class HandoffSettingsPreflightSummary:
    overall_status: str
    request_count: int
    pending_decision_count: int
    approved_decision_count: int
    rejected_or_needs_changes_count: int
    blocked_count: int
    executable_count: int
    blocker_codes: tuple[str, ...]
    missing_approval_codes: tuple[str, ...]
    missing_gate_codes: tuple[str, ...]
    missing_credential_names: tuple[str, ...]
    closed_provider_flag_names: tuple[str, ...]
    execution_allowed: bool
    future_execution_phase_exists: bool
    dry_run_only: bool
    no_execution: bool
    settings_applied: bool
    owner_approved: bool
    requests: tuple[HandoffSettingsPreflightItem, ...]


@dataclass(frozen=True)
class HandoffApprovalPacketItem:
    packet_id: UUID
    plan_family: str
    preflight_status: str
    decision_status: str
    generated_at: datetime
    dry_run_only: bool
    no_execution: bool
    executed: bool
    owner_approved: bool
    live_action: bool


@dataclass(frozen=True)
class HandoffApprovalPacketSummary:
    packet_count: int
    pending_count: int
    approved_count: int
    rejected_count: int
    needs_changes_count: int
    by_preflight_status: dict[str, int]
    by_plan_family: dict[str, int]
    by_decision_status: dict[str, int]
    packet_ids: tuple[str, ...]
    no_execution: bool
    executed: int
    owner_approved: bool
    live_action: bool
    packets: tuple[HandoffApprovalPacketItem, ...]


@dataclass(frozen=True)
class HandoffActionReadinessItem:
    candidate_id: UUID
    plan_family: str
    readiness_status: str
    blocker_status: str
    review_decision_status: str
    packet_decision_status: str
    approval_packet_id: UUID | None
    blocker_codes: tuple[str, ...]
    missing_approval_codes: tuple[str, ...]
    missing_prerequisite_codes: tuple[str, ...]
    dry_run_only: bool
    no_execution: bool
    executed: bool
    owner_approved: bool
    live_action: bool
    execution_allowed: bool


@dataclass(frozen=True)
class HandoffActionReadinessSummary:
    candidate_count: int
    blocked_count: int
    by_readiness_status: dict[str, int]
    by_plan_family: dict[str, int]
    by_blocker_status: dict[str, int]
    by_decision_status: dict[str, int]
    candidate_ids: tuple[str, ...]
    dry_run_only: bool
    no_execution: bool
    executed_count: int
    owner_approved: bool
    live_action: bool
    explicit_live_owner_action_required: bool
    candidates: tuple[HandoffActionReadinessItem, ...]


@dataclass(frozen=True)
class HandoffChecklistItem:
    code: str
    severity: str
    source_section: str
    status: str


@dataclass(frozen=True)
class OwnerHandoffPacket:
    generated_at: datetime
    packet_kind: str
    purpose: str
    overall_status: str
    read_only: bool
    no_execution: bool
    dry_run_only: bool
    executed: int
    execution_attempted: bool
    outbound_attempted: bool
    live_call_attempted: bool
    recommendation_applied: bool
    spend_attempted: bool
    campaign_launched: bool
    pages_published: bool
    ads_launched: bool
    owner_approved: bool
    settings_applied: bool
    halt_changed: bool
    live_action: bool
    execution_allowed: bool
    future_execution_phase_exists: bool
    go_live_permitted: bool
    manual_review_only: bool
    operator_halt_status: str
    operator_halt_before: str
    operator_halt_after: str
    outbound_enabled: bool
    live_providers_enabled: bool
    blocker_codes: tuple[str, ...]
    missing_credential_names: tuple[str, ...]
    closed_provider_flag_names: tuple[str, ...]
    launch_readiness: HandoffLaunchReadinessSummary
    settings_change_requests: HandoffSettingsRequestSummary
    settings_execution_preflight: HandoffSettingsPreflightSummary
    owner_approval_packets: HandoffApprovalPacketSummary
    approved_action_readiness: HandoffActionReadinessSummary
    remaining_manual_owner_checklist: tuple[HandoffChecklistItem, ...]


class OwnerHandoffPacketService:
    """Compose existing read-only summaries into one owner-review packet."""

    def __init__(
        self,
        *,
        launch_readiness: LaunchReadinessService | None = None,
        settings_requests: SettingsChangeRequestService | None = None,
        settings_preflight: SettingsExecutionPreflightService | None = None,
        action_readiness: ActionReadinessService | None = None,
    ) -> None:
        self.launch_readiness = launch_readiness or LaunchReadinessService()
        self.settings_requests = settings_requests or SettingsChangeRequestService()
        self.settings_preflight = settings_preflight or SettingsExecutionPreflightService()
        self.action_readiness = action_readiness or ActionReadinessService()

    def build(self, db: Session, settings: Settings) -> OwnerHandoffPacket:
        halt_before = read_operator_halt(db)
        checklist = self.launch_readiness.assess(db, settings)
        requests = self.settings_requests.list_requests(db, settings)
        preflight = self.settings_preflight.simulate(db, settings)
        readiness = self.action_readiness.list_queue(db, settings)
        packets = _packet_summary(db)
        halt_after = read_operator_halt(db)
        if halt_after is not halt_before:
            raise RuntimeError("owner handoff packet must not change operator halt status")
        launch = _launch_summary(checklist)
        settings_summary = _settings_request_summary(requests)
        preflight_summary = _preflight_summary(preflight)
        action_summary = _action_readiness_summary(readiness)
        checklist_items = _remaining_checklist(
            launch=launch,
            settings_requests=settings_summary,
            preflight=preflight_summary,
            packets=packets,
            action_readiness=action_summary,
            outbound_enabled=settings.outbound_enabled,
            live_providers_enabled=any_live_provider_enabled(settings),
            halt=halt_after,
        )
        packet = OwnerHandoffPacket(
            generated_at=datetime.now(tz=UTC),
            packet_kind=PACKET_KIND,
            purpose=PACKET_PURPOSE,
            overall_status=checklist.overall_status,
            read_only=True,
            no_execution=True,
            dry_run_only=True,
            executed=0,
            execution_attempted=False,
            outbound_attempted=False,
            live_call_attempted=False,
            recommendation_applied=False,
            spend_attempted=False,
            campaign_launched=False,
            pages_published=False,
            ads_launched=False,
            owner_approved=False,
            settings_applied=False,
            halt_changed=False,
            live_action=False,
            execution_allowed=False,
            future_execution_phase_exists=False,
            go_live_permitted=False,
            manual_review_only=True,
            operator_halt_status=halt_after.value,
            operator_halt_before=halt_before.value,
            operator_halt_after=halt_after.value,
            outbound_enabled=settings.outbound_enabled,
            live_providers_enabled=any_live_provider_enabled(settings),
            blocker_codes=_unique_sorted(
                (
                    *launch.blocker_codes,
                    *preflight_summary.blocker_codes,
                    *tuple(
                        code
                        for item in action_summary.candidates
                        for code in item.blocker_codes
                    ),
                )
            ),
            missing_credential_names=_unique_sorted(
                (*launch.missing_credential_names, *preflight_summary.missing_credential_names)
            ),
            closed_provider_flag_names=_unique_sorted(
                (
                    *launch.closed_provider_flag_names,
                    *preflight_summary.closed_provider_flag_names,
                )
            ),
            launch_readiness=launch,
            settings_change_requests=settings_summary,
            settings_execution_preflight=preflight_summary,
            owner_approval_packets=packets,
            approved_action_readiness=action_summary,
            remaining_manual_owner_checklist=checklist_items,
        )
        logger.info(
            "owner_handoff_packet_built",
            packet_kind=PACKET_KIND,
            purpose=PACKET_PURPOSE,
            overall_status=packet.overall_status,
            read_only=True,
            no_execution=True,
            executed=0,
            settings_applied=False,
            owner_approved=False,
            live_action=False,
            execution_allowed=False,
            go_live_permitted=False,
            future_execution_phase_exists=False,
        )
        return packet


def format_owner_handoff(packet: OwnerHandoffPacket, *, as_json: bool = False) -> str:
    payload = sanitize_mapping(handoff_payload(packet))
    if as_json:
        return json.dumps(payload, sort_keys=True)
    return _format_markdown(packet, payload)


def handoff_payload(packet: OwnerHandoffPacket) -> dict[str, Any]:
    return {
        "generated_at": packet.generated_at.isoformat(),
        "packet_kind": PACKET_KIND,
        "purpose": PACKET_PURPOSE,
        "overall_status": packet.overall_status,
        "read_only": True,
        "no_execution": True,
        "dry_run_only": True,
        "executed": 0,
        "execution_attempted": False,
        "outbound_attempted": False,
        "live_call_attempted": False,
        "recommendation_applied": False,
        "spend_attempted": False,
        "campaign_launched": False,
        "pages_published": False,
        "ads_launched": False,
        "owner_approved": False,
        "settings_applied": False,
        "halt_changed": False,
        "live_action": False,
        "execution_allowed": False,
        "future_execution_phase_exists": False,
        "go_live_permitted": False,
        "manual_review_only": True,
        "operator_halt_status": packet.operator_halt_status,
        "operator_halt_before": packet.operator_halt_before,
        "operator_halt_after": packet.operator_halt_after,
        "outbound_enabled": packet.outbound_enabled,
        "live_providers_enabled": packet.live_providers_enabled,
        "blocker_codes": list(packet.blocker_codes),
        "missing_credential_names": list(packet.missing_credential_names),
        "closed_provider_flag_names": list(packet.closed_provider_flag_names),
        "launch_readiness": _launch_payload(packet.launch_readiness),
        "settings_change_requests": _settings_request_payload(packet.settings_change_requests),
        "settings_execution_preflight": _preflight_payload(packet.settings_execution_preflight),
        "owner_approval_packets": _packet_payload(packet.owner_approval_packets),
        "approved_action_readiness": _action_payload(packet.approved_action_readiness),
        "remaining_manual_owner_checklist": [
            {
                "code": item.code,
                "severity": item.severity,
                "source_section": item.source_section,
                "status": item.status,
            }
            for item in packet.remaining_manual_owner_checklist
        ],
    }


def _launch_summary(checklist: LaunchReadinessChecklist) -> HandoffLaunchReadinessSummary:
    finding_codes = _unique_sorted(item.code for item in checklist.findings)
    blocker_codes = _unique_sorted(
        item.code for item in checklist.findings if item.severity == FindingSeverity.BLOCKED.value
    )
    missing_credentials = _unique_sorted(
        item.name
        for item in checklist.secret_inventory
        if item.status == SecretPresenceStatus.MISSING.value
    )
    closed_flags = _unique_sorted(
        item.name
        for item in checklist.config_flags
        if not item.enabled and item.name != "OUTBOUND_ENABLED"
    )
    return HandoffLaunchReadinessSummary(
        overall_status=checklist.overall_status,
        operator_halt_status=checklist.operator_halt_status,
        outbound_enabled=checklist.outbound_enabled,
        live_providers_enabled=checklist.live_providers_enabled,
        config_ok=checklist.config_ok,
        ci_smoke_gate_present=checklist.ci_smoke_gate.present,
        ci_smoke_gate_documented=checklist.ci_smoke_gate.documented,
        ci_smoke_gate_job_name=checklist.ci_smoke_gate.job_name,
        pending_owner_approval_packets=checklist.pending_owner_approval_packets,
        action_readiness_candidate_count=checklist.action_readiness_candidate_count,
        action_readiness_blocked_count=checklist.action_readiness_blocked_count,
        pending_settings_change_request_count=checklist.pending_settings_change_request_count,
        finding_codes=finding_codes,
        blocker_codes=blocker_codes,
        next_action_codes=_unique_sorted(item.next_action_code for item in checklist.next_actions),
        missing_credential_names=missing_credentials,
        closed_provider_flag_names=closed_flags,
        no_execution=True,
        owner_approved=False,
        live_action=False,
    )


def _settings_request_summary(
    listed: SettingsChangeRequestList,
) -> HandoffSettingsRequestSummary:
    items = tuple(
        HandoffSettingsRequestItem(
            request_id=item.request_id,
            request_type=item.request_type,
            request_status=item.status,
            decision_status=item.owner_decision_status,
            requested_setting_names=tuple(item.requested_setting_names),
            desired_boolean=item.desired_boolean,
            desired_status=item.desired_status,
            finding_code=item.finding_code,
            next_action_code=item.next_action_code,
            requested_at=item.requested_at,
            record_only=True,
            no_execution=True,
            executed=False,
            settings_applied=False,
            owner_approved=False,
            live_action=False,
        )
        for item in listed.requests
    )
    return HandoffSettingsRequestSummary(
        request_count=len(items),
        pending_count=_count_status(items, lambda item: item.decision_status, "pending"),
        approved_count=_count_status(items, lambda item: item.decision_status, "approved"),
        rejected_count=_count_status(items, lambda item: item.decision_status, "rejected"),
        needs_changes_count=_count_status(
            items, lambda item: item.decision_status, "needs_changes"
        ),
        by_request_type=_count_by(items, lambda item: item.request_type),
        by_status=_count_by(items, lambda item: item.request_status),
        by_decision_status=_count_by(items, lambda item: item.decision_status),
        request_ids=tuple(str(item.request_id) for item in items),
        setting_names=_unique_sorted(
            name for item in items for name in item.requested_setting_names
        ),
        record_only=True,
        no_execution=True,
        settings_applied=False,
        owner_approved=False,
        requests=items,
    )


def _preflight_summary(result: SettingsExecutionPreflight) -> HandoffSettingsPreflightSummary:
    items = tuple(
        HandoffSettingsPreflightItem(
            request_id=item.request_id,
            request_type=item.request_type,
            decision_status=item.decision_status,
            execution_status=item.execution_status,
            requested_setting_names=tuple(item.requested_setting_names),
            desired_boolean=item.desired_boolean,
            desired_status=item.desired_status,
            blocker_codes=tuple(item.blocker_codes),
            missing_approval_codes=tuple(item.missing_approval_codes),
            missing_gate_codes=tuple(item.missing_gate_codes),
            missing_credential_names=tuple(item.missing_credential_names),
            closed_provider_flag_names=tuple(item.closed_provider_flag_names),
            requested_at=item.requested_at,
            simulated_at=item.simulated_at,
            no_execution=True,
            dry_run_only=True,
            executed=False,
            settings_applied=False,
            owner_approved=False,
            execution_allowed=False,
            live_action=False,
        )
        for item in result.requests
    )
    return HandoffSettingsPreflightSummary(
        overall_status=result.overall_status,
        request_count=len(items),
        pending_decision_count=result.pending_decision_count,
        approved_decision_count=result.approved_decision_count,
        rejected_or_needs_changes_count=result.rejected_or_needs_changes_count,
        blocked_count=result.blocked_count,
        executable_count=0,
        blocker_codes=tuple(result.blocker_codes),
        missing_approval_codes=tuple(result.missing_approval_codes),
        missing_gate_codes=tuple(result.missing_gate_codes),
        missing_credential_names=tuple(result.missing_credential_names),
        closed_provider_flag_names=tuple(result.closed_provider_flag_names),
        execution_allowed=False,
        future_execution_phase_exists=False,
        dry_run_only=True,
        no_execution=True,
        settings_applied=False,
        owner_approved=False,
        requests=items,
    )


def _packet_summary(db: Session) -> HandoffApprovalPacketSummary:
    rows = tuple(
        db.scalars(
            select(OwnerApprovalPacket).order_by(
                OwnerApprovalPacket.generated_at.desc(),
                OwnerApprovalPacket.id.desc(),
            )
        ).all()
    )
    decisions = {
        row.owner_approval_packet_id: row
        for row in db.scalars(select(OwnerApprovalPacketDecision)).all()
    }
    items = tuple(
        HandoffApprovalPacketItem(
            packet_id=row.id,
            plan_family=row.plan_family,
            preflight_status=row.preflight_status,
            decision_status=(
                decisions[row.id].decision
                if row.id in decisions
                else SettingsChangeDecisionStatus.PENDING.value
            ),
            generated_at=row.generated_at,
            dry_run_only=True,
            no_execution=True,
            executed=False,
            owner_approved=False,
            live_action=False,
        )
        for row in rows
    )
    return HandoffApprovalPacketSummary(
        packet_count=len(items),
        pending_count=_count_status(items, lambda item: item.decision_status, "pending"),
        approved_count=_count_status(items, lambda item: item.decision_status, "approved"),
        rejected_count=_count_status(items, lambda item: item.decision_status, "rejected"),
        needs_changes_count=_count_status(
            items, lambda item: item.decision_status, "needs_changes"
        ),
        by_preflight_status=_count_by(items, lambda item: item.preflight_status),
        by_plan_family=_count_by(items, lambda item: item.plan_family),
        by_decision_status=_count_by(items, lambda item: item.decision_status),
        packet_ids=tuple(str(item.packet_id) for item in items),
        no_execution=True,
        executed=0,
        owner_approved=False,
        live_action=False,
        packets=items,
    )


def _action_readiness_summary(result: ActionReadinessResult) -> HandoffActionReadinessSummary:
    items = tuple(
        HandoffActionReadinessItem(
            candidate_id=item.candidate_id,
            plan_family=item.plan_family,
            readiness_status=item.readiness_status,
            blocker_status=item.blocker_status,
            review_decision_status=item.review_decision_status,
            packet_decision_status=item.packet_decision_status,
            approval_packet_id=item.approval_packet_id,
            blocker_codes=tuple(item.blocker_codes),
            missing_approval_codes=tuple(item.missing_approval_codes),
            missing_prerequisite_codes=tuple(item.missing_prerequisite_codes),
            dry_run_only=True,
            no_execution=True,
            executed=False,
            owner_approved=False,
            live_action=False,
            execution_allowed=False,
        )
        for item in result.candidates
    )
    blocked_count = sum(
        1
        for item in items
        if item.blocker_status == ActionReadinessBlockerStatus.BLOCKED.value
    )
    return HandoffActionReadinessSummary(
        candidate_count=len(items),
        blocked_count=blocked_count,
        by_readiness_status=dict(result.by_readiness_status),
        by_plan_family=dict(result.by_plan_family),
        by_blocker_status=dict(result.by_blocker_status),
        by_decision_status=dict(result.by_decision_status),
        candidate_ids=tuple(str(item.candidate_id) for item in items),
        dry_run_only=True,
        no_execution=True,
        executed_count=0,
        owner_approved=False,
        live_action=False,
        explicit_live_owner_action_required=True,
        candidates=items,
    )


def _remaining_checklist(
    *,
    launch: HandoffLaunchReadinessSummary,
    settings_requests: HandoffSettingsRequestSummary,
    preflight: HandoffSettingsPreflightSummary,
    packets: HandoffApprovalPacketSummary,
    action_readiness: HandoffActionReadinessSummary,
    outbound_enabled: bool,
    live_providers_enabled: bool,
    halt: HaltStatus,
) -> tuple[HandoffChecklistItem, ...]:
    selected: dict[str, HandoffChecklistItem] = {}

    def add(code: str, severity: str, source_section: str, status: str = "open") -> None:
        current = selected.get(code)
        if current is not None and _SEVERITY_RANK.get(current.severity, 0) >= _SEVERITY_RANK.get(
            severity, 0
        ):
            return
        selected[code] = HandoffChecklistItem(
            code=code,
            severity=severity,
            source_section=source_section,
            status=status,
        )

    add(HANDOFF_NOT_GO_LIVE_CODE, FindingSeverity.INFO.value, SECTION_HANDOFF)
    add(EXECUTION_DISABLED_CODE, FindingSeverity.INFO.value, SECTION_HANDOFF)
    for code in launch.next_action_codes:
        severity = FindingSeverity.INFO.value
        if code in launch.blocker_codes or code in {
            NextActionCode.DISABLE_OUTBOUND.value,
            NextActionCode.DISABLE_LIVE_PROVIDERS.value,
            NextActionCode.RECORD_OPERATOR_HALT.value,
            NextActionCode.CONFIGURE_REQUIRED_CREDENTIALS.value,
            NextActionCode.RESTORE_CI_SMOKE_GATE.value,
        }:
            severity = FindingSeverity.BLOCKED.value
        elif code in {
            NextActionCode.KEEP_OPERATOR_HALT.value,
            NextActionCode.OWNER_REVIEW_APPROVAL_PACKETS.value,
            NextActionCode.INSPECT_ACTION_READINESS.value,
            NextActionCode.REVIEW_SETTINGS_CHANGE_REQUESTS.value,
            NextActionCode.INSPECT_SETTINGS_EXECUTION_PREFLIGHT.value,
        }:
            severity = FindingSeverity.WARNING.value
        add(code, severity, SECTION_LAUNCH)
    if settings_requests.pending_count:
        add(
            NextActionCode.REVIEW_SETTINGS_CHANGE_REQUESTS.value,
            FindingSeverity.WARNING.value,
            SECTION_SETTINGS_REQUESTS,
        )
    if preflight.pending_decision_count or preflight.blocked_count:
        add(
            NextActionCode.INSPECT_SETTINGS_EXECUTION_PREFLIGHT.value,
            FindingSeverity.WARNING.value,
            SECTION_SETTINGS_PREFLIGHT,
        )
    if packets.pending_count:
        add(
            NextActionCode.OWNER_REVIEW_APPROVAL_PACKETS.value,
            FindingSeverity.WARNING.value,
            SECTION_PACKETS,
        )
    if action_readiness.blocked_count:
        add(
            NextActionCode.INSPECT_ACTION_READINESS.value,
            FindingSeverity.WARNING.value,
            SECTION_ACTION_READINESS,
        )
    if not outbound_enabled:
        add(
            NextActionCode.KEEP_OUTBOUND_DISABLED.value,
            FindingSeverity.INFO.value,
            SECTION_LAUNCH,
        )
    if not live_providers_enabled:
        add(
            NextActionCode.KEEP_LIVE_PROVIDERS_DISABLED.value,
            FindingSeverity.INFO.value,
            SECTION_LAUNCH,
        )
    match halt:
        case HaltStatus.HALTED:
            add(
                NextActionCode.KEEP_OPERATOR_HALT.value,
                FindingSeverity.WARNING.value,
                SECTION_LAUNCH,
            )
        case HaltStatus.UNAVAILABLE:
            add(
                NextActionCode.RECORD_OPERATOR_HALT.value,
                FindingSeverity.BLOCKED.value,
                SECTION_LAUNCH,
            )
        case HaltStatus.CLEARED:
            pass
        case _:
            _unreachable(halt)
    return tuple(
        sorted(
            selected.values(),
            key=lambda item: (-_SEVERITY_RANK.get(item.severity, 0), item.code),
        )
    )


def _launch_payload(summary: HandoffLaunchReadinessSummary) -> dict[str, Any]:
    return {
        "overall_status": summary.overall_status,
        "operator_halt_status": summary.operator_halt_status,
        "outbound_enabled": summary.outbound_enabled,
        "live_providers_enabled": summary.live_providers_enabled,
        "config_ok": summary.config_ok,
        "ci_smoke_gate_present": summary.ci_smoke_gate_present,
        "ci_smoke_gate_documented": summary.ci_smoke_gate_documented,
        "ci_smoke_gate_job_name": summary.ci_smoke_gate_job_name,
        "pending_owner_approval_packets": summary.pending_owner_approval_packets,
        "action_readiness_candidate_count": summary.action_readiness_candidate_count,
        "action_readiness_blocked_count": summary.action_readiness_blocked_count,
        "pending_settings_change_request_count": summary.pending_settings_change_request_count,
        "finding_codes": list(summary.finding_codes),
        "blocker_codes": list(summary.blocker_codes),
        "next_action_codes": list(summary.next_action_codes),
        "missing_credential_names": list(summary.missing_credential_names),
        "closed_provider_flag_names": list(summary.closed_provider_flag_names),
        "no_execution": True,
        "owner_approved": False,
        "live_action": False,
    }


def _settings_request_payload(summary: HandoffSettingsRequestSummary) -> dict[str, Any]:
    return {
        "request_count": summary.request_count,
        "pending_count": summary.pending_count,
        "approved_count": summary.approved_count,
        "rejected_count": summary.rejected_count,
        "needs_changes_count": summary.needs_changes_count,
        "by_request_type": dict(summary.by_request_type),
        "by_status": dict(summary.by_status),
        "by_decision_status": dict(summary.by_decision_status),
        "request_ids": list(summary.request_ids),
        "setting_names": list(summary.setting_names),
        "record_only": True,
        "no_execution": True,
        "settings_applied": False,
        "owner_approved": False,
        "requests": [
            {
                "request_id": str(item.request_id),
                "request_type": item.request_type,
                "request_status": item.request_status,
                "decision_status": item.decision_status,
                "requested_setting_names": list(item.requested_setting_names),
                "desired_boolean": item.desired_boolean,
                "desired_status": item.desired_status,
                "finding_code": item.finding_code,
                "next_action_code": item.next_action_code,
                "requested_at": item.requested_at.isoformat(),
                "record_only": True,
                "no_execution": True,
                "executed": False,
                "settings_applied": False,
                "owner_approved": False,
                "live_action": False,
            }
            for item in summary.requests
        ],
    }


def _preflight_payload(summary: HandoffSettingsPreflightSummary) -> dict[str, Any]:
    return {
        "overall_status": summary.overall_status,
        "request_count": summary.request_count,
        "pending_decision_count": summary.pending_decision_count,
        "approved_decision_count": summary.approved_decision_count,
        "rejected_or_needs_changes_count": summary.rejected_or_needs_changes_count,
        "blocked_count": summary.blocked_count,
        "executable_count": 0,
        "blocker_codes": list(summary.blocker_codes),
        "missing_approval_codes": list(summary.missing_approval_codes),
        "missing_gate_codes": list(summary.missing_gate_codes),
        "missing_credential_names": list(summary.missing_credential_names),
        "closed_provider_flag_names": list(summary.closed_provider_flag_names),
        "execution_allowed": False,
        "future_execution_phase_exists": False,
        "dry_run_only": True,
        "no_execution": True,
        "settings_applied": False,
        "owner_approved": False,
        "requests": [
            {
                "request_id": str(item.request_id),
                "request_type": item.request_type,
                "decision_status": item.decision_status,
                "execution_status": item.execution_status,
                "requested_setting_names": list(item.requested_setting_names),
                "desired_boolean": item.desired_boolean,
                "desired_status": item.desired_status,
                "blocker_codes": list(item.blocker_codes),
                "missing_approval_codes": list(item.missing_approval_codes),
                "missing_gate_codes": list(item.missing_gate_codes),
                "missing_credential_names": list(item.missing_credential_names),
                "closed_provider_flag_names": list(item.closed_provider_flag_names),
                "requested_at": item.requested_at.isoformat(),
                "simulated_at": item.simulated_at.isoformat(),
                "no_execution": True,
                "dry_run_only": True,
                "executed": False,
                "settings_applied": False,
                "owner_approved": False,
                "execution_allowed": False,
                "live_action": False,
            }
            for item in summary.requests
        ],
    }


def _packet_payload(summary: HandoffApprovalPacketSummary) -> dict[str, Any]:
    return {
        "packet_count": summary.packet_count,
        "pending_count": summary.pending_count,
        "approved_count": summary.approved_count,
        "rejected_count": summary.rejected_count,
        "needs_changes_count": summary.needs_changes_count,
        "by_preflight_status": dict(summary.by_preflight_status),
        "by_plan_family": dict(summary.by_plan_family),
        "by_decision_status": dict(summary.by_decision_status),
        "packet_ids": list(summary.packet_ids),
        "no_execution": True,
        "executed": 0,
        "owner_approved": False,
        "live_action": False,
        "packets": [
            {
                "packet_id": str(item.packet_id),
                "plan_family": item.plan_family,
                "preflight_status": item.preflight_status,
                "decision_status": item.decision_status,
                "generated_at": item.generated_at.isoformat(),
                "dry_run_only": True,
                "no_execution": True,
                "executed": False,
                "owner_approved": False,
                "live_action": False,
            }
            for item in summary.packets
        ],
    }


def _action_payload(summary: HandoffActionReadinessSummary) -> dict[str, Any]:
    return {
        "candidate_count": summary.candidate_count,
        "blocked_count": summary.blocked_count,
        "by_readiness_status": dict(summary.by_readiness_status),
        "by_plan_family": dict(summary.by_plan_family),
        "by_blocker_status": dict(summary.by_blocker_status),
        "by_decision_status": dict(summary.by_decision_status),
        "candidate_ids": list(summary.candidate_ids),
        "dry_run_only": True,
        "no_execution": True,
        "executed_count": 0,
        "owner_approved": False,
        "live_action": False,
        "explicit_live_owner_action_required": True,
        "candidates": [
            {
                "candidate_id": str(item.candidate_id),
                "plan_family": item.plan_family,
                "readiness_status": item.readiness_status,
                "blocker_status": item.blocker_status,
                "review_decision_status": item.review_decision_status,
                "packet_decision_status": item.packet_decision_status,
                "approval_packet_id": (
                    str(item.approval_packet_id) if item.approval_packet_id is not None else None
                ),
                "blocker_codes": list(item.blocker_codes),
                "missing_approval_codes": list(item.missing_approval_codes),
                "missing_prerequisite_codes": list(item.missing_prerequisite_codes),
                "dry_run_only": True,
                "no_execution": True,
                "executed": False,
                "owner_approved": False,
                "live_action": False,
                "execution_allowed": False,
            }
            for item in summary.candidates
        ],
    }


def _format_markdown(packet: OwnerHandoffPacket, payload: dict[str, Any]) -> str:
    lines = [
        "# Owner go-live handoff packet",
        "",
        "This packet is for manual owner review only. It is not permission or "
        "machinery for going live.",
        "",
        f"- overall: {payload['overall_status']}",
        f"- packet_kind: {payload['packet_kind']}",
        f"- purpose: {payload['purpose']}",
        f"- read_only: {_bool_text(payload['read_only'])}",
        f"- no_execution: {_bool_text(payload['no_execution'])}",
        f"- dry_run_only: {_bool_text(payload['dry_run_only'])}",
        f"- executed: {payload['executed']}",
        f"- owner_approved: {_bool_text(payload['owner_approved'])}",
        f"- settings_applied: {_bool_text(payload['settings_applied'])}",
        f"- halt_changed: {_bool_text(payload['halt_changed'])}",
        f"- live_action: {_bool_text(payload['live_action'])}",
        f"- execution_allowed: {_bool_text(payload['execution_allowed'])}",
        f"- go_live_permitted: {_bool_text(payload['go_live_permitted'])}",
        f"- future_execution_phase_exists: {_bool_text(payload['future_execution_phase_exists'])}",
        (
            "- operator_halt: "
            f"status={payload['operator_halt_status']} "
            f"before={payload['operator_halt_before']} "
            f"after={payload['operator_halt_after']}"
        ),
        f"- outbound_enabled: {_bool_text(payload['outbound_enabled'])}",
        f"- live_providers_enabled: {_bool_text(payload['live_providers_enabled'])}",
        f"- blocker_codes: {_format_codes(packet.blocker_codes)}",
        f"- missing_credential_names: {_format_codes(packet.missing_credential_names)}",
        f"- closed_provider_flag_names: {_format_codes(packet.closed_provider_flag_names)}",
        "",
        "## Launch readiness summary",
        f"- overall: {packet.launch_readiness.overall_status}",
        f"- operator_halt: {packet.launch_readiness.operator_halt_status}",
        f"- outbound_enabled: {_bool_text(packet.launch_readiness.outbound_enabled)}",
        (
            "- live_providers_enabled: "
            f"{_bool_text(packet.launch_readiness.live_providers_enabled)}"
        ),
        f"- config_ok: {_bool_text(packet.launch_readiness.config_ok)}",
        (
            "- ci_smoke_gate: "
            f"present={_bool_text(packet.launch_readiness.ci_smoke_gate_present)} "
            f"documented={_bool_text(packet.launch_readiness.ci_smoke_gate_documented)} "
            f"job={packet.launch_readiness.ci_smoke_gate_job_name}"
        ),
        (
            "- pending_owner_approval_packets: "
            f"{packet.launch_readiness.pending_owner_approval_packets}"
        ),
        (
            "- action_readiness: "
            f"candidates={packet.launch_readiness.action_readiness_candidate_count} "
            f"blocked={packet.launch_readiness.action_readiness_blocked_count}"
        ),
        (
            "- pending_settings_change_requests: "
            f"{packet.launch_readiness.pending_settings_change_request_count}"
        ),
        f"- finding_codes: {_format_codes(packet.launch_readiness.finding_codes)}",
        f"- blocker_codes: {_format_codes(packet.launch_readiness.blocker_codes)}",
        f"- next_action_codes: {_format_codes(packet.launch_readiness.next_action_codes)}",
        (
            "- missing_credential_names: "
            f"{_format_codes(packet.launch_readiness.missing_credential_names)}"
        ),
        (
            "- closed_provider_flag_names: "
            f"{_format_codes(packet.launch_readiness.closed_provider_flag_names)}"
        ),
        f"- no_execution: {_bool_text(packet.launch_readiness.no_execution)}",
        "",
        "## Settings change request summary",
        f"- requests: {packet.settings_change_requests.request_count}",
        f"- pending: {packet.settings_change_requests.pending_count}",
        f"- approved: {packet.settings_change_requests.approved_count}",
        f"- rejected: {packet.settings_change_requests.rejected_count}",
        f"- needs_changes: {packet.settings_change_requests.needs_changes_count}",
        f"- request_ids: {_format_codes(packet.settings_change_requests.request_ids)}",
        f"- setting_names: {_format_codes(packet.settings_change_requests.setting_names)}",
        f"- no_execution: {_bool_text(packet.settings_change_requests.no_execution)}",
        f"- settings_applied: {_bool_text(packet.settings_change_requests.settings_applied)}",
    ]
    for request_item in packet.settings_change_requests.requests:
        lines.append(_format_settings_request_line(request_item))
    lines.extend(
        [
            "",
            "## Settings execution preflight summary",
            f"- overall: {packet.settings_execution_preflight.overall_status}",
            f"- requests: {packet.settings_execution_preflight.request_count}",
            f"- pending_decisions: {packet.settings_execution_preflight.pending_decision_count}",
            (
                "- approved_decisions: "
                f"{packet.settings_execution_preflight.approved_decision_count}"
            ),
            f"- blocked: {packet.settings_execution_preflight.blocked_count}",
            f"- executable: {packet.settings_execution_preflight.executable_count}",
            (
                "- blocker_codes: "
                f"{_format_codes(packet.settings_execution_preflight.blocker_codes)}"
            ),
            (
                "- missing_approval_codes: "
                f"{_format_codes(packet.settings_execution_preflight.missing_approval_codes)}"
            ),
            (
                "- missing_gate_codes: "
                f"{_format_codes(packet.settings_execution_preflight.missing_gate_codes)}"
            ),
            (
                "- missing_credential_names: "
                f"{_format_codes(packet.settings_execution_preflight.missing_credential_names)}"
            ),
            (
                "- closed_provider_flag_names: "
                f"{_format_codes(packet.settings_execution_preflight.closed_provider_flag_names)}"
            ),
            (
                "- execution_allowed: "
                f"{_bool_text(packet.settings_execution_preflight.execution_allowed)}"
            ),
            f"- no_execution: {_bool_text(packet.settings_execution_preflight.no_execution)}",
        ]
    )
    for preflight_item in packet.settings_execution_preflight.requests:
        lines.append(_format_preflight_line(preflight_item))
    lines.extend(
        [
            "",
            "## Owner approval packet summary",
            f"- packets: {packet.owner_approval_packets.packet_count}",
            f"- pending: {packet.owner_approval_packets.pending_count}",
            f"- approved: {packet.owner_approval_packets.approved_count}",
            f"- rejected: {packet.owner_approval_packets.rejected_count}",
            f"- needs_changes: {packet.owner_approval_packets.needs_changes_count}",
            f"- packet_ids: {_format_codes(packet.owner_approval_packets.packet_ids)}",
            f"- no_execution: {_bool_text(packet.owner_approval_packets.no_execution)}",
            f"- executed: {packet.owner_approval_packets.executed}",
            f"- owner_approved: {_bool_text(packet.owner_approval_packets.owner_approved)}",
        ]
    )
    for packet_item in packet.owner_approval_packets.packets:
        lines.append(
            "- packet: "
            f"id={packet_item.packet_id} "
            f"plan_family={packet_item.plan_family} "
            f"preflight={packet_item.preflight_status} "
            f"decision={packet_item.decision_status} "
            f"executed={_bool_text(packet_item.executed)} "
            f"owner_approved={_bool_text(packet_item.owner_approved)} "
            f"no_execution={_bool_text(packet_item.no_execution)}"
        )
    lines.extend(
        [
            "",
            "## Approved action readiness summary",
            f"- candidates: {packet.approved_action_readiness.candidate_count}",
            f"- blocked: {packet.approved_action_readiness.blocked_count}",
            f"- candidate_ids: {_format_codes(packet.approved_action_readiness.candidate_ids)}",
            f"- no_execution: {_bool_text(packet.approved_action_readiness.no_execution)}",
            f"- executed: {packet.approved_action_readiness.executed_count}",
            (
                "- explicit_live_owner_action_required: "
                f"{_bool_text(packet.approved_action_readiness.explicit_live_owner_action_required)}"
            ),
        ]
    )
    for candidate in packet.approved_action_readiness.candidates:
        lines.append(
            "- candidate: "
            f"id={candidate.candidate_id} "
            f"plan_family={candidate.plan_family} "
            f"readiness={candidate.readiness_status} "
            f"blocker={candidate.blocker_status} "
            f"review={candidate.review_decision_status} "
            f"packet_decision={candidate.packet_decision_status} "
            f"packet_id={candidate.approval_packet_id or '-'} "
            f"blockers={_format_codes(candidate.blocker_codes)} "
            f"executed={_bool_text(candidate.executed)} "
            f"execution_allowed={_bool_text(candidate.execution_allowed)} "
            f"no_execution={_bool_text(candidate.no_execution)}"
        )
    lines.extend(["", "## Remaining manual owner checklist"])
    for checklist_item in packet.remaining_manual_owner_checklist:
        lines.append(
            f"- [{checklist_item.status}] {checklist_item.code} "
            f"severity={checklist_item.severity} source={checklist_item.source_section}"
        )
    return "\n".join(lines)


def _format_settings_request_line(item: HandoffSettingsRequestItem) -> str:
    names = ",".join(item.requested_setting_names) or "-"
    desired = "null" if item.desired_boolean is None else _bool_text(item.desired_boolean)
    return (
        "- request: "
        f"id={item.request_id} "
        f"type={item.request_type} "
        f"status={item.request_status} "
        f"decision={item.decision_status} "
        f"settings={names} "
        f"desired_boolean={desired} "
        f"desired_status={item.desired_status or '-'} "
        f"executed={_bool_text(item.executed)} "
        f"settings_applied={_bool_text(item.settings_applied)} "
        f"no_execution={_bool_text(item.no_execution)}"
    )


def _format_preflight_line(item: HandoffSettingsPreflightItem) -> str:
    names = ",".join(item.requested_setting_names) or "-"
    desired = "null" if item.desired_boolean is None else _bool_text(item.desired_boolean)
    return (
        "- request: "
        f"id={item.request_id} "
        f"type={item.request_type} "
        f"decision={item.decision_status} "
        f"execution={item.execution_status} "
        f"settings={names} "
        f"desired_boolean={desired} "
        f"desired_status={item.desired_status or '-'} "
        f"blockers={_format_codes(item.blocker_codes)} "
        f"gates={_format_codes(item.missing_gate_codes)} "
        f"executed={_bool_text(item.executed)} "
        f"execution_allowed={_bool_text(item.execution_allowed)} "
        f"no_execution={_bool_text(item.no_execution)}"
    )


def _format_codes(values: Sequence[str]) -> str:
    return ",".join(values) if values else "-"


def _unique_sorted(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(sorted(set(values)))


def _count_by(items: Sequence[Any], key: Callable[[Any], str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        value = str(key(item))
        counts[value] = counts.get(value, 0) + 1
    return counts


def _count_status(items: Sequence[Any], key: Callable[[Any], str], status: str) -> int:
    return sum(1 for item in items if key(item) == status)


def _bool_text(value: object) -> str:
    return "true" if value else "false"


def _unreachable(value: object) -> Never:
    raise RuntimeError(f"unhandled owner handoff variant: {value!r}")
