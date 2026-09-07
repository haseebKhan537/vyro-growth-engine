"""Read-only supervised validation owner approval/run packet JSON export.

Phase 73 exposes the existing Phase 71 contact-validation plan/report and
Phase 72 UI route names as one sanitized owner-review packet. It reuses
SupervisedValidationRunPacketService. It never executes the run, grants
approval, calls providers, sends email, enrolls campaigns, places calls,
books meetings, spends, publishes, deploys, applies settings, lifts halt,
or enables outbound. This export is not permission to run a supervised
validation and not an execution surface.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from vyro_growth.config import Settings
from vyro_growth.services.contact_validation import ContactValidationFilters
from vyro_growth.services.supervised_validation_run_packet import (
    CLI_COMMAND,
    HTML_ROUTE,
    HTTP_ROUTE,
    SupervisedValidationRunPacketService,
    supervised_validation_run_packet_payload,
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


class PrerequisiteItemResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    status: str
    label: str
    blocking: bool
    command_name: str | None = None
    json_route: str | None = None
    html_route: str | None = None


class OwnerDecisionItemResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    name: str
    granted: bool = False


class StatusCountResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    count: int


class OwnerNextStepResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    status: str
    label: str
    command_name: str | None = None
    json_route: str | None = None
    html_route: str | None = None
    config_name: str | None = None


class SegmentResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    state: str | None = None
    city: str | None = None
    specialty: str | None = None
    taxonomy_description: str | None = None
    max_cohort_size: int = 200
    planned_cohort_size: int = 200
    organizations_matching_filters: int = 0


class FunnelAggregateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    organizations_considered: int = 0
    official_website_verified_count: int = 0
    official_website_ambiguous_count: int = 0
    official_website_no_match_count: int = 0
    official_website_unknown_count: int = 0
    staff_facts_found_count: int = 0
    job_posting_intent_count: int = 0
    decision_maker_candidates_found_count: int = 0
    business_email_found_count: int = 0
    verified_email_count: int = 0
    verified_decision_maker_role_email_count: int = 0
    no_contact_found_count: int = 0
    no_verified_email_count: int = 0
    queued_human_phone_verification_count: int = 0
    provider_error_count: int = 0
    official_website_verified_rate: float = 0.0
    staff_facts_found_rate: float = 0.0
    job_posting_intent_rate: float = 0.0
    decision_maker_candidates_found_rate: float = 0.0
    business_email_found_rate: float = 0.0
    verified_email_rate: float = 0.0
    verified_decision_maker_role_email_rate: float = 0.0
    no_contact_found_rate: float = 0.0
    no_verified_email_rate: float = 0.0
    queued_human_phone_verification_rate: float = 0.0
    provider_error_rate: float = 0.0


class PlannedStageResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    command_name: str
    json_route: str | None = None
    mode: str
    executed: bool = False
    live_provider_called: bool = False


class OwnerReviewThresholdResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    metric: str
    comparator: str
    threshold: float
    applied_to_live_settings: bool = False
    scoring_thresholds_changed: bool = False


class ThresholdComparisonResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    metric: str
    observed: float
    threshold: float
    comparator: str
    passed: bool
    blocking: bool = False
    no_contact_found_is_failure: bool = False


class SupervisedValidationRunPacketResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    generated_at: datetime
    packet_kind: str = "supervised_validation_run_packet"
    purpose: str = "manual_owner_supervised_validation_run_review_only"
    overall_status: str
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
    decision_maker_live_enabled: bool = False
    email_verification_live_enabled: bool = False
    email_verification_smtp_enabled: bool = False
    contact_validation_is_not_outbound: bool = True
    contact_validation_is_not_live_send: bool = True
    supervised_validation_run_packet_is_not_execution: bool = True
    export_is_not_permission_to_run: bool = True
    supervised_validation_run_permitted: bool = False
    funnel_strong_enough_for_supervised_validation: bool = False
    no_contact_found_is_normal_outcome: bool = True
    no_contact_found_is_failure: bool = False
    no_verified_email_is_normal_outcome: bool = True
    no_verified_email_is_failure: bool = False
    source_plan_overall_status: str
    source_report_overall_status: str
    source_plan_command: str
    source_plan_route: str
    source_report_command: str
    source_report_route: str
    source_html_route: str
    segment: SegmentResponse
    funnel: FunnelAggregateResponse
    planned_stages: list[PlannedStageResponse] = Field(default_factory=list)
    owner_review_thresholds: list[OwnerReviewThresholdResponse] = Field(default_factory=list)
    threshold_comparisons: list[ThresholdComparisonResponse] = Field(default_factory=list)
    prerequisites: list[PrerequisiteItemResponse] = Field(default_factory=list)
    required_owner_decisions: list[OwnerDecisionItemResponse] = Field(default_factory=list)
    required_credentials: list[NamedPresenceResponse] = Field(default_factory=list)
    required_configs: list[NamedPresenceResponse] = Field(default_factory=list)
    missing_credential_names: list[str] = Field(default_factory=list)
    missing_config_names: list[str] = Field(default_factory=list)
    blocked_code_count: int = 0
    warning_code_count: int = 0
    info_code_count: int = 0
    status_counts: list[StatusCountResponse] = Field(default_factory=list)
    related_commands: list[str] = Field(default_factory=list)
    related_routes: list[str] = Field(default_factory=list)
    local_git: LocalGitMetadataResponse
    cli_command: str = CLI_COMMAND
    http_route: str = HTTP_ROUTE
    html_route: str = HTML_ROUTE
    next_actions: list[OwnerNextStepResponse] = Field(default_factory=list)


def build_supervised_validation_run_packet_response(
    db: Session,
    settings: Settings,
    *,
    filters: ContactValidationFilters | None = None,
    service: SupervisedValidationRunPacketService | None = None,
) -> SupervisedValidationRunPacketResponse:
    builder = service or SupervisedValidationRunPacketService()
    return SupervisedValidationRunPacketResponse.model_validate(
        supervised_validation_run_packet_payload(builder.build(db, settings, filters))
    )
