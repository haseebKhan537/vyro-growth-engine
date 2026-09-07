"""Read-only supervised 200-practice validation run gate JSON export.

Phase 77 exposes a sanitized owner-approval-required refusal/preflight over
existing live-provider setup, supervised-validation packet, contact-validation,
launch-readiness, settings-preflight, and compliance-binder surfaces. It reuses
SupervisedValidationRunGateService. Default behavior is refusal. It never
executes validation, grants approval, calls providers, sends email, enrolls
campaigns, places calls, autodials, uses AI voice, books meetings, creates
Meet links, launches ads, spends, publishes, deploys, applies settings, lifts
halt, or enables outbound. This export is not permission to run a supervised
validation and not an execution surface.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from vyro_growth.config import Settings
from vyro_growth.services.contact_validation import ContactValidationFilters
from vyro_growth.services.supervised_validation_run_gate import (
    CLI_COMMAND,
    HTTP_ROUTE,
    SupervisedValidationRunGateOptions,
    SupervisedValidationRunGateService,
    supervised_validation_run_gate_payload,
)


class LocalGitMetadataResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    available: bool = False
    current_branch: str
    current_sha: str
    working_tree_status: str
    git_provider_called: bool = False
    github_actions_called: bool = False


class NamedPresenceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    present: bool


class RunGateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    status: str
    label: str
    blocking: bool
    passed: bool
    command_name: str | None = None
    json_route: str | None = None
    html_route: str | None = None


class OwnerDecisionItemResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    name: str
    granted: bool = False


class CompliancePrerequisiteResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    status: str
    label: str
    blocking: bool
    documented: bool


class ValidationRunConstraintResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    label: str
    limit: int | None = None
    required: bool = True


class SegmentResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    state: str | None = None
    city: str | None = None
    specialty: str | None = None
    taxonomy_description: str | None = None
    max_cohort_size: int = 200
    planned_cohort_size: int = 200
    organizations_matching_filters: int = 0


class OwnerNextStepResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    status: str
    label: str
    command_name: str | None = None
    json_route: str | None = None
    html_route: str | None = None
    config_name: str | None = None


class SupervisedValidationRunGateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    generated_at: datetime
    packet_kind: str = "supervised_validation_run_gate"
    purpose: str = "manual_owner_supervised_validation_run_gate_refusal_only"
    overall_status: str
    requested_mode: str = "dry_run"
    dry_run: bool = True
    execute_requested: bool = False
    run_requested: bool = False
    run_executed: bool = False
    run_refused: bool = True
    gate_passed: bool = False
    read_only: bool = True
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
    validation_permitted: bool = False
    spend_attempted: bool = False
    campaign_launched: bool = False
    halt_changed: bool = False
    settings_applied: bool = False
    scoring_thresholds_changed: bool = False
    outbound_enabled: bool = False
    operator_halt_status: str
    operator_halt_before: str
    operator_halt_after: str
    operator_halt_unchanged: bool = True
    live_providers_enabled: bool = False
    live_providers: dict[str, bool] = Field(default_factory=dict)
    contact_validation_is_not_outbound: bool = True
    contact_validation_is_not_live_send: bool = True
    supervised_validation_run_packet_is_not_execution: bool = True
    live_provider_setup_checklist_is_not_go_live: bool = True
    supervised_validation_run_gate_is_not_execution: bool = True
    export_is_not_permission_to_run: bool = True
    supervised_validation_run_permitted: bool = False
    credential_values_included: bool = False
    owner_approval_code_present: bool = False
    owner_approval_code_exported: bool = False
    confirm_operator_halt_unchanged: bool = False
    source_live_provider_command: str
    source_live_provider_route: str
    source_live_provider_overall_status: str
    source_validation_packet_command: str
    source_validation_packet_route: str
    source_validation_packet_overall_status: str
    source_plan_command: str
    source_plan_route: str
    source_report_command: str
    source_report_route: str
    source_html_route: str
    source_launch_readiness_command: str
    source_launch_readiness_route: str
    source_launch_readiness_overall_status: str
    source_preflight_command: str
    source_preflight_route: str
    source_preflight_overall_status: str
    source_binder_command: str
    source_binder_route: str
    source_binder_overall_status: str
    segment: SegmentResponse
    gates: list[RunGateResponse] = Field(default_factory=list)
    refusal_reason_codes: list[str] = Field(default_factory=list)
    blocking_gate_count: int = 0
    passed_gate_count: int = 0
    required_owner_decisions: list[OwnerDecisionItemResponse] = Field(default_factory=list)
    required_credentials: list[NamedPresenceResponse] = Field(default_factory=list)
    missing_credential_names: list[str] = Field(default_factory=list)
    compliance_prerequisites: list[CompliancePrerequisiteResponse] = Field(default_factory=list)
    validation_run_constraints: list[ValidationRunConstraintResponse] = Field(default_factory=list)
    related_commands: list[str] = Field(default_factory=list)
    related_routes: list[str] = Field(default_factory=list)
    local_git: LocalGitMetadataResponse
    cli_command: str = CLI_COMMAND
    http_route: str = HTTP_ROUTE
    next_actions: list[OwnerNextStepResponse] = Field(default_factory=list)


def build_supervised_validation_run_gate_response(
    db: Session,
    settings: Settings,
    *,
    filters: ContactValidationFilters | None = None,
    service: SupervisedValidationRunGateService | None = None,
) -> SupervisedValidationRunGateResponse:
    builder = service or SupervisedValidationRunGateService()
    packet = builder.evaluate(
        db,
        settings,
        filters,
        SupervisedValidationRunGateOptions(dry_run=True, execute_requested=False),
    )
    return SupervisedValidationRunGateResponse.model_validate(
        supervised_validation_run_gate_payload(packet)
    )
