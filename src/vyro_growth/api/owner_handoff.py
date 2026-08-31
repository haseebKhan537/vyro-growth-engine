from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from vyro_growth.config import Settings
from vyro_growth.services.owner_handoff import (
    HandoffActionReadinessItem,
    HandoffActionReadinessSummary,
    HandoffApprovalPacketItem,
    HandoffApprovalPacketSummary,
    HandoffChecklistItem,
    HandoffLaunchReadinessSummary,
    HandoffSettingsPreflightItem,
    HandoffSettingsPreflightSummary,
    HandoffSettingsRequestItem,
    HandoffSettingsRequestSummary,
    OwnerHandoffPacket,
    OwnerHandoffPacketService,
)


class HandoffLaunchReadinessResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    overall_status: str
    operator_halt_status: str
    outbound_enabled: bool = False
    live_providers_enabled: bool = False
    config_ok: bool = False
    ci_smoke_gate_present: bool = False
    ci_smoke_gate_documented: bool = False
    ci_smoke_gate_job_name: str
    pending_owner_approval_packets: int = 0
    action_readiness_candidate_count: int = 0
    action_readiness_blocked_count: int = 0
    pending_settings_change_request_count: int = 0
    finding_codes: list[str] = Field(default_factory=list)
    blocker_codes: list[str] = Field(default_factory=list)
    next_action_codes: list[str] = Field(default_factory=list)
    missing_credential_names: list[str] = Field(default_factory=list)
    closed_provider_flag_names: list[str] = Field(default_factory=list)
    no_execution: bool = True
    owner_approved: bool = False
    live_action: bool = False


class HandoffSettingsRequestItemResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: UUID
    request_type: str
    request_status: str
    decision_status: str
    requested_setting_names: list[str] = Field(default_factory=list)
    desired_boolean: bool | None = None
    desired_status: str | None = None
    finding_code: str | None = None
    next_action_code: str | None = None
    requested_at: datetime
    record_only: bool = True
    no_execution: bool = True
    executed: bool = False
    settings_applied: bool = False
    owner_approved: bool = False
    live_action: bool = False


class HandoffSettingsRequestSummaryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_count: int = 0
    pending_count: int = 0
    approved_count: int = 0
    rejected_count: int = 0
    needs_changes_count: int = 0
    by_request_type: dict[str, int] = Field(default_factory=dict)
    by_status: dict[str, int] = Field(default_factory=dict)
    by_decision_status: dict[str, int] = Field(default_factory=dict)
    request_ids: list[str] = Field(default_factory=list)
    setting_names: list[str] = Field(default_factory=list)
    record_only: bool = True
    no_execution: bool = True
    settings_applied: bool = False
    owner_approved: bool = False
    requests: list[HandoffSettingsRequestItemResponse] = Field(default_factory=list)


class HandoffSettingsPreflightItemResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: UUID
    request_type: str
    decision_status: str
    execution_status: str
    requested_setting_names: list[str] = Field(default_factory=list)
    desired_boolean: bool | None = None
    desired_status: str | None = None
    blocker_codes: list[str] = Field(default_factory=list)
    missing_approval_codes: list[str] = Field(default_factory=list)
    missing_gate_codes: list[str] = Field(default_factory=list)
    missing_credential_names: list[str] = Field(default_factory=list)
    closed_provider_flag_names: list[str] = Field(default_factory=list)
    requested_at: datetime
    simulated_at: datetime
    no_execution: bool = True
    dry_run_only: bool = True
    executed: bool = False
    settings_applied: bool = False
    owner_approved: bool = False
    execution_allowed: bool = False
    live_action: bool = False


class HandoffSettingsPreflightSummaryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    overall_status: str
    request_count: int = 0
    pending_decision_count: int = 0
    approved_decision_count: int = 0
    rejected_or_needs_changes_count: int = 0
    blocked_count: int = 0
    executable_count: int = 0
    blocker_codes: list[str] = Field(default_factory=list)
    missing_approval_codes: list[str] = Field(default_factory=list)
    missing_gate_codes: list[str] = Field(default_factory=list)
    missing_credential_names: list[str] = Field(default_factory=list)
    closed_provider_flag_names: list[str] = Field(default_factory=list)
    execution_allowed: bool = False
    future_execution_phase_exists: bool = False
    dry_run_only: bool = True
    no_execution: bool = True
    settings_applied: bool = False
    owner_approved: bool = False
    requests: list[HandoffSettingsPreflightItemResponse] = Field(default_factory=list)


class HandoffApprovalPacketItemResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    packet_id: UUID
    plan_family: str
    preflight_status: str
    decision_status: str
    generated_at: datetime
    dry_run_only: bool = True
    no_execution: bool = True
    executed: bool = False
    owner_approved: bool = False
    live_action: bool = False


class HandoffApprovalPacketSummaryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    packet_count: int = 0
    pending_count: int = 0
    approved_count: int = 0
    rejected_count: int = 0
    needs_changes_count: int = 0
    by_preflight_status: dict[str, int] = Field(default_factory=dict)
    by_plan_family: dict[str, int] = Field(default_factory=dict)
    by_decision_status: dict[str, int] = Field(default_factory=dict)
    packet_ids: list[str] = Field(default_factory=list)
    no_execution: bool = True
    executed: int = 0
    owner_approved: bool = False
    live_action: bool = False
    packets: list[HandoffApprovalPacketItemResponse] = Field(default_factory=list)


class HandoffActionReadinessItemResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: UUID
    plan_family: str
    readiness_status: str
    blocker_status: str
    review_decision_status: str
    packet_decision_status: str
    approval_packet_id: UUID | None = None
    blocker_codes: list[str] = Field(default_factory=list)
    missing_approval_codes: list[str] = Field(default_factory=list)
    missing_prerequisite_codes: list[str] = Field(default_factory=list)
    dry_run_only: bool = True
    no_execution: bool = True
    executed: bool = False
    owner_approved: bool = False
    live_action: bool = False
    execution_allowed: bool = False


class HandoffActionReadinessSummaryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_count: int = 0
    blocked_count: int = 0
    by_readiness_status: dict[str, int] = Field(default_factory=dict)
    by_plan_family: dict[str, int] = Field(default_factory=dict)
    by_blocker_status: dict[str, int] = Field(default_factory=dict)
    by_decision_status: dict[str, int] = Field(default_factory=dict)
    candidate_ids: list[str] = Field(default_factory=list)
    dry_run_only: bool = True
    no_execution: bool = True
    executed_count: int = 0
    owner_approved: bool = False
    live_action: bool = False
    explicit_live_owner_action_required: bool = True
    candidates: list[HandoffActionReadinessItemResponse] = Field(default_factory=list)


class HandoffChecklistItemResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    severity: str
    source_section: str
    status: str


class OwnerHandoffPacketResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    generated_at: datetime
    packet_kind: str = "owner_go_live_handoff"
    purpose: str = "manual_owner_review_only"
    overall_status: str
    read_only: bool = True
    no_execution: bool = True
    dry_run_only: bool = True
    executed: int = 0
    execution_attempted: bool = False
    outbound_attempted: bool = False
    live_call_attempted: bool = False
    recommendation_applied: bool = False
    spend_attempted: bool = False
    campaign_launched: bool = False
    pages_published: bool = False
    ads_launched: bool = False
    owner_approved: bool = False
    settings_applied: bool = False
    halt_changed: bool = False
    live_action: bool = False
    execution_allowed: bool = False
    future_execution_phase_exists: bool = False
    go_live_permitted: bool = False
    manual_review_only: bool = True
    operator_halt_status: str
    operator_halt_before: str
    operator_halt_after: str
    outbound_enabled: bool = False
    live_providers_enabled: bool = False
    blocker_codes: list[str] = Field(default_factory=list)
    missing_credential_names: list[str] = Field(default_factory=list)
    closed_provider_flag_names: list[str] = Field(default_factory=list)
    launch_readiness: HandoffLaunchReadinessResponse
    settings_change_requests: HandoffSettingsRequestSummaryResponse
    settings_execution_preflight: HandoffSettingsPreflightSummaryResponse
    owner_approval_packets: HandoffApprovalPacketSummaryResponse
    approved_action_readiness: HandoffActionReadinessSummaryResponse
    remaining_manual_owner_checklist: list[HandoffChecklistItemResponse] = Field(
        default_factory=list
    )


