"""Read-only contact-enrichment validation plan and report JSON export.

Phase 71 exposes sanitized 200-practice measurement counts only. It never
executes outbound, calls live paid providers, or returns prospect identifiers.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from vyro_growth.config import Settings
from vyro_growth.services.contact_validation import (
    PLAN_CLI_COMMAND,
    PLAN_HTTP_ROUTE,
    REPORT_CLI_COMMAND,
    REPORT_HTTP_ROUTE,
    ContactValidationError,
    ContactValidationFilters,
    ContactValidationPlan,
    ContactValidationReport,
    ContactValidationService,
    plan_payload,
    report_payload,
)


class LocalGitMetadataResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    available: bool = False
    current_branch: str
    current_sha: str
    working_tree_status: str
    git_provider_called: bool = False
    github_actions_called: bool = False


class ContactValidationSegmentResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    state: str | None = None
    city: str | None = None
    specialty: str | None = None
    taxonomy_description: str | None = None
    max_cohort_size: int = 200
    organizations_matching_filters: int = 0
    planned_cohort_size: int = 200


class ContactValidationStageResponse(BaseModel):
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


class ContactValidationSafetyModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    generated_at: datetime
    packet_kind: str
    purpose: str = "contact_enrichment_validation_measurement_only"
    overall_status: str
    read_only: bool = True
    dry_run_only: bool = True
    no_execution: bool = True
    no_outbound: bool = True
    no_provider_calls: bool = True
    no_spend: bool = True
    no_deployment: bool = True
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
    live_providers_enabled: bool = False
    live_providers: dict[str, bool] = Field(default_factory=dict)
    decision_maker_live_enabled: bool = False
    email_verification_live_enabled: bool = False
    email_verification_smtp_enabled: bool = False
    contact_validation_is_not_outbound: bool = True
    contact_validation_is_not_live_send: bool = True
    supervised_validation_run_permitted: bool = False
    funnel_strong_enough_for_supervised_validation: bool = False
    no_contact_found_is_normal_outcome: bool = True
    no_contact_found_is_failure: bool = False
    segment: ContactValidationSegmentResponse
    planned_stages: list[ContactValidationStageResponse] = Field(default_factory=list)
    owner_review_thresholds: list[OwnerReviewThresholdResponse] = Field(default_factory=list)
    related_commands: list[str] = Field(default_factory=list)
    related_routes: list[str] = Field(default_factory=list)
    local_git: LocalGitMetadataResponse
    cli_command: str
    http_route: str


class ContactValidationPlanResponse(ContactValidationSafetyModel):
    packet_kind: str = "contact_validation_plan"
    cli_command: str = PLAN_CLI_COMMAND
    http_route: str = PLAN_HTTP_ROUTE


class ContactValidationReportResponse(ContactValidationSafetyModel):
    packet_kind: str = "contact_validation_report"
    cli_command: str = REPORT_CLI_COMMAND
    http_route: str = REPORT_HTTP_ROUTE
    threshold_comparisons: list[ThresholdComparisonResponse] = Field(default_factory=list)
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
    website_match_counts: dict[str, int] = Field(default_factory=dict)
    phone_verification_by_status: dict[str, int] = Field(default_factory=dict)
    run_ids_by_source: dict[str, list[str]] = Field(default_factory=dict)
    run_counts_by_source: dict[str, int] = Field(default_factory=dict)


def filters_from_query(
    *,
    state: str | None = None,
    city: str | None = None,
    specialty: str | None = None,
    taxonomy_description: str | None = None,
    max_cohort_size: int = 200,
) -> ContactValidationFilters:
    return ContactValidationFilters(
        state=state,
        city=city,
        specialty=specialty,
        taxonomy_description=taxonomy_description,
        max_cohort_size=max_cohort_size,
    )


def plan_to_response(plan: ContactValidationPlan) -> ContactValidationPlanResponse:
    return ContactValidationPlanResponse.model_validate(plan_payload(plan))


def report_to_response(report: ContactValidationReport) -> ContactValidationReportResponse:
    return ContactValidationReportResponse.model_validate(report_payload(report))


def build_contact_validation_plan_response(
    db: Session,
    settings: Settings,
    *,
    filters: ContactValidationFilters | None = None,
    service: ContactValidationService | None = None,
) -> ContactValidationPlanResponse:
    plan_service = service or ContactValidationService()
    return plan_to_response(plan_service.build_plan(db, settings, filters))


def build_contact_validation_report_response(
    db: Session,
    settings: Settings,
    *,
    filters: ContactValidationFilters | None = None,
    service: ContactValidationService | None = None,
) -> ContactValidationReportResponse:
    report_service = service or ContactValidationService()
    return report_to_response(report_service.build_report(db, settings, filters))


def contact_validation_http_error(error: ContactValidationError) -> tuple[int, str]:
    return 400, error.message
