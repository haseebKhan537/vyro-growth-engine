from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from vyro_growth.config import Settings
from vyro_growth.services.launch_readiness import (
    CiSmokeGateStatus,
    ConfigFlagStatus,
    LaunchReadinessChecklist,
    LaunchReadinessFinding,
    LaunchReadinessService,
    SecretInventoryItem,
)


class SecretInventoryItemResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    present: bool
    status: str
    required: bool = False


class ConfigFlagStatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    enabled: bool


class CiSmokeGateStatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    present: bool
    documented: bool
    job_name: str


class LaunchReadinessFindingResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    severity: str
    code: str
    next_action_code: str
    next_action_label: str


class LaunchReadinessResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    generated_at: datetime
    overall_status: str
    read_only: bool = True
    no_execution: bool = True
    executed: int = 0
    live_action: bool = False
    outbound_attempted: bool = False
    owner_approved: bool = False
    operator_halt_status: str
    operator_halt_before: str
    operator_halt_after: str
    outbound_enabled: bool
    live_providers_enabled: bool
    live_providers: dict[str, bool] = Field(default_factory=dict)
    config_ok: bool
    required_config_names: list[str] = Field(default_factory=list)
    config_flags: list[ConfigFlagStatusResponse] = Field(default_factory=list)
    secret_inventory: list[SecretInventoryItemResponse] = Field(default_factory=list)
    ci_smoke_gate: CiSmokeGateStatusResponse
    pending_owner_approval_packets: int = 0
    action_readiness_candidate_count: int = 0
    action_readiness_blocked_count: int = 0
    findings: list[LaunchReadinessFindingResponse] = Field(default_factory=list)
    next_actions: list[LaunchReadinessFindingResponse] = Field(default_factory=list)
    database: str
    environment: str


def _secret_to_response(item: SecretInventoryItem) -> SecretInventoryItemResponse:
    return SecretInventoryItemResponse(
        name=item.name,
        present=item.present,
        status=item.status,
        required=item.required,
    )


def _flag_to_response(item: ConfigFlagStatus) -> ConfigFlagStatusResponse:
    return ConfigFlagStatusResponse(name=item.name, enabled=item.enabled)


def _smoke_to_response(item: CiSmokeGateStatus) -> CiSmokeGateStatusResponse:
    return CiSmokeGateStatusResponse(
        present=item.present,
        documented=item.documented,
        job_name=item.job_name,
    )


def _finding_to_response(item: LaunchReadinessFinding) -> LaunchReadinessFindingResponse:
    return LaunchReadinessFindingResponse(
        severity=item.severity,
        code=item.code,
        next_action_code=item.next_action_code,
        next_action_label=item.next_action_label,
    )


def checklist_to_response(checklist: LaunchReadinessChecklist) -> LaunchReadinessResponse:
    return LaunchReadinessResponse(
        generated_at=checklist.generated_at,
        overall_status=checklist.overall_status,
        read_only=True,
        no_execution=True,
        executed=0,
        live_action=False,
        outbound_attempted=False,
        owner_approved=False,
        operator_halt_status=checklist.operator_halt_status,
        operator_halt_before=checklist.operator_halt_before,
        operator_halt_after=checklist.operator_halt_after,
        outbound_enabled=checklist.outbound_enabled,
        live_providers_enabled=checklist.live_providers_enabled,
        live_providers=dict(checklist.live_providers),
        config_ok=checklist.config_ok,
        required_config_names=list(checklist.required_config_names),
        config_flags=[_flag_to_response(item) for item in checklist.config_flags],
        secret_inventory=[_secret_to_response(item) for item in checklist.secret_inventory],
        ci_smoke_gate=_smoke_to_response(checklist.ci_smoke_gate),
        pending_owner_approval_packets=checklist.pending_owner_approval_packets,
        action_readiness_candidate_count=checklist.action_readiness_candidate_count,
        action_readiness_blocked_count=checklist.action_readiness_blocked_count,
        findings=[_finding_to_response(item) for item in checklist.findings],
        next_actions=[_finding_to_response(item) for item in checklist.next_actions],
        database=checklist.database,
        environment=checklist.environment,
    )


def build_launch_readiness_response(
    db: Session,
    settings: Settings,
    *,
    service: LaunchReadinessService | None = None,
) -> LaunchReadinessResponse:
    checker = service or LaunchReadinessService()
    return checklist_to_response(checker.assess(db, settings))