def _launch_to_response(
    summary: HandoffLaunchReadinessSummary,
) -> HandoffLaunchReadinessResponse:
    return HandoffLaunchReadinessResponse(
        overall_status=summary.overall_status,
        operator_halt_status=summary.operator_halt_status,
        outbound_enabled=summary.outbound_enabled,
        live_providers_enabled=summary.live_providers_enabled,
        config_ok=summary.config_ok,
        ci_smoke_gate_present=summary.ci_smoke_gate_present,
        ci_smoke_gate_documented=summary.ci_smoke_gate_documented,
        ci_smoke_gate_job_name=summary.ci_smoke_gate_job_name,
        pending_owner_approval_packets=summary.pending_owner_approval_packets,
        action_readiness_candidate_count=summary.action_readiness_candidate_count,
        action_readiness_blocked_count=summary.action_readiness_blocked_count,
        pending_settings_change_request_count=summary.pending_settings_change_request_count,
        finding_codes=list(summary.finding_codes),
        blocker_codes=list(summary.blocker_codes),
        next_action_codes=list(summary.next_action_codes),
        missing_credential_names=list(summary.missing_credential_names),
        closed_provider_flag_names=list(summary.closed_provider_flag_names),
        no_execution=True,
        owner_approved=False,
        live_action=False,
    )


