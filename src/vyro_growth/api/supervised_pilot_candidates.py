"""Read-only supervised pilot candidate readiness JSON export.

Phase 57 exposes existing discovery, enrichment, scoring, outreach,
supervised pilot plan, provider setup, rehearsal outcome, launch
readiness, and operator halt surfaces as one sanitized candidate
readiness packet. It reuses SupervisedPilotCandidateService. It never
executes, builds, publishes, deploys, applies settings, lifts halt,
enables outbound, calls providers, spends, or changes live state. This
export is not permission to go live and not an execution surface.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from vyro_growth.config import Settings
from vyro_growth.services.supervised_pilot_candidates import (
    CLI_COMMAND,
    HTTP_ROUTE,
    SupervisedPilotCandidateService,
    supervised_pilot_candidates_payload,
)


class LocalGitMetadataResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    available: bool = False
    current_branch: str
    current_sha: str
    working_tree_status: str
    git_provider_called: bool = False
    github_actions_called: bool = False


class CandidateCountResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    count: int


class CandidateScopeRecommendationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    suggested_candidate_count: int
    suggested_max_leads: int
    suggested_max_drafts: int
    suggested_max_manually_reviewed_sends: int
    suggested_max_daily_activity: int
    ready_for_review_count: int
    blocked_candidate_count: int
    total_candidate_count: int
    stop_conditions: list[str] = Field(default_factory=list)
    recommendation_summary: str


class CandidateNextActionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    status: str
    label: str
    command_name: str | None = None
    json_route: str | None = None
    html_route: str | None = None
    config_name: str | None = None


class SupervisedPilotCandidatesResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    generated_at: datetime
    packet_kind: str = "supervised_pilot_candidates"
    purpose: str = "manual_owner_supervised_pilot_candidate_review_only"
    overall_status: str
    read_only: bool = True
    no_execution: bool = True
    no_go_live: bool = True
    no_deployment: bool = True
    no_outbound: bool = True
    no_provider_calls: bool = True
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
    supervised_pilot_candidates_is_not_go_live: bool = True
    export_is_not_permission_to_go_live: bool = True
    export_is_not_execution: bool = True
    supervised_pilot_plan_is_not_go_live: bool = True
    rehearsal_outcome_report_is_not_go_live: bool = True
    go_live_rehearsal_checklist_is_not_go_live: bool = True
    provider_setup_checklist_is_not_go_live: bool = True
    operator_halt_status: str
    operator_halt_before: str
    operator_halt_after: str
    candidate_scope: CandidateScopeRecommendationResponse
    candidate_counts_by_readiness: list[CandidateCountResponse] = Field(default_factory=list)
    candidate_counts_by_status: list[CandidateCountResponse] = Field(default_factory=list)
    candidate_counts_by_stage: list[CandidateCountResponse] = Field(default_factory=list)
    candidate_counts_by_source: list[CandidateCountResponse] = Field(default_factory=list)
    candidate_counts_by_specialty: list[CandidateCountResponse] = Field(default_factory=list)
    candidate_counts_by_state: list[CandidateCountResponse] = Field(default_factory=list)
    scoring_distribution: list[CandidateCountResponse] = Field(default_factory=list)
    website_match_counts: list[CandidateCountResponse] = Field(default_factory=list)
    outreach_status_counts: list[CandidateCountResponse] = Field(default_factory=list)
    suppression_counts_by_reason: list[CandidateCountResponse] = Field(default_factory=list)
    kill_switch_outbound_disabled: bool = True
    kill_switch_operator_halt_active: bool = False
    kill_switch_live_providers_closed: bool = True
    suppression_record_count: int = 0
    blocked_counts: list[CandidateCountResponse] = Field(default_factory=list)
    missing_prerequisite_codes: list[str] = Field(default_factory=list)
    remaining_owner_approval_types: list[str] = Field(default_factory=list)
    closed_provider_flag_names: list[str] = Field(default_factory=list)
    missing_credential_names: list[str] = Field(default_factory=list)
    missing_config_names: list[str] = Field(default_factory=list)
    blocker_codes: list[str] = Field(default_factory=list)
    gate_codes: list[str] = Field(default_factory=list)
    cli_command: str = CLI_COMMAND
    http_route: str = HTTP_ROUTE
    source_pilot_plan_command: str
    source_pilot_plan_route: str
    source_pilot_plan_html_route: str
    source_pilot_plan_overall_status: str
    source_outcome_command: str
    source_outcome_route: str
    source_outcome_overall_status: str
    source_rehearsal_command: str
    source_rehearsal_route: str
    source_rehearsal_overall_status: str
    source_launch_readiness_command: str
    source_launch_readiness_route: str
    source_launch_readiness_overall_status: str
    source_index_command: str
    source_index_route: str
    source_index_overall_status: str
    source_provider_setup_command: str
    source_provider_setup_route: str
    source_provider_setup_overall_status: str
    related_commands: list[str] = Field(default_factory=list)
    related_routes: list[str] = Field(default_factory=list)
    local_git: LocalGitMetadataResponse
    next_actions: list[CandidateNextActionResponse] = Field(default_factory=list)


def build_supervised_pilot_candidates_response(
    db: Session,
    settings: Settings,
    *,
    service: SupervisedPilotCandidateService | None = None,
) -> SupervisedPilotCandidatesResponse:
    builder = service or SupervisedPilotCandidateService()
    return SupervisedPilotCandidatesResponse.model_validate(
        supervised_pilot_candidates_payload(builder.build(db, settings))
    )
