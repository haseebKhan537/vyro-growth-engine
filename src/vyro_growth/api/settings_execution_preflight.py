from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from vyro_growth.config import Settings
from vyro_growth.services.settings_execution_preflight import (
    SettingsExecutionPreflight,
    SettingsExecutionPreflightFilters,
    SettingsExecutionPreflightItem,
    SettingsExecutionPreflightService,
)


class SettingsExecutionPreflightItemResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: UUID
    request_type: str
    request_status: str
    decision_status: str
    requested_setting_names: list[str] = Field(default_factory=list)
    desired_boolean: bool | None = None
    desired_status: str | None = None
    execution_status: str
    blocker_codes: list[str] = Field(default_factory=list)
    missing_approval_codes: list[str] = Field(default_factory=list)
    missing_gate_codes: list[str] = Field(default_factory=list)
    missing_credential_names: list[str] = Field(default_factory=list)
    closed_provider_flag_names: list[str] = Field(default_factory=list)
    requested_at: datetime
    simulated_at: datetime
    record_only: bool = True
    no_execution: bool = True
    dry_run_only: bool = True
    executed: bool = False
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


class SettingsExecutionPreflightResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    generated_at: datetime
    overall_status: str
    request_count: int = 0
    pending_decision_count: int = 0
    approved_decision_count: int = 0
    rejected_or_needs_changes_count: int = 0
    blocked_count: int = 0
    executable_count: int = 0
    by_request_type: dict[str, int] = Field(default_factory=dict)
    by_decision_status: dict[str, int] = Field(default_factory=dict)
    by_execution_status: dict[str, int] = Field(default_factory=dict)
    blocker_codes: list[str] = Field(default_factory=list)
    missing_approval_codes: list[str] = Field(default_factory=list)
    missing_gate_codes: list[str] = Field(default_factory=list)
    missing_credential_names: list[str] = Field(default_factory=list)
    closed_provider_flag_names: list[str] = Field(default_factory=list)
    record_only: bool = True
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
    outbound_enabled: bool = False
    live_providers_enabled: bool = False
    operator_halt_status: str
    operator_halt_before: str
    operator_halt_after: str
    pending_owner_approval_packet_count: int = 0
    approved_owner_approval_packet_count: int = 0
    requests: list[SettingsExecutionPreflightItemResponse] = Field(default_factory=list)


def item_to_response(
    item: SettingsExecutionPreflightItem,
) -> SettingsExecutionPreflightItemResponse:
    return SettingsExecutionPreflightItemResponse(
        request_id=item.request_id,
        request_type=item.request_type,
        request_status=item.request_status,
        decision_status=item.decision_status,
        requested_setting_names=list(item.requested_setting_names),
        desired_boolean=item.desired_boolean,
        desired_status=item.desired_status,
        execution_status=item.execution_status,
        blocker_codes=list(item.blocker_codes),
        missing_approval_codes=list(item.missing_approval_codes),
        missing_gate_codes=list(item.missing_gate_codes),
        missing_credential_names=list(item.missing_credential_names),
        closed_provider_flag_names=list(item.closed_provider_flag_names),
        requested_at=item.requested_at,
        simulated_at=item.simulated_at,
        record_only=True,
        no_execution=True,
        dry_run_only=True,
        executed=False,
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
    )


def preflight_to_response(
    result: SettingsExecutionPreflight,
) -> SettingsExecutionPreflightResponse:
    return SettingsExecutionPreflightResponse(
        generated_at=result.generated_at,
        overall_status=result.overall_status,
        request_count=result.request_count,
        pending_decision_count=result.pending_decision_count,
        approved_decision_count=result.approved_decision_count,
        rejected_or_needs_changes_count=result.rejected_or_needs_changes_count,
        blocked_count=result.blocked_count,
        executable_count=0,
        by_request_type=dict(result.by_request_type),
        by_decision_status=dict(result.by_decision_status),
        by_execution_status=dict(result.by_execution_status),
        blocker_codes=list(result.blocker_codes),
        missing_approval_codes=list(result.missing_approval_codes),
        missing_gate_codes=list(result.missing_gate_codes),
        missing_credential_names=list(result.missing_credential_names),
        closed_provider_flag_names=list(result.closed_provider_flag_names),
        record_only=True,
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
        outbound_enabled=result.outbound_enabled,
        live_providers_enabled=result.live_providers_enabled,
        operator_halt_status=result.operator_halt_status,
        operator_halt_before=result.operator_halt_before,
        operator_halt_after=result.operator_halt_after,
        pending_owner_approval_packet_count=result.pending_owner_approval_packet_count,
        approved_owner_approval_packet_count=result.approved_owner_approval_packet_count,
        requests=[item_to_response(item) for item in result.requests],
    )


def build_settings_execution_preflight_response(
    db: Session,
    settings: Settings,
    *,
    request_type: str | None = None,
    decision_status: str | None = None,
    execution_status: str | None = None,
    service: SettingsExecutionPreflightService | None = None,
) -> SettingsExecutionPreflightResponse:
    simulator = service or SettingsExecutionPreflightService()
    return preflight_to_response(
        simulator.simulate(
            db,
            settings,
            filters=SettingsExecutionPreflightFilters(
                request_type=request_type,
                decision_status=decision_status,
                execution_status=execution_status,
            ),
        )
    )
