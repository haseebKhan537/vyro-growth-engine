"""Read-only rehearsal outcome report JSON export.

Phase 53 exposes the current Phase 51 go-live rehearsal checklist as a
compact sanitized outcome packet. It reuses RehearsalOutcomeReportService,
which reuses GoLiveRehearsalChecklistService as the source of truth. It
never executes, builds, publishes, deploys, applies settings, lifts halt,
enables outbound, calls providers, or changes live state. This export is
not permission to go live and not an execution surface.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from vyro_growth.config import Settings
from vyro_growth.services.rehearsal_outcome_report import (
    CLI_COMMAND,
    HTTP_ROUTE,
    RehearsalOutcomeReportService,
    outcome_report_payload,
)


class LocalGitMetadataResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    available: bool = False
    current_branch: str
    current_sha: str
    working_tree_status: str
    git_provider_called: bool = False
    github_actions_called: bool = False


class OutcomeCountResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    count: int


class OutcomeNextActionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    status: str
    label: str
    command_name: str | None = None
    json_route: str | None = None
    html_route: str | None = None
    config_name: str | None = None


class RehearsalOutcomeReportResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    generated_at: datetime
    packet_kind: str = "rehearsal_outcome_report"
    purpose: str = "manual_owner_rehearsal_outcome_review_only"
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
    rehearsal_outcome_report_is_not_go_live: bool = True
    report_is_not_permission_to_go_live: bool = True
    report_is_not_execution: bool = True
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
    rehearsal_step_count: int = 0
    rehearsal_step_counts_by_status: list[OutcomeCountResponse] = Field(default_factory=list)
    rehearsal_step_counts_by_kind: list[OutcomeCountResponse] = Field(default_factory=list)
    rehearsal_step_counts_by_required_owner_approval_type: list[OutcomeCountResponse] = Field(
        default_factory=list
    )
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
    outcome_summary: str
    cli_command: str = CLI_COMMAND
    http_route: str = HTTP_ROUTE
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
    next_actions: list[OutcomeNextActionResponse] = Field(default_factory=list)


def build_rehearsal_outcome_report_response(
    db: Session,
    settings: Settings,
    *,
    service: RehearsalOutcomeReportService | None = None,
) -> RehearsalOutcomeReportResponse:
    builder = service or RehearsalOutcomeReportService()
    return RehearsalOutcomeReportResponse.model_validate(
        outcome_report_payload(builder.build(db, settings))
    )
