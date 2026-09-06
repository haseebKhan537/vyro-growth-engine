"""Read-only supervised pilot launch plan JSON export.

Phase 55 exposes existing readiness, rehearsal, outcome, provider setup, and
launch dossier surfaces as one sanitized small-pilot plan. It reuses
SupervisedPilotPlanService, which reuses RehearsalOutcomeReportService and
ProviderSetupChecklistService. It never executes, builds, publishes, deploys,
applies settings, lifts halt, enables outbound, calls providers, spends, or
changes live state. This export is not permission to go live and not an
execution surface.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from vyro_growth.config import Settings
from vyro_growth.services.supervised_pilot_plan import (
    CLI_COMMAND,
    HTTP_ROUTE,
    SupervisedPilotPlanService,
    supervised_pilot_plan_payload,
)


class LocalGitMetadataResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    available: bool = False
    current_branch: str
    current_sha: str
    working_tree_status: str
    git_provider_called: bool = False
    github_actions_called: bool = False


class PilotAssertionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    expected: str
    observed: str
    passed: bool


class PilotScopeRecommendationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    suggested_max_leads: int
    suggested_max_drafts: int
    suggested_max_manually_reviewed_sends: int
    suggested_max_daily_activity: int
    stop_conditions: list[str] = Field(default_factory=list)
    recommendation_summary: str


class PilotPrerequisiteResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    category: str
    label: str
    status: str
    required_owner_approval_type: str
    missing_credential_names: list[str] = Field(default_factory=list)
    closed_provider_flag_names: list[str] = Field(default_factory=list)
    blocker_codes: list[str] = Field(default_factory=list)
    related_commands: list[str] = Field(default_factory=list)
    related_routes: list[str] = Field(default_factory=list)
    review_text: str


class PilotRunbookStepResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step_key: str
    label: str
    instruction: str
    status: str
    runnable: bool = False
    executed: int = 0
    command_name: str | None = None
    json_route: str | None = None
    html_route: str | None = None
    config_name: str | None = None


class PilotAbortCriterionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    label: str
    instruction: str


class PilotNextActionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    status: str
    label: str
    command_name: str | None = None
    json_route: str | None = None
    html_route: str | None = None
    config_name: str | None = None


class SupervisedPilotPlanResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    generated_at: datetime
    packet_kind: str = "supervised_pilot_plan"
    purpose: str = "manual_owner_supervised_pilot_review_only"
    overall_status: str
    read_only: bool = True
    no_execution: bool = True
    no_go_live: bool = True
    no_deployment: bool = True
    no_spend: bool = True
    dry_run_only: bool = True
    executed: int = 0
    execution_attempted: bool = False
    outbound_attempted: bool = False
    live_call_attempted: bool = False
    recommendation_applied: bool = False
    spend_attempted: bool = False
    spend_allowed: bool = False
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
    supervised_pilot_plan_is_not_go_live: bool = True
    plan_is_not_permission_to_go_live: bool = True
    plan_is_not_execution: bool = True
    rehearsal_outcome_report_is_not_go_live: bool = True
    go_live_rehearsal_checklist_is_not_go_live: bool = True
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
    safety_assertions: list[PilotAssertionResponse] = Field(default_factory=list)
    expected_safe_assertion_count: int = 0
    expected_safe_assertions_passed: int = 0
    expected_safe_assertions_failed: int = 0
    failed_safe_assertion_keys: list[str] = Field(default_factory=list)
    remaining_owner_approval_types: list[str] = Field(default_factory=list)
    closed_provider_flag_names: list[str] = Field(default_factory=list)
    missing_credential_names: list[str] = Field(default_factory=list)
    missing_config_names: list[str] = Field(default_factory=list)
    blocker_codes: list[str] = Field(default_factory=list)
    gate_codes: list[str] = Field(default_factory=list)
    pilot_scope: PilotScopeRecommendationResponse
    prerequisites: list[PilotPrerequisiteResponse] = Field(default_factory=list)
    runbook_steps: list[PilotRunbookStepResponse] = Field(default_factory=list)
    abort_criteria: list[PilotAbortCriterionResponse] = Field(default_factory=list)
    cli_command: str = CLI_COMMAND
    http_route: str = HTTP_ROUTE
    source_outcome_command: str
    source_outcome_route: str
    source_outcome_html_route: str
    source_outcome_overall_status: str
    source_rehearsal_command: str
    source_rehearsal_route: str
    source_rehearsal_html_route: str
    source_rehearsal_overall_status: str
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
    related_commands: list[str] = Field(default_factory=list)
    related_routes: list[str] = Field(default_factory=list)
    local_git: LocalGitMetadataResponse
    next_actions: list[PilotNextActionResponse] = Field(default_factory=list)


def build_supervised_pilot_plan_response(
    db: Session,
    settings: Settings,
    *,
    service: SupervisedPilotPlanService | None = None,
) -> SupervisedPilotPlanResponse:
    builder = service or SupervisedPilotPlanService()
    return SupervisedPilotPlanResponse.model_validate(
        supervised_pilot_plan_payload(builder.build(db, settings))
    )
