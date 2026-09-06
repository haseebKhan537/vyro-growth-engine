"""Read-only staged go-live rollout plan JSON export.

Phase 45 exposes the existing readiness, blocker, binder, runbook, and
manifest surfaces as a sanitized staged planning JSON packet. It reuses
StagedRolloutPlanService, which reuses those source services. It never
executes, builds, publishes, deploys, applies settings, lifts halt,
enables outbound, calls providers, or changes live state. This export is
not permission to go live and is not an execution surface.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from vyro_growth.config import Settings
from vyro_growth.services.staged_rollout_plan import (
    CLI_COMMAND,
    HTTP_ROUTE,
    StagedRolloutPlanService,
    plan_payload,
)


class LocalGitMetadataResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    available: bool = False
    current_branch: str
    current_sha: str
    working_tree_status: str
    git_provider_called: bool = False
    github_actions_called: bool = False


class StagedRolloutChecklistItemResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    status: str
    label: str
    owner_approval_type: str
    html_route: str | None = None
    json_route: str | None = None
    command_name: str | None = None
    config_name: str | None = None


class StagedRolloutStageResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stage_key: str
    stage_label: str
    status: str
    blocker_codes: list[str] = Field(default_factory=list)
    gate_codes: list[str] = Field(default_factory=list)
    required_owner_approval_type: str
    checklist_items: list[StagedRolloutChecklistItemResponse] = Field(default_factory=list)
    related_commands: list[str] = Field(default_factory=list)
    related_routes: list[str] = Field(default_factory=list)
    related_config_names: list[str] = Field(default_factory=list)
    read_only: bool = True
    no_execution: bool = True
    execution_allowed: bool = False
    go_live_permitted: bool = False
    deployment_allowed: bool = False
    settings_applied: bool = False
    halt_changed: bool = False
    outbound_enabled: bool = False
    owner_approved: bool = False
    staged_rollout_plan_is_not_go_live: bool = True


class StagedRolloutPlanResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    generated_at: datetime
    packet_kind: str = "staged_go_live_rollout_plan"
    purpose: str = "manual_owner_staged_rollout_planning_only"
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
    staged_rollout_plan_is_not_go_live: bool = True
    plan_is_not_permission_to_go_live: bool = True
    plan_is_not_execution: bool = True
    index_is_not_permission_to_go_live: bool = True
    handoff_is_not_go_live: bool = True
    binder_is_not_go_live: bool = True
    runbook_is_not_deployment: bool = True
    manifest_is_not_a_build_or_deploy: bool = True
    operator_halt_status: str
    operator_halt_before: str
    operator_halt_after: str
    closed_provider_flag_names: list[str] = Field(default_factory=list)
    missing_credential_names: list[str] = Field(default_factory=list)
    blocker_codes: list[str] = Field(default_factory=list)
    cli_command: str = CLI_COMMAND
    http_route: str = HTTP_ROUTE
    source_index_command: str
    source_index_route: str
    source_index_overall_status: str
    source_blockers_plan_command: str
    source_blockers_plan_route: str
    source_blockers_plan_overall_status: str
    source_launch_readiness_command: str
    source_launch_readiness_route: str
    source_launch_readiness_overall_status: str
    source_binder_command: str
    source_binder_route: str
    source_binder_overall_status: str
    source_runbook_command: str
    source_runbook_route: str
    source_runbook_overall_status: str
    source_manifest_command: str
    source_manifest_route: str
    source_manifest_overall_status: str
    related_commands: list[str] = Field(default_factory=list)
    related_routes: list[str] = Field(default_factory=list)
    local_git: LocalGitMetadataResponse
    stages: list[StagedRolloutStageResponse] = Field(default_factory=list)


def build_staged_rollout_plan_response(
    db: Session,
    settings: Settings,
    *,
    service: StagedRolloutPlanService | None = None,
) -> StagedRolloutPlanResponse:
    builder = service or StagedRolloutPlanService()
    return StagedRolloutPlanResponse.model_validate(plan_payload(builder.build(db, settings)))
