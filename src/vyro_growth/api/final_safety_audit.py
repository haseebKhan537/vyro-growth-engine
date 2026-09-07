"""Read-only final repository and safety audit JSON export.

Phase 75 exposes existing launch-readiness, contact-validation,
provider-setup, manifest, runbook, and dossier surfaces as one
sanitized pre-validation audit. It reuses FinalSafetyAuditService.
It never executes validation, grants approval, writes state, runs
migrations, calls providers, sends email, enrolls campaigns, places
calls, books meetings, spends, publishes, deploys, applies settings,
lifts halt, or enables outbound. This export is not permission to
run real-world validation and is not an execution surface.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from vyro_growth.config import Settings
from vyro_growth.services.final_safety_audit import (
    CLI_COMMAND,
    HTTP_ROUTE,
    FinalSafetyAuditService,
    final_safety_audit_payload,
)


class LocalGitMetadataResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    available: bool = False
    current_branch: str
    current_sha: str
    working_tree_status: str
    git_provider_called: bool = False
    github_actions_called: bool = False


class NamedItemResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str


class PhaseInventoryItemResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    phase_number: int
    title: str


class MigrationInventoryItemResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filename: str
    revision_id: str


class LiveFlagItemResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    enabled: bool


class CiJobItemResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    present: bool


class DocCoverageItemResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    path: str
    present: bool
    mentioned: bool


class OpenIssueItemResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    issue_number: str
    title: str


class OwnerApprovalItemResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    name: str
    granted: bool = False


class StatusCountResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    count: int


class FindingCodeItemResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    severity: str


class OwnerNextStepResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    status: str
    label: str
    command_name: str | None = None
    json_route: str | None = None


class FinalSafetyAuditResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    generated_at: datetime
    packet_kind: str = "final_safety_repository_audit"
    purpose: str = "manual_owner_pre_validation_repository_audit_only"
    overall_status: str
    read_only: bool = True
    export_only: bool = True
    dry_run_only: bool = True
    no_execution: bool = True
    no_outbound: bool = True
    no_provider_calls: bool = True
    no_send: bool = True
    no_call: bool = True
    no_book: bool = True
    no_spend: bool = True
    no_deploy: bool = True
    no_autodial: bool = True
    no_ai_voice: bool = True
    no_migrations: bool = True
    no_github_actions: bool = True
    manual_review_only: bool = True
    outbound_attempted: bool = False
    live_call_attempted: bool = False
    live_provider_calls_attempted: bool = False
    smtp_attempted: bool = False
    autodial_attempted: bool = False
    campaign_enrolled: bool = False
    booking_attempted: bool = False
    meet_link_created: bool = False
    ads_launched: bool = False
    execution_allowed: bool = False
    owner_approved: bool = False
    spend_attempted: bool = False
    campaign_launched: bool = False
    halt_changed: bool = False
    settings_applied: bool = False
    scoring_thresholds_changed: bool = False
    github_actions_called: bool = False
    git_provider_called: bool = False
    outbound_enabled: bool = False
    operator_halt_status: str
    operator_halt_before: str
    operator_halt_after: str
    operator_halt_unchanged: bool = True
    kill_switch_outbound_disabled: bool = True
    kill_switch_operator_halt_honored: bool = True
    dual_kill_switch_proof: bool = True
    live_providers_enabled: bool = False
    live_providers: dict[str, bool] = Field(default_factory=dict)
    live_flag_inventory: list[LiveFlagItemResponse] = Field(default_factory=list)
    source_launch_readiness_overall_status: str
    source_contact_validation_overall_status: str
    launch_readiness_is_not_execution: bool = True
    contact_validation_is_not_outbound: bool = True
    contact_validation_is_not_live_send: bool = True
    final_safety_audit_is_not_execution: bool = True
    export_is_not_permission_to_validate: bool = True
    supervised_validation_run_permitted: bool = False
    phases: list[PhaseInventoryItemResponse] = Field(default_factory=list)
    commands: list[NamedItemResponse] = Field(default_factory=list)
    routes: list[NamedItemResponse] = Field(default_factory=list)
    migrations: list[MigrationInventoryItemResponse] = Field(default_factory=list)
    ci_jobs: list[CiJobItemResponse] = Field(default_factory=list)
    safe_local_commands: list[str] = Field(default_factory=list)
    ci_smoke_gate_present: bool = False
    ci_smoke_gate_documented: bool = False
    finding_codes: list[FindingCodeItemResponse] = Field(default_factory=list)
    blocked_code_count: int = 0
    warning_code_count: int = 0
    info_code_count: int = 0
    status_counts: list[StatusCountResponse] = Field(default_factory=list)
    documentation_coverage: list[DocCoverageItemResponse] = Field(default_factory=list)
    open_issues: list[OpenIssueItemResponse] = Field(default_factory=list)
    owner_approvals_required: list[OwnerApprovalItemResponse] = Field(default_factory=list)
    related_commands: list[str] = Field(default_factory=list)
    related_routes: list[str] = Field(default_factory=list)
    local_git: LocalGitMetadataResponse
    cli_command: str = CLI_COMMAND
    http_route: str = HTTP_ROUTE
    next_actions: list[OwnerNextStepResponse] = Field(default_factory=list)


def build_final_safety_audit_response(
    db: Session,
    settings: Settings,
    *,
    service: FinalSafetyAuditService | None = None,
) -> FinalSafetyAuditResponse:
    builder = service or FinalSafetyAuditService()
    return FinalSafetyAuditResponse.model_validate(
        final_safety_audit_payload(builder.build(db, settings))
    )
