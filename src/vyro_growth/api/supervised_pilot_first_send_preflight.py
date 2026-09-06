"""Read-only supervised pilot first-send preflight JSON export.

Phase 61 exposes the existing supervised pilot go/no-go packet, supervised
pilot plan, candidate readiness, provider setup, rehearsal outcome, launch
readiness, review/action-readiness, owner approval/settings-request, and
operator halt surfaces as one sanitized first-send preflight. It reuses
SupervisedPilotFirstSendPreflightService. It never executes, builds,
publishes, deploys, applies settings, lifts halt, enables outbound,
calls providers, spends, or changes live state. This export is not
permission to send, not permission to go live, and not an execution
surface.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from vyro_growth.config import Settings
from vyro_growth.services.supervised_pilot_first_send_preflight import (
    CLI_COMMAND,
    HTTP_ROUTE,
    SupervisedPilotFirstSendPreflightService,
    supervised_pilot_first_send_preflight_payload,
)


class LocalGitMetadataResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    available: bool = False
    current_branch: str
    current_sha: str
    working_tree_status: str
    git_provider_called: bool = False
    github_actions_called: bool = False


class FirstSendCountResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    count: int


class FirstSendPreflightCheckResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    status: str
    label: str
    blocking: bool
    command_name: str | None = None
    json_route: str | None = None
    html_route: str | None = None


class FirstSendAbortCriterionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    label: str
    instruction: str


class FirstSendNextActionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    status: str
    label: str
    command_name: str | None = None
    json_route: str | None = None
    html_route: str | None = None
    config_name: str | None = None


class SupervisedPilotFirstSendPreflightResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    generated_at: datetime
    packet_kind: str = "supervised_pilot_first_send_preflight"
    purpose: str = "manual_owner_supervised_pilot_first_send_preflight_review_only"
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
    first_send_allowed: bool = False
    first_send_attempted: bool = False
    first_send_executed: int = 0
    sends_executed: int = 0
    suggested_max_first_sends: int = 0
    suggested_max_leads: int = 0
    suggested_max_drafts: int = 0
    suggested_max_manually_reviewed_sends: int = 0
    suggested_max_daily_activity: int = 0
    supervised_pilot_first_send_preflight_is_not_go_live: bool = True
    first_send_preflight_is_not_a_send: bool = True
    export_is_not_permission_to_go_live: bool = True
    export_is_not_execution: bool = True
    supervised_pilot_go_no_go_is_not_go_live: bool = True
    supervised_pilot_plan_is_not_go_live: bool = True
    supervised_pilot_candidates_is_not_go_live: bool = True
    rehearsal_outcome_report_is_not_go_live: bool = True
    go_live_rehearsal_checklist_is_not_go_live: bool = True
    provider_setup_checklist_is_not_go_live: bool = True
    operator_halt_status: str
    operator_halt_before: str
    operator_halt_after: str
    source_go_no_go_overall_status: str
    source_pilot_plan_overall_status: str
    source_candidates_overall_status: str
    ready_for_review_count: int = 0
    blocked_candidate_count: int = 0
    total_candidate_count: int = 0
    review_queue_pending_count: int = 0
    action_readiness_candidate_count: int = 0
    approval_packet_count: int = 0
    settings_request_count: int = 0
    settings_request_pending_count: int = 0
    prerequisite_counts_by_status: list[FirstSendCountResponse] = Field(default_factory=list)
    candidate_counts_by_readiness: list[FirstSendCountResponse] = Field(default_factory=list)
    blocked_reason_counts: list[FirstSendCountResponse] = Field(default_factory=list)
    expected_safe_assertion_count: int = 0
    expected_safe_assertions_passed: int = 0
    expected_safe_assertions_failed: int = 0
    failed_safe_assertion_keys: list[str] = Field(default_factory=list)
    preflight_checks: list[FirstSendPreflightCheckResponse] = Field(default_factory=list)
    abort_criteria: list[FirstSendAbortCriterionResponse] = Field(default_factory=list)
    stop_conditions: list[str] = Field(default_factory=list)
    owner_decision_prerequisites: list[str] = Field(default_factory=list)
    remaining_owner_approval_types: list[str] = Field(default_factory=list)
    closed_provider_flag_names: list[str] = Field(default_factory=list)
    missing_credential_names: list[str] = Field(default_factory=list)
    missing_config_names: list[str] = Field(default_factory=list)
    missing_prerequisite_codes: list[str] = Field(default_factory=list)
    blocker_codes: list[str] = Field(default_factory=list)
    gate_codes: list[str] = Field(default_factory=list)
    cli_command: str = CLI_COMMAND
    http_route: str = HTTP_ROUTE
    source_go_no_go_command: str
    source_go_no_go_route: str
    source_go_no_go_html_route: str
    source_pilot_plan_command: str
    source_pilot_plan_route: str
    source_pilot_plan_html_route: str
    source_candidates_command: str
    source_candidates_route: str
    source_candidates_html_route: str
    related_commands: list[str] = Field(default_factory=list)
    related_routes: list[str] = Field(default_factory=list)
    local_git: LocalGitMetadataResponse
    next_actions: list[FirstSendNextActionResponse] = Field(default_factory=list)


def build_supervised_pilot_first_send_preflight_response(
    db: Session,
    settings: Settings,
    *,
    service: SupervisedPilotFirstSendPreflightService | None = None,
) -> SupervisedPilotFirstSendPreflightResponse:
    builder = service or SupervisedPilotFirstSendPreflightService()
    return SupervisedPilotFirstSendPreflightResponse.model_validate(
        supervised_pilot_first_send_preflight_payload(builder.build(db, settings))
    )
