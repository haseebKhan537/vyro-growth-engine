"""Read-only manual go-live rehearsal checklist JSON export.

Phase 51 exposes existing launch-readiness, go-live index, launch-blocker,
staged-rollout, owner-launch-dossier, provider-setup, runbook, manifest, and
settings-preflight surfaces as one sanitized manual rehearsal checklist. It
reuses GoLiveRehearsalChecklistService, which reuses those source services.
It never executes, builds, publishes, deploys, applies settings, lifts halt,
enables outbound, calls providers, or changes live state. This export is
not a script runner, not permission to go live, and not an execution
surface.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from vyro_growth.config import Settings
from vyro_growth.services.go_live_rehearsal_checklist import (
    CLI_COMMAND,
    HTTP_ROUTE,
    GoLiveRehearsalChecklistService,
    rehearsal_payload,
)


class LocalGitMetadataResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    available: bool = False
    current_branch: str
    current_sha: str
    working_tree_status: str
    git_provider_called: bool = False
    github_actions_called: bool = False


class RehearsalAssertionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    expected: str
    observed: str
    passed: bool


class RehearsalSourceSurfaceResponse(BaseModel):
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


class RehearsalStepResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step_key: str
    gate_key: str
    label: str
    instruction: str
    status: str
    step_kind: str
    required_owner_approval_type: str
    command_name: str | None = None
    json_route: str | None = None
    html_route: str | None = None
    config_name: str | None = None
    expected_assertions: list[str] = Field(default_factory=list)
    blocker_codes: list[str] = Field(default_factory=list)
    gate_codes: list[str] = Field(default_factory=list)
    runnable: bool = False
    executed: int = 0


class RehearsalRollbackNoteResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    label: str
    instruction: str


class RehearsalNextActionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    status: str
    label: str
    command_name: str | None = None
    json_route: str | None = None
    html_route: str | None = None
    config_name: str | None = None


class GoLiveRehearsalChecklistResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    generated_at: datetime
    packet_kind: str = "go_live_rehearsal_checklist"
    purpose: str = "manual_owner_go_live_rehearsal_review_only"
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
    go_live_rehearsal_checklist_is_not_go_live: bool = True
    checklist_is_not_permission_to_go_live: bool = True
    checklist_is_not_execution: bool = True
    rehearsal_is_not_a_script_runner: bool = True
    index_is_not_permission_to_go_live: bool = True
    dossier_is_not_permission_to_go_live: bool = True
    staged_rollout_plan_is_not_go_live: bool = True
    provider_setup_checklist_is_not_go_live: bool = True
    runbook_is_not_deployment: bool = True
    manifest_is_not_a_build_or_deploy: bool = True
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
    source_provider_setup_command: str
    source_provider_setup_route: str
    source_provider_setup_overall_status: str
    source_preflight_command: str
    source_preflight_route: str
    source_preflight_overall_status: str
    source_runbook_command: str
    source_runbook_route: str
    source_runbook_overall_status: str
    source_manifest_command: str
    source_manifest_route: str
    source_manifest_overall_status: str
    related_commands: list[str] = Field(default_factory=list)
    related_routes: list[str] = Field(default_factory=list)
    local_git: LocalGitMetadataResponse
    expected_safe_assertions: list[RehearsalAssertionResponse] = Field(default_factory=list)
    sources: list[RehearsalSourceSurfaceResponse] = Field(default_factory=list)
    rehearsal_steps: list[RehearsalStepResponse] = Field(default_factory=list)
    rollback_guidance: list[RehearsalRollbackNoteResponse] = Field(default_factory=list)
    next_actions: list[RehearsalNextActionResponse] = Field(default_factory=list)


def build_go_live_rehearsal_checklist_response(
    db: Session,
    settings: Settings,
    *,
    service: GoLiveRehearsalChecklistService | None = None,
) -> GoLiveRehearsalChecklistResponse:
    builder = service or GoLiveRehearsalChecklistService()
    return GoLiveRehearsalChecklistResponse.model_validate(
        rehearsal_payload(builder.build(db, settings))
    )
