"""Read-only supervised validation owner approval/run packet.

Phase 73 converts the Phase 71 contact-validation plan/report and Phase 72
UI route names into one owner-review packet for a later bounded
200-practice contact-enrichment validation run. It reuses
ContactValidationService payloads and never recalculates funnel readiness.
It never executes that run, grants approval, calls providers, sends email,
enrolls campaigns, places calls, autodials, uses AI voice, books meetings,
creates Meet links, launches ads, spends, publishes, deploys, applies
settings, lifts halt, or enables outbound. This packet is not permission
to run a supervised validation and not an execution surface.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Never

from sqlalchemy.orm import Session

from vyro_growth.config import Settings, credential_presence_flags
from vyro_growth.observability import sanitize_mapping
from vyro_growth.services.contact_validation import (
    BLOCKED_STATUS,
    INFO_STATUS,
    OVERALL_STATUSES,
    PLAN_CLI_COMMAND,
    PLAN_HTTP_ROUTE,
    READY_STATUS,
    REPORT_CLI_COMMAND,
    REPORT_HTTP_ROUTE,
    WARNING_STATUS,
    ContactValidationFilters,
    ContactValidationPlan,
    ContactValidationReport,
    ContactValidationService,
    ContactValidationStage,
    OwnerReviewThreshold,
    ThresholdComparison,
)
from vyro_growth.services.contact_validation import HTML_ROUTE as CONTACT_VALIDATION_HTML_ROUTE
from vyro_growth.services.contact_validation import (
    RELATED_COMMANDS as CONTACT_VALIDATION_COMMANDS,
)
from vyro_growth.services.contact_validation import (
    RELATED_ROUTES as CONTACT_VALIDATION_ROUTES,
)
from vyro_growth.services.launch_readiness import default_repo_root
from vyro_growth.services.operator_halt import HaltStatus, read_operator_halt
from vyro_growth.services.release_artifact_manifest import LocalGitMetadata, inspect_local_git

PACKET_KIND = "supervised_validation_run_packet"
PACKET_PURPOSE = "manual_owner_supervised_validation_run_review_only"
CLI_COMMAND = "supervised-validation-run-packet"
HTTP_ROUTE = "/internal/supervised-validation-run-packet"
HTML_ROUTE = "/internal/operator-supervised-validation-run-packet"
REQUIRED_CREDENTIAL_NAMES: tuple[str, ...] = (
    "DECISION_MAKER_API_KEY",
    "EMAIL_VERIFICATION_API_KEY",
    "INTERNAL_API_KEY",
)
REQUIRED_CONFIG_NAMES: tuple[str, ...] = (
    "OUTBOUND_ENABLED",
    "DECISION_MAKER_LIVE_ENABLED",
    "EMAIL_VERIFICATION_LIVE_ENABLED",
    "EMAIL_VERIFICATION_SMTP_ENABLED",
)
OWNER_DECISION_SPECS: tuple[tuple[str, str], ...] = (
    (
        "approve_bounded_validation_segment",
        "Approve a bounded 200-practice segment later. "
        "This packet does not grant that approval.",
    ),
    (
        "approve_live_decision_maker_credentials",
        "Approve live decision-maker credentials later. "
        "This packet does not enable that provider.",
    ),
    (
        "approve_live_email_verification_credentials",
        "Approve live email-verification credentials later. "
        "This packet does not enable that provider.",
    ),
    (
        "permit_supervised_validation_run",
        "Permit a later owner-supervised validation run. "
        "supervised_validation_run_permitted stays false.",
    ),
    (
        "enable_outbound",
        "Keep OUTBOUND_ENABLED=false. This packet is not permission to enable outbound.",
    ),
    (
        "lift_operator_halt",
        "Keep operator halt unchanged. This packet never lifts halt.",
    ),
)
RELATED_COMMANDS: tuple[str, ...] = tuple(
    dict.fromkeys(
        (
            *CONTACT_VALIDATION_COMMANDS,
            CLI_COMMAND,
        )
    )
)
RELATED_ROUTES: tuple[str, ...] = tuple(
    dict.fromkeys(
        (
            *CONTACT_VALIDATION_ROUTES,
            HTTP_ROUTE,
            HTML_ROUTE,
        )
    )
)


@dataclass(frozen=True)
class NamedPresence:
    name: str
    present: bool


@dataclass(frozen=True)
class PrerequisiteItem:
    code: str
    status: str
    label: str
    blocking: bool
    command_name: str | None
    json_route: str | None
    html_route: str | None


@dataclass(frozen=True)
class OwnerDecisionItem:
    code: str
    name: str
    granted: bool


@dataclass(frozen=True)
class StatusCount:
    key: str
    count: int


@dataclass(frozen=True)
class OwnerNextStep:
    code: str
    status: str
    label: str
    command_name: str | None
    json_route: str | None
    html_route: str | None
    config_name: str | None


@dataclass(frozen=True)
class FunnelAggregate:
    organizations_considered: int
    official_website_verified_count: int
    official_website_ambiguous_count: int
    official_website_no_match_count: int
    official_website_unknown_count: int
    staff_facts_found_count: int
    job_posting_intent_count: int
    decision_maker_candidates_found_count: int
    business_email_found_count: int
    verified_email_count: int
    verified_decision_maker_role_email_count: int
    no_contact_found_count: int
    no_verified_email_count: int
    queued_human_phone_verification_count: int
    provider_error_count: int
    official_website_verified_rate: float
    staff_facts_found_rate: float
    job_posting_intent_rate: float
    decision_maker_candidates_found_rate: float
    business_email_found_rate: float
    verified_email_rate: float
    verified_decision_maker_role_email_rate: float
    no_contact_found_rate: float
    no_verified_email_rate: float
    queued_human_phone_verification_rate: float
    provider_error_rate: float


@dataclass(frozen=True)
class SupervisedValidationRunPacket:
    generated_at: datetime
    packet_kind: str
    purpose: str
    overall_status: str
    read_only: bool
    dry_run_only: bool
    no_execution: bool
    no_outbound: bool
    no_provider_calls: bool
    no_send: bool
    no_call: bool
    no_book: bool
    no_spend: bool
    no_deploy: bool
    no_autodial: bool
    no_ai_voice: bool
    manual_review_only: bool
    outbound_attempted: bool
    live_call_attempted: bool
    live_provider_calls_attempted: bool
    smtp_attempted: bool
    autodial_attempted: bool
    campaign_enrolled: bool
    booking_attempted: bool
    meet_link_created: bool
    ads_launched: bool
    execution_allowed: bool
    owner_approved: bool
    spend_attempted: bool
    campaign_launched: bool
    halt_changed: bool
    settings_applied: bool
    scoring_thresholds_changed: bool
    outbound_enabled: bool
    operator_halt_status: str
    operator_halt_before: str
    operator_halt_after: str
    operator_halt_unchanged: bool
    live_providers_enabled: bool
    live_providers: dict[str, bool]
    decision_maker_live_enabled: bool
    email_verification_live_enabled: bool
    email_verification_smtp_enabled: bool
    contact_validation_is_not_outbound: bool
    contact_validation_is_not_live_send: bool
    supervised_validation_run_packet_is_not_execution: bool
    export_is_not_permission_to_run: bool
    supervised_validation_run_permitted: bool
    funnel_strong_enough_for_supervised_validation: bool
    no_contact_found_is_normal_outcome: bool
    no_contact_found_is_failure: bool
    no_verified_email_is_normal_outcome: bool
    no_verified_email_is_failure: bool
    source_plan_overall_status: str
    source_report_overall_status: str
    source_plan_command: str
    source_plan_route: str
    source_report_command: str
    source_report_route: str
    source_html_route: str
    segment_state: str | None
    segment_city: str | None
    segment_specialty: str | None
    segment_taxonomy_description: str | None
    max_cohort_size: int
    planned_cohort_size: int
    organizations_matching_filters: int
    funnel: FunnelAggregate
    planned_stages: tuple[ContactValidationStage, ...]
    owner_review_thresholds: tuple[OwnerReviewThreshold, ...]
    threshold_comparisons: tuple[ThresholdComparison, ...]
    prerequisites: tuple[PrerequisiteItem, ...]
    required_owner_decisions: tuple[OwnerDecisionItem, ...]
    required_credentials: tuple[NamedPresence, ...]
    required_configs: tuple[NamedPresence, ...]
    missing_credential_names: tuple[str, ...]
    missing_config_names: tuple[str, ...]
    blocked_code_count: int
    warning_code_count: int
    info_code_count: int
    status_counts: tuple[StatusCount, ...]
    related_commands: tuple[str, ...]
    related_routes: tuple[str, ...]
    local_git: LocalGitMetadata
    cli_command: str
    http_route: str
    html_route: str
    next_actions: tuple[OwnerNextStep, ...]


class SupervisedValidationRunPacketService:
    """Owner-review packet over Phase 71 plan/report. Never executes the run."""

    def build(
        self,
        db: Session,
        settings: Settings,
        filters: ContactValidationFilters | None = None,
        *,
        repo_root: Path | None = None,
        service: ContactValidationService | None = None,
    ) -> SupervisedValidationRunPacket:
        halt_before = read_operator_halt(db)
        source = service or ContactValidationService()
        plan = source.build_plan(db, settings, filters, repo_root=repo_root)
        report = source.build_report(db, settings, filters, repo_root=repo_root)
        local_git = inspect_local_git(repo_root or default_repo_root())
        halt_after = read_operator_halt(db)
        _assert_halt_unchanged(halt_before, halt_after)
        credentials = _required_credentials(settings)
        configs = _required_configs(settings)
        prerequisites = _prerequisites(plan, report)
        decisions = _owner_decisions()
        next_actions = _next_actions(plan, report)
        status_counts = _status_counts(
            prerequisites=prerequisites,
            decisions=decisions,
            comparisons=report.threshold_comparisons,
            next_actions=next_actions,
        )
        counts_by_key = {item.key: item.count for item in status_counts}
        return SupervisedValidationRunPacket(
            generated_at=datetime.now(tz=UTC),
            packet_kind=PACKET_KIND,
            purpose=PACKET_PURPOSE,
            overall_status=_checked_status(report.overall_status),
            read_only=True,
            dry_run_only=True,
            no_execution=True,
            no_outbound=True,
            no_provider_calls=True,
            no_send=True,
            no_call=True,
            no_book=True,
            no_spend=True,
            no_deploy=True,
            no_autodial=True,
            no_ai_voice=True,
            manual_review_only=True,
            outbound_attempted=False,
            live_call_attempted=False,
            live_provider_calls_attempted=False,
            smtp_attempted=False,
            autodial_attempted=False,
            campaign_enrolled=False,
            booking_attempted=False,
            meet_link_created=False,
            ads_launched=False,
            execution_allowed=False,
            owner_approved=False,
            spend_attempted=False,
            campaign_launched=False,
            halt_changed=False,
            settings_applied=False,
            scoring_thresholds_changed=False,
            outbound_enabled=report.outbound_enabled,
            operator_halt_status=halt_after.value,
            operator_halt_before=halt_before.value,
            operator_halt_after=halt_after.value,
            operator_halt_unchanged=halt_before is halt_after,
            live_providers_enabled=report.live_providers_enabled,
            live_providers=dict(report.live_providers),
            decision_maker_live_enabled=settings.decision_maker_live_enabled,
            email_verification_live_enabled=settings.email_verification_live_enabled,
            email_verification_smtp_enabled=settings.email_verification_smtp_enabled,
            contact_validation_is_not_outbound=True,
            contact_validation_is_not_live_send=True,
            supervised_validation_run_packet_is_not_execution=True,
            export_is_not_permission_to_run=True,
            supervised_validation_run_permitted=False,
            funnel_strong_enough_for_supervised_validation=(
                report.funnel_strong_enough_for_supervised_validation
            ),
            no_contact_found_is_normal_outcome=True,
            no_contact_found_is_failure=False,
            no_verified_email_is_normal_outcome=True,
            no_verified_email_is_failure=False,
            source_plan_overall_status=plan.overall_status,
            source_report_overall_status=report.overall_status,
            source_plan_command=PLAN_CLI_COMMAND,
            source_plan_route=PLAN_HTTP_ROUTE,
            source_report_command=REPORT_CLI_COMMAND,
            source_report_route=REPORT_HTTP_ROUTE,
            source_html_route=CONTACT_VALIDATION_HTML_ROUTE,
            segment_state=report.segment.state,
            segment_city=report.segment.city,
            segment_specialty=report.segment.specialty,
            segment_taxonomy_description=report.segment.taxonomy_description,
            max_cohort_size=report.segment.max_cohort_size,
            planned_cohort_size=report.segment.planned_cohort_size,
            organizations_matching_filters=report.segment.organizations_matching_filters,
            funnel=_funnel_from_report(report),
            planned_stages=report.planned_stages,
            owner_review_thresholds=report.owner_review_thresholds,
            threshold_comparisons=report.threshold_comparisons,
            prerequisites=prerequisites,
            required_owner_decisions=decisions,
            required_credentials=credentials,
            required_configs=configs,
            missing_credential_names=tuple(
                item.name for item in credentials if not item.present
            ),
            missing_config_names=tuple(item.name for item in configs if not item.present),
            blocked_code_count=counts_by_key.get(BLOCKED_STATUS, 0),
            warning_code_count=counts_by_key.get(WARNING_STATUS, 0),
            info_code_count=counts_by_key.get(INFO_STATUS, 0),
            status_counts=status_counts,
            related_commands=RELATED_COMMANDS,
            related_routes=RELATED_ROUTES,
            local_git=local_git,
            cli_command=CLI_COMMAND,
            http_route=HTTP_ROUTE,
            html_route=HTML_ROUTE,
            next_actions=next_actions,
        )


def supervised_validation_run_packet_payload(
    packet: SupervisedValidationRunPacket,
) -> dict[str, Any]:
    return {
        "generated_at": packet.generated_at.isoformat(),
        "packet_kind": packet.packet_kind,
        "purpose": packet.purpose,
        "overall_status": packet.overall_status,
        "read_only": packet.read_only,
        "dry_run_only": packet.dry_run_only,
        "no_execution": packet.no_execution,
        "no_outbound": packet.no_outbound,
        "no_provider_calls": packet.no_provider_calls,
        "no_send": packet.no_send,
        "no_call": packet.no_call,
        "no_book": packet.no_book,
        "no_spend": packet.no_spend,
        "no_deploy": packet.no_deploy,
        "no_autodial": packet.no_autodial,
        "no_ai_voice": packet.no_ai_voice,
        "manual_review_only": packet.manual_review_only,
        "outbound_attempted": packet.outbound_attempted,
        "live_call_attempted": packet.live_call_attempted,
        "live_provider_calls_attempted": packet.live_provider_calls_attempted,
        "smtp_attempted": packet.smtp_attempted,
        "autodial_attempted": packet.autodial_attempted,
        "campaign_enrolled": packet.campaign_enrolled,
        "booking_attempted": packet.booking_attempted,
        "meet_link_created": packet.meet_link_created,
        "ads_launched": packet.ads_launched,
        "execution_allowed": packet.execution_allowed,
        "owner_approved": packet.owner_approved,
        "spend_attempted": packet.spend_attempted,
        "campaign_launched": packet.campaign_launched,
        "halt_changed": packet.halt_changed,
        "settings_applied": packet.settings_applied,
        "scoring_thresholds_changed": packet.scoring_thresholds_changed,
        "outbound_enabled": packet.outbound_enabled,
        "operator_halt_status": packet.operator_halt_status,
        "operator_halt_before": packet.operator_halt_before,
        "operator_halt_after": packet.operator_halt_after,
        "operator_halt_unchanged": packet.operator_halt_unchanged,
        "live_providers_enabled": packet.live_providers_enabled,
        "live_providers": dict(packet.live_providers),
        "decision_maker_live_enabled": packet.decision_maker_live_enabled,
        "email_verification_live_enabled": packet.email_verification_live_enabled,
        "email_verification_smtp_enabled": packet.email_verification_smtp_enabled,
        "contact_validation_is_not_outbound": packet.contact_validation_is_not_outbound,
        "contact_validation_is_not_live_send": packet.contact_validation_is_not_live_send,
        "supervised_validation_run_packet_is_not_execution": (
            packet.supervised_validation_run_packet_is_not_execution
        ),
        "export_is_not_permission_to_run": packet.export_is_not_permission_to_run,
        "supervised_validation_run_permitted": packet.supervised_validation_run_permitted,
        "funnel_strong_enough_for_supervised_validation": (
            packet.funnel_strong_enough_for_supervised_validation
        ),
        "no_contact_found_is_normal_outcome": packet.no_contact_found_is_normal_outcome,
        "no_contact_found_is_failure": packet.no_contact_found_is_failure,
        "no_verified_email_is_normal_outcome": packet.no_verified_email_is_normal_outcome,
        "no_verified_email_is_failure": packet.no_verified_email_is_failure,
        "source_plan_overall_status": packet.source_plan_overall_status,
        "source_report_overall_status": packet.source_report_overall_status,
        "source_plan_command": packet.source_plan_command,
        "source_plan_route": packet.source_plan_route,
        "source_report_command": packet.source_report_command,
        "source_report_route": packet.source_report_route,
        "source_html_route": packet.source_html_route,
        "segment": {
            "state": packet.segment_state,
            "city": packet.segment_city,
            "specialty": packet.segment_specialty,
            "taxonomy_description": packet.segment_taxonomy_description,
            "max_cohort_size": packet.max_cohort_size,
            "planned_cohort_size": packet.planned_cohort_size,
            "organizations_matching_filters": packet.organizations_matching_filters,
        },
        "funnel": _funnel_payload(packet.funnel),
        "planned_stages": [_stage_payload(stage) for stage in packet.planned_stages],
        "owner_review_thresholds": [
            _threshold_payload(item) for item in packet.owner_review_thresholds
        ],
        "threshold_comparisons": [
            _comparison_payload(item) for item in packet.threshold_comparisons
        ],
        "prerequisites": [_prerequisite_payload(item) for item in packet.prerequisites],
        "required_owner_decisions": [
            _decision_payload(item) for item in packet.required_owner_decisions
        ],
        "required_credentials": [_presence_payload(item) for item in packet.required_credentials],
        "required_configs": [_presence_payload(item) for item in packet.required_configs],
        "missing_credential_names": list(packet.missing_credential_names),
        "missing_config_names": list(packet.missing_config_names),
        "blocked_code_count": packet.blocked_code_count,
        "warning_code_count": packet.warning_code_count,
        "info_code_count": packet.info_code_count,
        "status_counts": [_count_payload(item) for item in packet.status_counts],
        "related_commands": list(packet.related_commands),
        "related_routes": list(packet.related_routes),
        "local_git": {
            "available": packet.local_git.available,
            "current_branch": packet.local_git.current_branch,
            "current_sha": packet.local_git.current_sha,
            "working_tree_status": packet.local_git.working_tree_status,
            "git_provider_called": False,
            "github_actions_called": False,
        },
        "cli_command": packet.cli_command,
        "http_route": packet.http_route,
        "html_route": packet.html_route,
        "next_actions": [_action_payload(item) for item in packet.next_actions],
    }


def format_supervised_validation_run_packet(
    packet: SupervisedValidationRunPacket,
    *,
    as_json: bool = False,
) -> str:
    payload = sanitize_mapping(supervised_validation_run_packet_payload(packet))
    if as_json:
        return json.dumps(payload, sort_keys=True)
    return _format_markdown(packet, payload)


def _funnel_from_report(report: ContactValidationReport) -> FunnelAggregate:
    return FunnelAggregate(
        organizations_considered=report.organizations_considered,
        official_website_verified_count=report.official_website_verified_count,
        official_website_ambiguous_count=report.official_website_ambiguous_count,
        official_website_no_match_count=report.official_website_no_match_count,
        official_website_unknown_count=report.official_website_unknown_count,
        staff_facts_found_count=report.staff_facts_found_count,
        job_posting_intent_count=report.job_posting_intent_count,
        decision_maker_candidates_found_count=report.decision_maker_candidates_found_count,
        business_email_found_count=report.business_email_found_count,
        verified_email_count=report.verified_email_count,
        verified_decision_maker_role_email_count=(
            report.verified_decision_maker_role_email_count
        ),
        no_contact_found_count=report.no_contact_found_count,
        no_verified_email_count=report.no_verified_email_count,
        queued_human_phone_verification_count=report.queued_human_phone_verification_count,
        provider_error_count=report.provider_error_count,
        official_website_verified_rate=report.official_website_verified_rate,
        staff_facts_found_rate=report.staff_facts_found_rate,
        job_posting_intent_rate=report.job_posting_intent_rate,
        decision_maker_candidates_found_rate=report.decision_maker_candidates_found_rate,
        business_email_found_rate=report.business_email_found_rate,
        verified_email_rate=report.verified_email_rate,
        verified_decision_maker_role_email_rate=(
            report.verified_decision_maker_role_email_rate
        ),
        no_contact_found_rate=report.no_contact_found_rate,
        no_verified_email_rate=report.no_verified_email_rate,
        queued_human_phone_verification_rate=report.queued_human_phone_verification_rate,
        provider_error_rate=report.provider_error_rate,
    )


def _required_credentials(settings: Settings) -> tuple[NamedPresence, ...]:
    presence = credential_presence_flags(settings)
    mapping = {
        "DECISION_MAKER_API_KEY": presence["decision_maker_api_key"],
        "EMAIL_VERIFICATION_API_KEY": presence["email_verification_api_key"],
        "INTERNAL_API_KEY": presence["internal_api_key"],
    }
    return tuple(
        NamedPresence(name=name, present=mapping[name]) for name in REQUIRED_CREDENTIAL_NAMES
    )


def _required_configs(settings: Settings) -> tuple[NamedPresence, ...]:
    mapping = {
        "OUTBOUND_ENABLED": settings.outbound_enabled,
        "DECISION_MAKER_LIVE_ENABLED": settings.decision_maker_live_enabled,
        "EMAIL_VERIFICATION_LIVE_ENABLED": settings.email_verification_live_enabled,
        "EMAIL_VERIFICATION_SMTP_ENABLED": settings.email_verification_smtp_enabled,
    }
    return tuple(NamedPresence(name=name, present=mapping[name]) for name in REQUIRED_CONFIG_NAMES)


def _prerequisites(
    plan: ContactValidationPlan,
    report: ContactValidationReport,
) -> tuple[PrerequisiteItem, ...]:
    outbound_status = BLOCKED_STATUS if report.outbound_enabled else INFO_STATUS
    live_status = BLOCKED_STATUS if report.live_providers_enabled else INFO_STATUS
    halt_unchanged = report.operator_halt_before == report.operator_halt_after
    halt_status = INFO_STATUS if halt_unchanged else BLOCKED_STATUS
    funnel_label = (
        "Funnel thresholds passed for owner review only. "
        "supervised_validation_run_permitted remains false."
        if report.funnel_strong_enough_for_supervised_validation
        else (
            "Funnel is not yet strong enough for a supervised 200-practice "
            "validation run. This packet does not execute that run."
        )
    )
    return (
        PrerequisiteItem(
            code="keep_outbound_disabled",
            status=_bucket_status(outbound_status),
            label="Keep OUTBOUND_ENABLED=false. This packet is not permission to enable outbound.",
            blocking=report.outbound_enabled,
            command_name=PLAN_CLI_COMMAND,
            json_route=PLAN_HTTP_ROUTE,
            html_route=HTML_ROUTE,
        ),
        PrerequisiteItem(
            code="keep_operator_halt_unchanged",
            status=_bucket_status(halt_status),
            label="Keep operator halt unchanged. This packet never lifts halt or applies settings.",
            blocking=not halt_unchanged,
            command_name=REPORT_CLI_COMMAND,
            json_route=REPORT_HTTP_ROUTE,
            html_route=HTML_ROUTE,
        ),
        PrerequisiteItem(
            code="keep_live_providers_disabled_until_owner_approval",
            status=_bucket_status(live_status),
            label=(
                "Keep live provider flags false until a later owner-approved step. "
                "This packet does not call providers."
            ),
            blocking=report.live_providers_enabled,
            command_name=REPORT_CLI_COMMAND,
            json_route=REPORT_HTTP_ROUTE,
            html_route=HTML_ROUTE,
        ),
        PrerequisiteItem(
            code="review_contact_validation_plan",
            status=_bucket_status(plan.overall_status),
            label=(
                "Review the sanitized contact-validation plan. Planned stages "
                "are existing route/command names only and are not executed."
            ),
            blocking=False,
            command_name=PLAN_CLI_COMMAND,
            json_route=PLAN_HTTP_ROUTE,
            html_route=CONTACT_VALIDATION_HTML_ROUTE,
        ),
        PrerequisiteItem(
            code="review_contact_validation_report",
            status=_bucket_status(report.overall_status),
            label=(
                "Review aggregate funnel counts and rates from stored local data. "
                "This packet does not call providers."
            ),
            blocking=False,
            command_name=REPORT_CLI_COMMAND,
            json_route=REPORT_HTTP_ROUTE,
            html_route=CONTACT_VALIDATION_HTML_ROUTE,
        ),
        PrerequisiteItem(
            code="review_operator_contact_validation_ui",
            status=_bucket_status(report.overall_status),
            label=(
                "Review the Phase 72 operator contact-validation UI. "
                "That page is an aggregate-only shell, not an execution surface."
            ),
            blocking=False,
            command_name=REPORT_CLI_COMMAND,
            json_route=REPORT_HTTP_ROUTE,
            html_route=CONTACT_VALIDATION_HTML_ROUTE,
        ),
        PrerequisiteItem(
            code="review_operator_supervised_validation_run_packet_ui",
            status=_bucket_status(report.overall_status),
            label=(
                "Review the Phase 74 operator supervised-validation run-packet UI. "
                "That page is an aggregate-only shell, not an execution surface."
            ),
            blocking=False,
            command_name=CLI_COMMAND,
            json_route=HTTP_ROUTE,
            html_route=HTML_ROUTE,
        ),
        PrerequisiteItem(
            code="funnel_thresholds_owner_review_only",
            status=_bucket_status(report.overall_status),
            label=funnel_label,
            blocking=False,
            command_name=REPORT_CLI_COMMAND,
            json_route=REPORT_HTTP_ROUTE,
            html_route=HTML_ROUTE,
        ),
        PrerequisiteItem(
            code="no_contact_found_is_normal_outcome",
            status=INFO_STATUS,
            label=(
                "NO_CONTACT_FOUND is a normal outcome, not a failure. "
                "Queued human phone-verification remains review-only."
            ),
            blocking=False,
            command_name="list-phone-verification",
            json_route="/internal/phone-verification/tasks",
            html_route=CONTACT_VALIDATION_HTML_ROUTE,
        ),
        PrerequisiteItem(
            code="no_verified_email_is_normal_outcome",
            status=INFO_STATUS,
            label=(
                "NO_VERIFIED_EMAIL is a normal outcome, not a failure. "
                "This packet does not send or verify live email."
            ),
            blocking=False,
            command_name="email-verification-metrics",
            json_route="/internal/email-verification/metrics",
            html_route=CONTACT_VALIDATION_HTML_ROUTE,
        ),
        PrerequisiteItem(
            code="later_owner_approval_required_before_supervised_run",
            status=INFO_STATUS,
            label=(
                "A later explicit owner approval is required before any supervised "
                "validation run. owner_approved stays false."
            ),
            blocking=False,
            command_name=CLI_COMMAND,
            json_route=HTTP_ROUTE,
            html_route=HTML_ROUTE,
        ),
        PrerequisiteItem(
            code="supervised_validation_run_not_permitted",
            status=INFO_STATUS,
            label=(
                "supervised_validation_run_permitted=false. Do not execute a "
                "200-practice validation run, send email, enroll campaigns, "
                "or place calls from this packet."
            ),
            blocking=False,
            command_name=CLI_COMMAND,
            json_route=HTTP_ROUTE,
            html_route=HTML_ROUTE,
        ),
    )


def _owner_decisions() -> tuple[OwnerDecisionItem, ...]:
    return tuple(
        OwnerDecisionItem(code=code, name=name, granted=False)
        for code, name in OWNER_DECISION_SPECS
    )


def _next_actions(
    plan: ContactValidationPlan,
    report: ContactValidationReport,
) -> tuple[OwnerNextStep, ...]:
    outbound_status = BLOCKED_STATUS if report.outbound_enabled else INFO_STATUS
    halt_unchanged = report.operator_halt_before == report.operator_halt_after
    halt_status = INFO_STATUS if halt_unchanged else BLOCKED_STATUS
    funnel_code = (
        "funnel_ready_for_owner_review_only"
        if report.funnel_strong_enough_for_supervised_validation
        else "funnel_not_ready_for_supervised_validation"
    )
    funnel_label = (
        "Funnel thresholds passed for owner review only. "
        "supervised_validation_run_permitted remains false."
        if report.funnel_strong_enough_for_supervised_validation
        else (
            "Funnel is not yet strong enough for a supervised 200-practice "
            "validation run. This packet does not execute that run."
        )
    )
    return (
        OwnerNextStep(
            code="keep_outbound_disabled",
            status=_bucket_status(outbound_status),
            label="Keep OUTBOUND_ENABLED=false. This packet is not permission to enable outbound.",
            command_name=PLAN_CLI_COMMAND,
            json_route=PLAN_HTTP_ROUTE,
            html_route=HTML_ROUTE,
            config_name="OUTBOUND_ENABLED",
        ),
        OwnerNextStep(
            code="keep_operator_halt_unchanged",
            status=_bucket_status(halt_status),
            label="Keep operator halt unchanged. This packet never lifts halt or applies settings.",
            command_name=REPORT_CLI_COMMAND,
            json_route=REPORT_HTTP_ROUTE,
            html_route=HTML_ROUTE,
            config_name=None,
        ),
        OwnerNextStep(
            code="review_contact_validation_plan",
            status=_bucket_status(plan.overall_status),
            label=(
                "Review the sanitized contact-validation plan. Planned stages "
                "are existing route/command names only and are not executed."
            ),
            command_name=PLAN_CLI_COMMAND,
            json_route=PLAN_HTTP_ROUTE,
            html_route=CONTACT_VALIDATION_HTML_ROUTE,
            config_name=None,
        ),
        OwnerNextStep(
            code="review_contact_validation_report",
            status=_bucket_status(report.overall_status),
            label=(
                "Review aggregate funnel counts and rates from stored local data. "
                "This packet does not call providers."
            ),
            command_name=REPORT_CLI_COMMAND,
            json_route=REPORT_HTTP_ROUTE,
            html_route=CONTACT_VALIDATION_HTML_ROUTE,
            config_name=None,
        ),
        OwnerNextStep(
            code="review_operator_contact_validation_ui",
            status=_bucket_status(report.overall_status),
            label=(
                "Review GET /internal/operator-contact-validation. That Phase 72 "
                "shell is aggregate-only and is not an execution surface."
            ),
            command_name=REPORT_CLI_COMMAND,
            json_route=REPORT_HTTP_ROUTE,
            html_route=CONTACT_VALIDATION_HTML_ROUTE,
            config_name=None,
        ),
        OwnerNextStep(
            code="review_operator_supervised_validation_run_packet_ui",
            status=_bucket_status(report.overall_status),
            label=(
                "Review GET /internal/operator-supervised-validation-run-packet. "
                "That Phase 74 shell is aggregate-only and is not an execution surface."
            ),
            command_name=CLI_COMMAND,
            json_route=HTTP_ROUTE,
            html_route=HTML_ROUTE,
            config_name=None,
        ),
        OwnerNextStep(
            code=funnel_code,
            status=_bucket_status(report.overall_status),
            label=funnel_label,
            command_name=REPORT_CLI_COMMAND,
            json_route=REPORT_HTTP_ROUTE,
            html_route=HTML_ROUTE,
            config_name=None,
        ),
        OwnerNextStep(
            code="no_contact_found_is_normal_outcome",
            status=INFO_STATUS,
            label=(
                "NO_CONTACT_FOUND is a normal outcome, not a failure. "
                "Queued human phone-verification remains review-only."
            ),
            command_name="list-phone-verification",
            json_route="/internal/phone-verification/tasks",
            html_route=CONTACT_VALIDATION_HTML_ROUTE,
            config_name=None,
        ),
        OwnerNextStep(
            code="no_verified_email_is_normal_outcome",
            status=INFO_STATUS,
            label=(
                "NO_VERIFIED_EMAIL is a normal outcome, not a failure. "
                "This packet does not send or verify live email."
            ),
            command_name="email-verification-metrics",
            json_route="/internal/email-verification/metrics",
            html_route=CONTACT_VALIDATION_HTML_ROUTE,
            config_name=None,
        ),
        OwnerNextStep(
            code="supervised_validation_run_not_permitted",
            status=INFO_STATUS,
            label=(
                "supervised_validation_run_permitted=false. Do not execute a "
                "200-practice validation run, send email, enroll campaigns, "
                "or place calls from this packet."
            ),
            command_name=CLI_COMMAND,
            json_route=HTTP_ROUTE,
            html_route=HTML_ROUTE,
            config_name=None,
        ),
    )


def _status_counts(
    *,
    prerequisites: Sequence[PrerequisiteItem],
    decisions: Sequence[OwnerDecisionItem],
    comparisons: Sequence[ThresholdComparison],
    next_actions: Sequence[OwnerNextStep],
) -> tuple[StatusCount, ...]:
    counts: Counter[str] = Counter()
    for prerequisite in prerequisites:
        counts[_bucket_status(prerequisite.status)] += 1
    for action in next_actions:
        counts[_bucket_status(action.status)] += 1
    for comparison in comparisons:
        if comparison.blocking and not comparison.passed:
            counts[BLOCKED_STATUS] += 1
        elif comparison.passed:
            counts[INFO_STATUS] += 1
        else:
            counts[WARNING_STATUS] += 1
    counts[INFO_STATUS] += len(decisions)
    return (
        StatusCount(key=BLOCKED_STATUS, count=counts.get(BLOCKED_STATUS, 0)),
        StatusCount(key=WARNING_STATUS, count=counts.get(WARNING_STATUS, 0)),
        StatusCount(key=INFO_STATUS, count=counts.get(INFO_STATUS, 0)),
    )


def _bucket_status(status: str) -> str:
    checked = _checked_status(status)
    if checked == READY_STATUS:
        return INFO_STATUS
    if checked == BLOCKED_STATUS:
        return BLOCKED_STATUS
    if checked == WARNING_STATUS:
        return WARNING_STATUS
    if checked == INFO_STATUS:
        return INFO_STATUS
    return _unknown_status(checked)


def _checked_status(status: str) -> str:
    if status not in OVERALL_STATUSES:
        return _unknown_status(status)
    return status


def _unknown_status(status: str) -> Never:
    raise RuntimeError(f"unhandled supervised validation packet status: {status!r}")


def _assert_halt_unchanged(before: HaltStatus, after: HaltStatus) -> None:
    if after is not before:
        raise RuntimeError("supervised validation run packet must not change operator halt")


def _funnel_payload(funnel: FunnelAggregate) -> dict[str, Any]:
    return {
        "organizations_considered": funnel.organizations_considered,
        "official_website_verified_count": funnel.official_website_verified_count,
        "official_website_ambiguous_count": funnel.official_website_ambiguous_count,
        "official_website_no_match_count": funnel.official_website_no_match_count,
        "official_website_unknown_count": funnel.official_website_unknown_count,
        "staff_facts_found_count": funnel.staff_facts_found_count,
        "job_posting_intent_count": funnel.job_posting_intent_count,
        "decision_maker_candidates_found_count": funnel.decision_maker_candidates_found_count,
        "business_email_found_count": funnel.business_email_found_count,
        "verified_email_count": funnel.verified_email_count,
        "verified_decision_maker_role_email_count": (
            funnel.verified_decision_maker_role_email_count
        ),
        "no_contact_found_count": funnel.no_contact_found_count,
        "no_verified_email_count": funnel.no_verified_email_count,
        "queued_human_phone_verification_count": funnel.queued_human_phone_verification_count,
        "provider_error_count": funnel.provider_error_count,
        "official_website_verified_rate": funnel.official_website_verified_rate,
        "staff_facts_found_rate": funnel.staff_facts_found_rate,
        "job_posting_intent_rate": funnel.job_posting_intent_rate,
        "decision_maker_candidates_found_rate": funnel.decision_maker_candidates_found_rate,
        "business_email_found_rate": funnel.business_email_found_rate,
        "verified_email_rate": funnel.verified_email_rate,
        "verified_decision_maker_role_email_rate": (
            funnel.verified_decision_maker_role_email_rate
        ),
        "no_contact_found_rate": funnel.no_contact_found_rate,
        "no_verified_email_rate": funnel.no_verified_email_rate,
        "queued_human_phone_verification_rate": funnel.queued_human_phone_verification_rate,
        "provider_error_rate": funnel.provider_error_rate,
    }


def _stage_payload(stage: ContactValidationStage) -> dict[str, Any]:
    return {
        "code": stage.code,
        "command_name": stage.command_name,
        "json_route": stage.json_route,
        "mode": stage.mode,
        "executed": stage.executed,
        "live_provider_called": stage.live_provider_called,
    }


def _threshold_payload(item: OwnerReviewThreshold) -> dict[str, Any]:
    return {
        "code": item.code,
        "metric": item.metric,
        "comparator": item.comparator,
        "threshold": item.threshold,
        "applied_to_live_settings": item.applied_to_live_settings,
        "scoring_thresholds_changed": item.scoring_thresholds_changed,
    }


def _comparison_payload(item: ThresholdComparison) -> dict[str, Any]:
    return {
        "code": item.code,
        "metric": item.metric,
        "observed": item.observed,
        "threshold": item.threshold,
        "comparator": item.comparator,
        "passed": item.passed,
        "blocking": item.blocking,
        "no_contact_found_is_failure": item.no_contact_found_is_failure,
    }


def _prerequisite_payload(item: PrerequisiteItem) -> dict[str, Any]:
    return {
        "code": item.code,
        "status": item.status,
        "label": item.label,
        "blocking": item.blocking,
        "command_name": item.command_name,
        "json_route": item.json_route,
        "html_route": item.html_route,
    }


def _decision_payload(item: OwnerDecisionItem) -> dict[str, Any]:
    return {
        "code": item.code,
        "name": item.name,
        "granted": item.granted,
    }


def _presence_payload(item: NamedPresence) -> dict[str, Any]:
    return {
        "name": item.name,
        "present": item.present,
    }


def _count_payload(item: StatusCount) -> dict[str, Any]:
    return {
        "key": item.key,
        "count": item.count,
    }


def _action_payload(item: OwnerNextStep) -> dict[str, Any]:
    return {
        "code": item.code,
        "status": item.status,
        "label": item.label,
        "command_name": item.command_name,
        "json_route": item.json_route,
        "html_route": item.html_route,
        "config_name": item.config_name,
    }


def _format_markdown(packet: SupervisedValidationRunPacket, payload: dict[str, Any]) -> str:
    segment = payload["segment"]
    funnel = payload["funnel"]
    lines = [
        "# Supervised validation owner approval/run packet",
        "",
        (
            f"status={payload['overall_status']} "
            f"kind={payload['packet_kind']} "
            f"purpose={payload['purpose']}"
        ),
        f"- generated_at: {payload['generated_at']}",
        (
            f"- operator_halt_before={payload['operator_halt_before']} "
            f"status={payload['operator_halt_status']} "
            f"after={payload['operator_halt_after']} "
            f"unchanged={_bool_text(payload['operator_halt_unchanged'])}"
        ),
        f"- outbound_enabled: {_bool_text(payload['outbound_enabled'])}",
        f"- live_providers_enabled: {_bool_text(payload['live_providers_enabled'])}",
        f"- cli_command: {payload['cli_command']}",
        f"- http_route: {payload['http_route']}",
        f"- html_route: {payload['html_route']}",
        f"- source_plan_command: {payload['source_plan_command']}",
        f"- source_plan_route: {payload['source_plan_route']}",
        f"- source_report_command: {payload['source_report_command']}",
        f"- source_report_route: {payload['source_report_route']}",
        f"- source_html_route: {payload['source_html_route']}",
        f"- source_plan_overall_status: {payload['source_plan_overall_status']}",
        f"- source_report_overall_status: {payload['source_report_overall_status']}",
        "",
        "## Target segment",
        f"- state: {segment['state'] or '-'}",
        f"- city: {segment['city'] or '-'}",
        f"- specialty: {segment['specialty'] or '-'}",
        f"- taxonomy_description: {segment['taxonomy_description'] or '-'}",
        f"- max_cohort_size: {segment['max_cohort_size']}",
        f"- planned_cohort_size: {segment['planned_cohort_size']}",
        f"- organizations_matching_filters: {segment['organizations_matching_filters']}",
        "",
        "## Safety flags",
        "- read_only=true",
        "- dry_run_only=true",
        "- no_execution=true",
        "- no_outbound=true",
        "- no_provider_calls=true",
        "- no_send=true",
        "- no_call=true",
        "- no_book=true",
        "- no_spend=true",
        "- no_deploy=true",
        "- no_autodial=true",
        "- no_ai_voice=true",
        "- owner_approved=false",
        "- supervised_validation_run_permitted=false",
        "- execution_allowed=false",
        "- export_is_not_permission_to_run=true",
        "- supervised_validation_run_packet_is_not_execution=true",
        f"- halt_changed={_bool_text(payload['halt_changed'])}",
        f"- operator_halt_unchanged={_bool_text(payload['operator_halt_unchanged'])}",
        (
            "- no_contact_found_is_normal_outcome="
            f"{_bool_text(payload['no_contact_found_is_normal_outcome'])}"
        ),
        (
            "- no_verified_email_is_normal_outcome="
            f"{_bool_text(payload['no_verified_email_is_normal_outcome'])}"
        ),
        "",
        "## Funnel aggregates",
        f"- organizations_considered: {funnel['organizations_considered']}",
        f"- official_website_verified_count: {funnel['official_website_verified_count']}",
        f"- staff_facts_found_count: {funnel['staff_facts_found_count']}",
        f"- job_posting_intent_count: {funnel['job_posting_intent_count']}",
        (
            "- decision_maker_candidates_found_count: "
            f"{funnel['decision_maker_candidates_found_count']}"
        ),
        f"- business_email_found_count: {funnel['business_email_found_count']}",
        f"- verified_email_count: {funnel['verified_email_count']}",
        (
            "- verified_decision_maker_role_email_count: "
            f"{funnel['verified_decision_maker_role_email_count']}"
        ),
        f"- no_contact_found_count: {funnel['no_contact_found_count']}",
        f"- no_verified_email_count: {funnel['no_verified_email_count']}",
        (
            "- queued_human_phone_verification_count: "
            f"{funnel['queued_human_phone_verification_count']}"
        ),
        f"- provider_error_count: {funnel['provider_error_count']}",
        (
            "- funnel_strong_enough_for_supervised_validation: "
            f"{_bool_text(payload['funnel_strong_enough_for_supervised_validation'])}"
        ),
        "",
        "## Status code counts",
        f"- blocked_code_count: {payload['blocked_code_count']}",
        f"- warning_code_count: {payload['warning_code_count']}",
        f"- info_code_count: {payload['info_code_count']}",
    ]
    lines.extend(["", "## Prerequisite checklist"])
    for prerequisite in packet.prerequisites:
        command_name = prerequisite.command_name or "-"
        json_route = prerequisite.json_route or "-"
        html_route = prerequisite.html_route or "-"
        lines.append(
            f"- [{prerequisite.status}] {prerequisite.code} "
            f"blocking={_bool_text(prerequisite.blocking)} "
            f"command={command_name} json_route={json_route} "
            f"html_route={html_route} label={prerequisite.label}"
        )
    lines.extend(["", "## Required owner decisions"])
    for decision in packet.required_owner_decisions:
        lines.append(
            f"- {decision.code} granted={_bool_text(decision.granted)} name={decision.name}"
        )
    lines.extend(["", "## Required credentials"])
    for credential in packet.required_credentials:
        lines.append(f"- {credential.name} present={_bool_text(credential.present)}")
    lines.extend(["", "## Required configs"])
    for config in packet.required_configs:
        lines.append(f"- {config.name} present={_bool_text(config.present)}")
    lines.extend(["", "## Planned existing stages"])
    for stage in packet.planned_stages:
        json_route = stage.json_route or "-"
        lines.append(
            f"- {stage.code} command={stage.command_name} json_route={json_route} "
            f"executed={_bool_text(stage.executed)} "
            f"live_provider_called={_bool_text(stage.live_provider_called)}"
        )
    lines.extend(["", "## Threshold comparison statuses"])
    for comparison in packet.threshold_comparisons:
        lines.append(
            f"- {comparison.code} metric={comparison.metric} "
            f"passed={_bool_text(comparison.passed)} "
            f"blocking={_bool_text(comparison.blocking)}"
        )
    lines.extend(["", "## Owner next steps"])
    for action in packet.next_actions:
        command_name = action.command_name or "-"
        json_route = action.json_route or "-"
        html_route = action.html_route or "-"
        config_name = action.config_name or "-"
        lines.append(
            f"- [{action.status}] {action.code} command={command_name} "
            f"json_route={json_route} html_route={html_route} "
            f"config_name={config_name} label={action.label}"
        )
    lines.extend(
        [
            "",
            "## Local git",
            f"- available: {_bool_text(packet.local_git.available)}",
            f"- current_branch: {packet.local_git.current_branch}",
            f"- current_sha: {packet.local_git.current_sha}",
            f"- working_tree_status: {packet.local_git.working_tree_status}",
            "- git_provider_called: false",
            "- github_actions_called: false",
        ]
    )
    return "\n".join(lines)


def _bool_text(value: object) -> str:
    return "true" if value is True else "false"
