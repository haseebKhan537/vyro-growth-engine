"""Read-only provider credential/setup checklist JSON export.

Phase 49 exposes existing launch-readiness, go-live index, launch-blocker,
staged-rollout, owner-launch-dossier, settings-preflight, and runbook
surfaces as one sanitized provider setup checklist. It reuses
ProviderSetupChecklistService, which reuses those source services. It never
executes, builds, publishes, deploys, applies settings, lifts halt, enables
outbound, calls providers, or changes live state. This export is not
permission to go live and is not an execution surface.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from vyro_growth.config import Settings
from vyro_growth.services.provider_setup_checklist import (
    CLI_COMMAND,
    HTTP_ROUTE,
    ProviderSetupChecklistService,
    checklist_payload,
)


class LocalGitMetadataResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    available: bool = False
    current_branch: str
    current_sha: str
    working_tree_status: str
    git_provider_called: bool = False
    github_actions_called: bool = False


class ProviderCredentialStatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    present: bool
    status: str
    required: bool


class ProviderFlagStateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    enabled: bool


class ProviderSetupCategoryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    label: str
    overall_status: str
    required_owner_approval_type: str
    config_names: list[str] = Field(default_factory=list)
    missing_credential_names: list[str] = Field(default_factory=list)
    closed_provider_flag_names: list[str] = Field(default_factory=list)
    credential_statuses: list[ProviderCredentialStatusResponse] = Field(default_factory=list)
    flag_states: list[ProviderFlagStateResponse] = Field(default_factory=list)
    blocker_codes: list[str] = Field(default_factory=list)
    gate_codes: list[str] = Field(default_factory=list)
    related_commands: list[str] = Field(default_factory=list)
    related_routes: list[str] = Field(default_factory=list)
    preparation_label: str
    read_only: bool = True
    no_execution: bool = True
    go_live_permitted: bool = False
    deployment_allowed: bool = False


class LocalVerificationGateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    status: str
    label: str
    command_name: str | None = None
    json_route: str | None = None


class ProviderSetupNextActionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    status: str
    label: str
    command_name: str | None = None
    json_route: str | None = None
    html_route: str | None = None
    config_name: str | None = None


class ProviderSetupChecklistResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    generated_at: datetime
    packet_kind: str = "provider_setup_checklist"
    purpose: str = "manual_owner_provider_setup_review_only"
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
    provider_setup_checklist_is_not_go_live: bool = True
    checklist_is_not_permission_to_go_live: bool = True
    checklist_is_not_execution: bool = True
    index_is_not_permission_to_go_live: bool = True
    dossier_is_not_permission_to_go_live: bool = True
    staged_rollout_plan_is_not_go_live: bool = True
    runbook_is_not_deployment: bool = True
    operator_halt_status: str
    operator_halt_before: str
    operator_halt_after: str
    closed_provider_flag_names: list[str] = Field(default_factory=list)
    missing_credential_names: list[str] = Field(default_factory=list)
    blocker_codes: list[str] = Field(default_factory=list)
    gate_codes: list[str] = Field(default_factory=list)
    cli_command: str = CLI_COMMAND
    http_route: str = HTTP_ROUTE
    source_launch_readiness_command: str
    source_launch_readiness_route: str
    source_launch_readiness_overall_status: str
    source_index_command: str
    source_index_route: str
    source_index_overall_status: str
    source_blockers_plan_command: str
    source_blockers_plan_route: str
    source_blockers_plan_overall_status: str
    source_staged_rollout_command: str
    source_staged_rollout_route: str
    source_staged_rollout_overall_status: str
    source_dossier_command: str
    source_dossier_route: str
    source_dossier_overall_status: str
    source_preflight_command: str
    source_preflight_route: str
    source_preflight_overall_status: str
    source_runbook_command: str
    source_runbook_route: str
    source_runbook_overall_status: str
    related_commands: list[str] = Field(default_factory=list)
    related_routes: list[str] = Field(default_factory=list)
    local_git: LocalGitMetadataResponse
    categories: list[ProviderSetupCategoryResponse] = Field(default_factory=list)
    local_verification_gates: list[LocalVerificationGateResponse] = Field(default_factory=list)
    next_actions: list[ProviderSetupNextActionResponse] = Field(default_factory=list)


def build_provider_setup_checklist_response(
    db: Session,
    settings: Settings,
    *,
    service: ProviderSetupChecklistService | None = None,
) -> ProviderSetupChecklistResponse:
    builder = service or ProviderSetupChecklistService()
    return ProviderSetupChecklistResponse.model_validate(
        checklist_payload(builder.build(db, settings))
    )
