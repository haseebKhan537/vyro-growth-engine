"""Read-only owner launch dossier JSON export.

Phase 47 exposes existing readiness, blocker, staged-rollout, handoff,
binder, runbook, manifest, settings-preflight, and audit surfaces as one
sanitized owner-review JSON packet. It reuses OwnerLaunchDossierService,
which reuses those source services. It never executes, builds, publishes,
deploys, applies settings, lifts halt, enables outbound, calls providers,
or changes live state. This export is not permission to go live and is
not an execution surface.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from vyro_growth.config import Settings
from vyro_growth.services.owner_launch_dossier import (
    CLI_COMMAND,
    HTTP_ROUTE,
    OwnerLaunchDossierService,
    dossier_payload,
)


class LocalGitMetadataResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    available: bool = False
    current_branch: str
    current_sha: str
    working_tree_status: str
    git_provider_called: bool = False
    github_actions_called: bool = False


class DossierSourceSurfaceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    label: str
    purpose: str
    overall_status: str
    command_name: str | None = None
    json_route: str | None = None
    html_route: str | None = None
    blocker_codes: list[str] = Field(default_factory=list)
    gate_codes: list[str] = Field(default_factory=list)
    missing_credential_names: list[str] = Field(default_factory=list)
    read_only: bool = True
    no_execution: bool = True
    go_live_permitted: bool = False
    deployment_allowed: bool = False


class DossierNextActionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    status: str
    label: str
    command_name: str | None = None
    json_route: str | None = None
    html_route: str | None = None
    config_name: str | None = None


class DossierSettingsPreflightSummaryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    overall_status: str
    request_count: int
    pending_decision_count: int
    approved_decision_count: int
    blocked_count: int
    executable_count: int = 0
    blocker_codes: list[str] = Field(default_factory=list)
    missing_gate_codes: list[str] = Field(default_factory=list)
    missing_credential_names: list[str] = Field(default_factory=list)
    closed_provider_flag_names: list[str] = Field(default_factory=list)
    no_execution: bool = True
    dry_run_only: bool = True
    executed: int = 0
    settings_applied: bool = False
    execution_allowed: bool = False


class DossierAuditSummaryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    matching_count: int
    shown_count: int
    truncated: bool
    available_event_types: list[str] = Field(default_factory=list)
    available_sources: list[str] = Field(default_factory=list)
    available_statuses: list[str] = Field(default_factory=list)
    read_only: bool = True
    no_execution: bool = True
    executed: int = 0
    halt_changed: bool = False
    outbound_enabled: bool = False
    operator_halt_status: str


class OwnerLaunchDossierResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    generated_at: datetime
    packet_kind: str = "owner_launch_dossier"
    purpose: str = "manual_owner_review_export_only"
    overall_status: str
    read_only: bool = True
    no_execution: bool = True
    no_go_live: bool = True
    no_deployment: bool = True
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
    future_deployment_phase_exists: bool = False
    go_live_permitted: bool = False
    deployment_allowed: bool = False
    deployment_attempted: bool = False
    deployed: bool = False
    build_allowed: bool = False
    artifact_publish_allowed: bool = False
    container_build_attempted: bool = False
    artifact_publish_attempted: bool = False
    outbound_enabled: bool = False
    live_providers_enabled: bool = False
    manual_review_only: bool = True
    owner_launch_dossier_is_not_go_live: bool = True
    dossier_is_not_permission_to_go_live: bool = True
    dossier_is_not_execution: bool = True
    index_is_not_permission_to_go_live: bool = True
    handoff_is_not_go_live: bool = True
    binder_is_not_go_live: bool = True
    runbook_is_not_deployment: bool = True
    manifest_is_not_a_build_or_deploy: bool = True
    staged_rollout_plan_is_not_go_live: bool = True
    operator_halt_status: str
    operator_halt_before: str
    operator_halt_after: str
    closed_provider_flag_names: list[str] = Field(default_factory=list)
    missing_credential_names: list[str] = Field(default_factory=list)
    blocker_codes: list[str] = Field(default_factory=list)
    gate_codes: list[str] = Field(default_factory=list)
    cli_command: str = CLI_COMMAND
    http_route: str = HTTP_ROUTE
    source_index_command: str
    source_index_route: str
    source_index_overall_status: str
    source_blockers_plan_command: str
    source_blockers_plan_route: str
    source_blockers_plan_overall_status: str
    source_staged_rollout_command: str
    source_staged_rollout_route: str
    source_staged_rollout_overall_status: str
    source_handoff_command: str
    source_handoff_route: str
    source_handoff_overall_status: str
    source_binder_command: str
    source_binder_route: str
    source_binder_overall_status: str
    source_runbook_command: str
    source_runbook_route: str
    source_runbook_overall_status: str
    source_manifest_command: str
    source_manifest_route: str
    source_manifest_overall_status: str
    source_preflight_command: str
    source_preflight_route: str
    source_preflight_overall_status: str
    source_audit_route: str
    source_audit_matching_count: int
    related_commands: list[str] = Field(default_factory=list)
    related_routes: list[str] = Field(default_factory=list)
    local_git: LocalGitMetadataResponse
    sources: list[DossierSourceSurfaceResponse] = Field(default_factory=list)
    settings_preflight: DossierSettingsPreflightSummaryResponse
    operator_audit: DossierAuditSummaryResponse
    next_actions: list[DossierNextActionResponse] = Field(default_factory=list)


def build_owner_launch_dossier_response(
    db: Session,
    settings: Settings,
    *,
    service: OwnerLaunchDossierService | None = None,
) -> OwnerLaunchDossierResponse:
    builder = service or OwnerLaunchDossierService()
    return OwnerLaunchDossierResponse.model_validate(dossier_payload(builder.build(db, settings)))
