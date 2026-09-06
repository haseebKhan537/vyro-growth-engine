"""Read-only launch blockers remediation plan JSON export.

Phase 43 exposes the existing Phase 42 go-live readiness index blockers as
sanitized remediation-planning JSON. It reuses LaunchBlockersPlanService,
which reuses GoLiveReadinessIndexService. It never executes, builds,
publishes, deploys, applies settings, lifts halt, enables outbound, calls
providers, or changes live state. This export is not permission to go live
and is not an execution surface.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from vyro_growth.config import Settings
from vyro_growth.services.launch_blockers_plan import (
    CLI_COMMAND,
    HTTP_ROUTE,
    LaunchBlockersPlanService,
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


class RemediationStepResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    blocker_code: str
    surface_key: str
    surface_label: str
    current_status: str
    recommended_step: str
    owner_approval_type: str
    step_kind: str
    html_route: str | None = None
    json_route: str | None = None
    command_name: str | None = None
    config_name: str | None = None


class RemediationGroupResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    group_key: str
    group_label: str
    group_kind: str
    overall_status: str
    step_count: str
    steps: list[RemediationStepResponse] = Field(default_factory=list)


class LaunchBlockersPlanResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    generated_at: datetime
    packet_kind: str = "launch_blockers_remediation_plan"
    purpose: str = "manual_owner_remediation_planning_only"
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
    manual_review_only: bool = True
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
    outbound_enabled: bool = False
    live_providers_enabled: bool = False
    closed_provider_flag_names: list[str] = Field(default_factory=list)
    missing_credential_names: list[str] = Field(default_factory=list)
    blocker_codes: list[str] = Field(default_factory=list)
    cli_command: str = CLI_COMMAND
    http_route: str = HTTP_ROUTE
    source_index_command: str
    source_index_route: str
    source_index_overall_status: str
    related_commands: list[str] = Field(default_factory=list)
    related_routes: list[str] = Field(default_factory=list)
    local_git: LocalGitMetadataResponse
    groups: list[RemediationGroupResponse] = Field(default_factory=list)
    steps: list[RemediationStepResponse] = Field(default_factory=list)


def build_launch_blockers_plan_response(
    db: Session,
    settings: Settings,
    *,
    service: LaunchBlockersPlanService | None = None,
) -> LaunchBlockersPlanResponse:
    builder = service or LaunchBlockersPlanService()
    return LaunchBlockersPlanResponse.model_validate(plan_payload(builder.build(db, settings)))