def _settings_request_item_to_response(
    item: HandoffSettingsRequestItem,
) -> HandoffSettingsRequestItemResponse:
    return HandoffSettingsRequestItemResponse(
        request_id=item.request_id,
        request_type=item.request_type,
        request_status=item.request_status,
        decision_status=item.decision_status,
        requested_setting_names=list(item.requested_setting_names),
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


def _settings_request_to_response(
    summary: HandoffSettingsRequestSummary,
) -> HandoffSettingsRequestSummaryResponse:
    return HandoffSettingsRequestSummaryResponse(
        request_count=summary.request_count,
        pending_count=summary.pending_count,
        approved_count=summary.approved_count,
        rejected_count=summary.rejected_count,
        needs_changes_count=summary.needs_changes_count,
        by_request_type=dict(summary.by_request_type),
        by_status=dict(summary.by_status),
        by_decision_status=dict(summary.by_decision_status),
        request_ids=list(summary.request_ids),
        setting_names=list(summary.setting_names),
        record_only=True,
        no_execution=True,
        settings_applied=False,
        owner_approved=False,
        requests=[_settings_request_item_to_response(item) for item in summary.requests],
    )


def _preflight_item_to_response(
    item: HandoffSettingsPreflightItem,
) -> HandoffSettingsPreflightItemResponse:
    return HandoffSettingsPreflightItemResponse(
        request_id=item.request_id,
        request_type=item.request_type,
        decision_status=item.decision_status,
        execution_status=item.execution_status,
        requested_setting_names=list(item.requested_setting_names),
        desired_boolean=item.desired_boolean,
        desired_status=item.desired_status,
        blocker_codes=list(item.blocker_codes),
        missing_approval_codes=list(item.missing_approval_codes),
        missing_gate_codes=list(item.missing_gate_codes),
        missing_credential_names=list(item.missing_credential_names),
        closed_provider_flag_names=list(item.closed_provider_flag_names),
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


def _preflight_to_response(
    summary: HandoffSettingsPreflightSummary,
) -> HandoffSettingsPreflightSummaryResponse:
    return HandoffSettingsPreflightSummaryResponse(
        overall_status=summary.overall_status,
        request_count=summary.request_count,
        pending_decision_count=summary.pending_decision_count,
        approved_decision_count=summary.approved_decision_count,
        rejected_or_needs_changes_count=summary.rejected_or_needs_changes_count,
        blocked_count=summary.blocked_count,
        executable_count=0,
        blocker_codes=list(summary.blocker_codes),
        missing_approval_codes=list(summary.missing_approval_codes),
        missing_gate_codes=list(summary.missing_gate_codes),
        missing_credential_names=list(summary.missing_credential_names),
        closed_provider_flag_names=list(summary.closed_provider_flag_names),
        execution_allowed=False,
        future_execution_phase_exists=False,
        dry_run_only=True,
        no_execution=True,
        settings_applied=False,
        owner_approved=False,
        requests=[_preflight_item_to_response(item) for item in summary.requests],
    )


def _packet_item_to_response(
    item: HandoffApprovalPacketItem,
) -> HandoffApprovalPacketItemResponse:
    return HandoffApprovalPacketItemResponse(
        packet_id=item.packet_id,
        plan_family=item.plan_family,
        preflight_status=item.preflight_status,
        decision_status=item.decision_status,
        generated_at=item.generated_at,
        dry_run_only=True,
        no_execution=True,
        executed=False,
        owner_approved=False,
        live_action=False,
    )


def _packets_to_response(
    summary: HandoffApprovalPacketSummary,
) -> HandoffApprovalPacketSummaryResponse:
    return HandoffApprovalPacketSummaryResponse(
        packet_count=summary.packet_count,
        pending_count=summary.pending_count,
        approved_count=summary.approved_count,
        rejected_count=summary.rejected_count,
        needs_changes_count=summary.needs_changes_count,
        by_preflight_status=dict(summary.by_preflight_status),
        by_plan_family=dict(summary.by_plan_family),
        by_decision_status=dict(summary.by_decision_status),
        packet_ids=list(summary.packet_ids),
        no_execution=True,
        executed=0,
        owner_approved=False,
        live_action=False,
        packets=[_packet_item_to_response(item) for item in summary.packets],
    )


def _action_item_to_response(
    item: HandoffActionReadinessItem,
) -> HandoffActionReadinessItemResponse:
    return HandoffActionReadinessItemResponse(
        candidate_id=item.candidate_id,
        plan_family=item.plan_family,
        readiness_status=item.readiness_status,
        blocker_status=item.blocker_status,
        review_decision_status=item.review_decision_status,
        packet_decision_status=item.packet_decision_status,
        approval_packet_id=item.approval_packet_id,
        blocker_codes=list(item.blocker_codes),
        missing_approval_codes=list(item.missing_approval_codes),
        missing_prerequisite_codes=list(item.missing_prerequisite_codes),
        dry_run_only=True,
        no_execution=True,
        executed=False,
        owner_approved=False,
        live_action=False,
        execution_allowed=False,
    )


def _action_to_response(
    summary: HandoffActionReadinessSummary,
) -> HandoffActionReadinessSummaryResponse:
    return HandoffActionReadinessSummaryResponse(
        candidate_count=summary.candidate_count,
        blocked_count=summary.blocked_count,
        by_readiness_status=dict(summary.by_readiness_status),
        by_plan_family=dict(summary.by_plan_family),
        by_blocker_status=dict(summary.by_blocker_status),
        by_decision_status=dict(summary.by_decision_status),
        candidate_ids=list(summary.candidate_ids),
        dry_run_only=True,
        no_execution=True,
        executed_count=0,
        owner_approved=False,
        live_action=False,
        explicit_live_owner_action_required=True,
        candidates=[_action_item_to_response(item) for item in summary.candidates],
    )


def _checklist_to_response(item: HandoffChecklistItem) -> HandoffChecklistItemResponse:
    return HandoffChecklistItemResponse(
        code=item.code,
        severity=item.severity,
        source_section=item.source_section,
        status=item.status,
    )


def packet_to_response(packet: OwnerHandoffPacket) -> OwnerHandoffPacketResponse:
    return OwnerHandoffPacketResponse(
        generated_at=packet.generated_at,
        packet_kind="owner_go_live_handoff",
        purpose="manual_owner_review_only",
        overall_status=packet.overall_status,
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
        operator_halt_status=packet.operator_halt_status,
        operator_halt_before=packet.operator_halt_before,
        operator_halt_after=packet.operator_halt_after,
        outbound_enabled=packet.outbound_enabled,
        live_providers_enabled=packet.live_providers_enabled,
        blocker_codes=list(packet.blocker_codes),
        missing_credential_names=list(packet.missing_credential_names),
        closed_provider_flag_names=list(packet.closed_provider_flag_names),
        launch_readiness=_launch_to_response(packet.launch_readiness),
        settings_change_requests=_settings_request_to_response(packet.settings_change_requests),
        settings_execution_preflight=_preflight_to_response(packet.settings_execution_preflight),
        owner_approval_packets=_packets_to_response(packet.owner_approval_packets),
        approved_action_readiness=_action_to_response(packet.approved_action_readiness),
        remaining_manual_owner_checklist=[
            _checklist_to_response(item) for item in packet.remaining_manual_owner_checklist
        ],
    )


def build_owner_handoff_response(
    db: Session,
    settings: Settings,
    *,
    service: OwnerHandoffPacketService | None = None,
) -> OwnerHandoffPacketResponse:
    builder = service or OwnerHandoffPacketService()
    return packet_to_response(builder.build(db, settings))
