"""Dry-run contact-enrichment validation plan and 200-practice report.

Phase 71 measures stored discovery/enrichment/verification outcomes for a
bounded cohort. It never calls live paid providers, sends email, enrolls
campaigns, places calls, books meetings, spends, publishes, deploys, applies
settings, or changes operator halt / outbound flags.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Never
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from vyro_growth.config import Settings, any_live_provider_enabled, live_provider_flags
from vyro_growth.domain import (
    ContactDiscoveryCallStatus,
    ContactRoleCategory,
    ContactVerificationStatus,
    EnrichmentRunStatus,
    WebsiteFactType,
    WebsiteMatchStatus,
)
from vyro_growth.models import (
    Contact,
    ContactDiscoveryCall,
    DiscoveryRun,
    EnrichmentRun,
    Organization,
    SourceEvidence,
)
from vyro_growth.observability import sanitize_mapping
from vyro_growth.providers.decision_makers import DECISION_MAKER_SOURCE
from vyro_growth.providers.email_verification import (
    EMAIL_VERIFICATION_SOURCE,
    is_verified_safe_verdict,
)
from vyro_growth.providers.website import WEBSITE_ENRICHMENT_SOURCE
from vyro_growth.services.launch_readiness import default_repo_root
from vyro_growth.services.operator_halt import HaltStatus, read_operator_halt
from vyro_growth.services.release_artifact_manifest import (
    LocalGitMetadata,
    inspect_local_git,
)

PACKET_KIND_PLAN = "contact_validation_plan"
PACKET_KIND_REPORT = "contact_validation_report"
PACKET_PURPOSE = "contact_enrichment_validation_measurement_only"
PLAN_CLI_COMMAND = "contact-validation-plan"
REPORT_CLI_COMMAND = "contact-validation-report"
PLAN_HTTP_ROUTE = "/internal/contact-validation/plan"
REPORT_HTTP_ROUTE = "/internal/contact-validation/report"
MAX_COHORT_SIZE = 200
DEFAULT_COHORT_SIZE = 200
MIN_COHORT_SIZE = 1
NPPES_SOURCE = "nppes"
STATE_RE = re.compile(r"^[A-Za-z]{2}$")
UNSAFE_FILTER_RE = re.compile(r"[@:]|\b(?:sk|rk)-", re.IGNORECASE)
SAFE_ROLE_CATEGORIES = frozenset(category.value for category in ContactRoleCategory)
SAFE_WEBSITE_MATCH_STATUSES = frozenset(status.value for status in WebsiteMatchStatus)
SAFE_PHONE_QUEUE_STATUSES = frozenset(status.value for status in ContactDiscoveryCallStatus)
UNKNOWN_BUCKET = "unknown"
READY_STATUS = "ready_for_owner_review"
BLOCKED_STATUS = "blocked"
WARNING_STATUS = "warning"
INFO_STATUS = "info"
OVERALL_STATUSES = frozenset({READY_STATUS, BLOCKED_STATUS, WARNING_STATUS, INFO_STATUS})

DEFAULT_MIN_ORGANIZATIONS_CONSIDERED = 50
DEFAULT_MIN_OFFICIAL_WEBSITE_VERIFIED_RATE = 0.5
DEFAULT_MIN_STAFF_FACTS_RATE = 0.2
DEFAULT_MIN_JOB_POSTING_INTENT_RATE = 0.05
DEFAULT_MIN_DECISION_MAKER_CANDIDATE_RATE = 0.25
DEFAULT_MIN_BUSINESS_EMAIL_RATE = 0.2
DEFAULT_MIN_VERIFIED_EMAIL_RATE = 0.15
DEFAULT_MIN_VERIFIED_DECISION_MAKER_EMAIL_RATE = 0.1
DEFAULT_MAX_PROVIDER_ERROR_RATE = 0.1

RELATED_COMMANDS: tuple[str, ...] = (
    "discover-nppes",
    "enrich-websites",
    "enrich-contacts",
    "contact-enrichment-metrics",
    "verify-emails",
    "email-verification-metrics",
    "queue-phone-verification",
    "list-phone-verification",
    PLAN_CLI_COMMAND,
    REPORT_CLI_COMMAND,
)
RELATED_ROUTES: tuple[str, ...] = (
    "/internal/discovery/nppes",
    "/internal/contact-enrichment/metrics",
    "/internal/email-verification/metrics",
    "/internal/phone-verification/tasks",
    PLAN_HTTP_ROUTE,
    REPORT_HTTP_ROUTE,
)
PLANNED_STAGES: tuple[tuple[str, str, str | None], ...] = (
    ("nppes_discovery", "discover-nppes", "/internal/discovery/nppes"),
    ("website_enrichment", "enrich-websites", None),
    ("decision_maker_enrichment", "enrich-contacts", None),
    ("email_verification", "verify-emails", None),
    (
        "human_phone_verification_queue",
        "queue-phone-verification",
        "/internal/phone-verification/tasks",
    ),
    (
        "contact_enrichment_metrics",
        "contact-enrichment-metrics",
        "/internal/contact-enrichment/metrics",
    ),
    (
        "email_verification_metrics",
        "email-verification-metrics",
        "/internal/email-verification/metrics",
    ),
    ("contact_validation_report", REPORT_CLI_COMMAND, REPORT_HTTP_ROUTE),
)


class ContactValidationError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class ContactValidationFilters:
    state: str | None = None
    city: str | None = None
    specialty: str | None = None
    taxonomy_description: str | None = None
    max_cohort_size: int = DEFAULT_COHORT_SIZE


@dataclass(frozen=True)
class ContactValidationSegment:
    state: str | None
    city: str | None
    specialty: str | None
    taxonomy_description: str | None
    max_cohort_size: int
    organizations_matching_filters: int
    planned_cohort_size: int


@dataclass(frozen=True)
class ContactValidationStage:
    code: str
    command_name: str
    json_route: str | None
    mode: str
    executed: bool
    live_provider_called: bool


@dataclass(frozen=True)
class OwnerReviewThreshold:
    code: str
    metric: str
    comparator: str
    threshold: float
    applied_to_live_settings: bool
    scoring_thresholds_changed: bool


@dataclass(frozen=True)
class ThresholdComparison:
    code: str
    metric: str
    observed: float
    threshold: float
    comparator: str
    passed: bool
    blocking: bool
    no_contact_found_is_failure: bool


@dataclass(frozen=True)
class ContactValidationPlan:
    generated_at: datetime
    packet_kind: str
    purpose: str
    overall_status: str
    read_only: bool
    dry_run_only: bool
    no_execution: bool
    no_outbound: bool
    no_provider_calls: bool
    no_spend: bool
    no_deployment: bool
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
    live_providers_enabled: bool
    live_providers: dict[str, bool]
    decision_maker_live_enabled: bool
    email_verification_live_enabled: bool
    email_verification_smtp_enabled: bool
    contact_validation_is_not_outbound: bool
    contact_validation_is_not_live_send: bool
    supervised_validation_run_permitted: bool
    funnel_strong_enough_for_supervised_validation: bool
    no_contact_found_is_normal_outcome: bool
    no_contact_found_is_failure: bool
    segment: ContactValidationSegment
    planned_stages: tuple[ContactValidationStage, ...]
    owner_review_thresholds: tuple[OwnerReviewThreshold, ...]
    related_commands: tuple[str, ...]
    related_routes: tuple[str, ...]
    local_git: LocalGitMetadata
    cli_command: str
    http_route: str


@dataclass(frozen=True)
class ContactValidationReport:
    generated_at: datetime
    packet_kind: str
    purpose: str
    overall_status: str
    read_only: bool
    dry_run_only: bool
    no_execution: bool
    no_outbound: bool
    no_provider_calls: bool
    no_spend: bool
    no_deployment: bool
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
    live_providers_enabled: bool
    live_providers: dict[str, bool]
    decision_maker_live_enabled: bool
    email_verification_live_enabled: bool
    email_verification_smtp_enabled: bool
    contact_validation_is_not_outbound: bool
    contact_validation_is_not_live_send: bool
    supervised_validation_run_permitted: bool
    funnel_strong_enough_for_supervised_validation: bool
    no_contact_found_is_normal_outcome: bool
    no_contact_found_is_failure: bool
    segment: ContactValidationSegment
    planned_stages: tuple[ContactValidationStage, ...]
    owner_review_thresholds: tuple[OwnerReviewThreshold, ...]
    threshold_comparisons: tuple[ThresholdComparison, ...]
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
    website_match_counts: dict[str, int]
    phone_verification_by_status: dict[str, int]
    run_ids_by_source: dict[str, list[str]]
    run_counts_by_source: dict[str, int]
    related_commands: tuple[str, ...]
    related_routes: tuple[str, ...]
    local_git: LocalGitMetadata
    cli_command: str
    http_route: str


class ContactValidationService:
    """Read-only 200-practice contact-enrichment measurement. Never calls providers."""

    def build_plan(
        self,
        db: Session,
        settings: Settings,
        filters: ContactValidationFilters | None = None,
        *,
        repo_root: Path | None = None,
    ) -> ContactValidationPlan:
        halt_before = read_operator_halt(db)
        parsed = parse_contact_validation_filters(filters)
        matching = _matching_organization_count(db, parsed)
        segment = _segment(parsed, matching)
        local_git = inspect_local_git(repo_root or default_repo_root())
        halt_after = read_operator_halt(db)
        _assert_halt_unchanged(halt_before, halt_after)
        status = _plan_status(settings)
        return ContactValidationPlan(
            generated_at=datetime.now(tz=UTC),
            packet_kind=PACKET_KIND_PLAN,
            purpose=PACKET_PURPOSE,
            overall_status=status,
            **_safety_kwargs(settings, halt_before=halt_before, halt_after=halt_after),
            funnel_strong_enough_for_supervised_validation=False,
            no_contact_found_is_normal_outcome=True,
            no_contact_found_is_failure=False,
            segment=segment,
            planned_stages=_planned_stages(),
            owner_review_thresholds=_owner_review_thresholds(),
            related_commands=RELATED_COMMANDS,
            related_routes=RELATED_ROUTES,
            local_git=local_git,
            cli_command=PLAN_CLI_COMMAND,
            http_route=PLAN_HTTP_ROUTE,
        )

    def build_report(
        self,
        db: Session,
        settings: Settings,
        filters: ContactValidationFilters | None = None,
        *,
        repo_root: Path | None = None,
    ) -> ContactValidationReport:
        halt_before = read_operator_halt(db)
        parsed = parse_contact_validation_filters(filters)
        matching = _matching_organization_count(db, parsed)
        organizations = _select_cohort(db, parsed)
        considered_ids = tuple(row.id for row in organizations)
        contacts = _contacts_for(db, considered_ids)
        evidence = _evidence_for(db, considered_ids)
        phone_tasks = _phone_tasks_for(db, considered_ids)
        runs = _runs_for(db, considered_ids)
        discovery_runs = _discovery_runs_for(db, considered_ids)
        local_git = inspect_local_git(repo_root or default_repo_root())
        halt_after = read_operator_halt(db)
        _assert_halt_unchanged(halt_before, halt_after)

        considered = len(organizations)
        website_counts = _count_safe(
            (row.website_match_status for row in organizations),
            allowed=SAFE_WEBSITE_MATCH_STATUSES,
        )
        staff_orgs = {
            row.organization_id
            for row in evidence
            if row.claim_type == WebsiteFactType.STAFF_MEMBER.value
        }
        job_orgs = {
            row.organization_id
            for row in evidence
            if row.claim_type == WebsiteFactType.JOB_POSTING_SIGNAL.value
        }
        candidate_orgs = {row.organization_id for row in contacts}
        email_orgs = {row.organization_id for row in contacts if _has_text(row.email)}
        verified_email_orgs = {
            row.organization_id for row in contacts if _is_verified_email(row)
        }
        verified_role_email_orgs = {
            row.organization_id
            for row in contacts
            if row.role_category in SAFE_ROLE_CATEGORIES and _is_verified_email(row)
        }
        queued_phone_orgs = {
            row.organization_id
            for row in phone_tasks
            if row.status == ContactDiscoveryCallStatus.QUEUED.value
        }
        latest_contact_runs = _latest_runs(runs, DECISION_MAKER_SOURCE)
        no_contact_orgs = 0
        error_orgs = 0
        for organization in organizations:
            run = latest_contact_runs.get(organization.id)
            if run is not None and run.status == EnrichmentRunStatus.FAILED.value:
                error_orgs += 1
                continue
            if organization.id in candidate_orgs:
                continue
            if run is not None or organization.id in queued_phone_orgs:
                no_contact_orgs += 1

        no_verified_email_orgs = len(email_orgs - verified_email_orgs)
        phone_status_counts = _count_safe(
            (row.status for row in phone_tasks),
            allowed=SAFE_PHONE_QUEUE_STATUSES,
        )
        run_ids = _run_ids_by_source(runs, discovery_runs)
        comparisons = _threshold_comparisons(
            considered=considered,
            official_website_verified_rate=_rate(
                website_counts.get(WebsiteMatchStatus.VERIFIED.value, 0), considered
            ),
            staff_facts_found_rate=_rate(len(staff_orgs), considered),
            job_posting_intent_rate=_rate(len(job_orgs), considered),
            decision_maker_candidates_found_rate=_rate(len(candidate_orgs), considered),
            business_email_found_rate=_rate(len(email_orgs), considered),
            verified_email_rate=_rate(len(verified_email_orgs), considered),
            verified_decision_maker_role_email_rate=_rate(
                len(verified_role_email_orgs), considered
            ),
            provider_error_rate=_rate(error_orgs, considered),
        )
        funnel_ready = _funnel_ready(comparisons, settings)
        status = _report_status(
            settings=settings,
            considered=considered,
            comparisons=comparisons,
            funnel_ready=funnel_ready,
        )
        return ContactValidationReport(
            generated_at=datetime.now(tz=UTC),
            packet_kind=PACKET_KIND_REPORT,
            purpose=PACKET_PURPOSE,
            overall_status=status,
            **_safety_kwargs(settings, halt_before=halt_before, halt_after=halt_after),
            funnel_strong_enough_for_supervised_validation=funnel_ready,
            no_contact_found_is_normal_outcome=True,
            no_contact_found_is_failure=False,
            segment=_segment(parsed, matching),
            planned_stages=_planned_stages(),
            owner_review_thresholds=_owner_review_thresholds(),
            threshold_comparisons=comparisons,
            organizations_considered=considered,
            official_website_verified_count=website_counts.get(
                WebsiteMatchStatus.VERIFIED.value, 0
            ),
            official_website_ambiguous_count=website_counts.get(
                WebsiteMatchStatus.AMBIGUOUS.value, 0
            ),
            official_website_no_match_count=website_counts.get(
                WebsiteMatchStatus.NO_MATCH.value, 0
            ),
            official_website_unknown_count=website_counts.get(UNKNOWN_BUCKET, 0)
            + sum(1 for row in organizations if not row.website_match_status),
            staff_facts_found_count=len(staff_orgs),
            job_posting_intent_count=len(job_orgs),
            decision_maker_candidates_found_count=len(candidate_orgs),
            business_email_found_count=len(email_orgs),
            verified_email_count=len(verified_email_orgs),
            verified_decision_maker_role_email_count=len(verified_role_email_orgs),
            no_contact_found_count=no_contact_orgs,
            no_verified_email_count=no_verified_email_orgs,
            queued_human_phone_verification_count=len(queued_phone_orgs),
            provider_error_count=error_orgs,
            official_website_verified_rate=_rate(
                website_counts.get(WebsiteMatchStatus.VERIFIED.value, 0), considered
            ),
            staff_facts_found_rate=_rate(len(staff_orgs), considered),
            job_posting_intent_rate=_rate(len(job_orgs), considered),
            decision_maker_candidates_found_rate=_rate(len(candidate_orgs), considered),
            business_email_found_rate=_rate(len(email_orgs), considered),
            verified_email_rate=_rate(len(verified_email_orgs), considered),
            verified_decision_maker_role_email_rate=_rate(
                len(verified_role_email_orgs), considered
            ),
            no_contact_found_rate=_rate(no_contact_orgs, considered),
            no_verified_email_rate=_rate(no_verified_email_orgs, considered),
            queued_human_phone_verification_rate=_rate(len(queued_phone_orgs), considered),
            provider_error_rate=_rate(error_orgs, considered),
            website_match_counts=dict(sorted(website_counts.items())),
            phone_verification_by_status=dict(sorted(phone_status_counts.items())),
            run_ids_by_source=run_ids,
            run_counts_by_source={key: len(value) for key, value in run_ids.items()},
            related_commands=RELATED_COMMANDS,
            related_routes=RELATED_ROUTES,
            local_git=local_git,
            cli_command=REPORT_CLI_COMMAND,
            http_route=REPORT_HTTP_ROUTE,
        )


def parse_contact_validation_filters(
    filters: ContactValidationFilters | None,
) -> ContactValidationFilters:
    raw = filters or ContactValidationFilters()
    state = _optional_state(raw.state)
    city = _optional_place(raw.city)
    specialty = _optional_taxonomy(raw.specialty)
    taxonomy = _optional_taxonomy(raw.taxonomy_description)
    if specialty and taxonomy and specialty != taxonomy:
        raise ContactValidationError(
            "conflicting_specialty_filter",
            "specialty and taxonomy_description filters must match",
        )
    resolved_specialty = specialty or taxonomy
    max_cohort = raw.max_cohort_size
    if max_cohort < MIN_COHORT_SIZE or max_cohort > MAX_COHORT_SIZE:
        raise ContactValidationError(
            "invalid_cohort_size",
            f"max_cohort_size must be between {MIN_COHORT_SIZE} and {MAX_COHORT_SIZE}",
        )
    return ContactValidationFilters(
        state=state,
        city=city,
        specialty=resolved_specialty,
        taxonomy_description=resolved_specialty,
        max_cohort_size=max_cohort,
    )


def plan_payload(plan: ContactValidationPlan) -> dict[str, Any]:
    payload = {
        "generated_at": plan.generated_at.isoformat(),
        "packet_kind": plan.packet_kind,
        "purpose": plan.purpose,
        "overall_status": plan.overall_status,
        **_safety_payload(plan),
        "funnel_strong_enough_for_supervised_validation": (
            plan.funnel_strong_enough_for_supervised_validation
        ),
        "no_contact_found_is_normal_outcome": plan.no_contact_found_is_normal_outcome,
        "no_contact_found_is_failure": plan.no_contact_found_is_failure,
        "segment": _segment_payload(plan.segment),
        "planned_stages": [_stage_payload(stage) for stage in plan.planned_stages],
        "owner_review_thresholds": [
            _threshold_payload(item) for item in plan.owner_review_thresholds
        ],
        "related_commands": list(plan.related_commands),
        "related_routes": list(plan.related_routes),
        "local_git": _git_payload(plan.local_git),
        "cli_command": plan.cli_command,
        "http_route": plan.http_route,
    }
    return payload


def report_payload(report: ContactValidationReport) -> dict[str, Any]:
    return {
        "generated_at": report.generated_at.isoformat(),
        "packet_kind": report.packet_kind,
        "purpose": report.purpose,
        "overall_status": report.overall_status,
        **_safety_payload(report),
        "funnel_strong_enough_for_supervised_validation": (
            report.funnel_strong_enough_for_supervised_validation
        ),
        "no_contact_found_is_normal_outcome": report.no_contact_found_is_normal_outcome,
        "no_contact_found_is_failure": report.no_contact_found_is_failure,
        "segment": _segment_payload(report.segment),
        "planned_stages": [_stage_payload(stage) for stage in report.planned_stages],
        "owner_review_thresholds": [
            _threshold_payload(item) for item in report.owner_review_thresholds
        ],
        "threshold_comparisons": [
            _comparison_payload(item) for item in report.threshold_comparisons
        ],
        "organizations_considered": report.organizations_considered,
        "official_website_verified_count": report.official_website_verified_count,
        "official_website_ambiguous_count": report.official_website_ambiguous_count,
        "official_website_no_match_count": report.official_website_no_match_count,
        "official_website_unknown_count": report.official_website_unknown_count,
        "staff_facts_found_count": report.staff_facts_found_count,
        "job_posting_intent_count": report.job_posting_intent_count,
        "decision_maker_candidates_found_count": report.decision_maker_candidates_found_count,
        "business_email_found_count": report.business_email_found_count,
        "verified_email_count": report.verified_email_count,
        "verified_decision_maker_role_email_count": (
            report.verified_decision_maker_role_email_count
        ),
        "no_contact_found_count": report.no_contact_found_count,
        "no_verified_email_count": report.no_verified_email_count,
        "queued_human_phone_verification_count": (
            report.queued_human_phone_verification_count
        ),
        "provider_error_count": report.provider_error_count,
        "official_website_verified_rate": report.official_website_verified_rate,
        "staff_facts_found_rate": report.staff_facts_found_rate,
        "job_posting_intent_rate": report.job_posting_intent_rate,
        "decision_maker_candidates_found_rate": (
            report.decision_maker_candidates_found_rate
        ),
        "business_email_found_rate": report.business_email_found_rate,
        "verified_email_rate": report.verified_email_rate,
        "verified_decision_maker_role_email_rate": (
            report.verified_decision_maker_role_email_rate
        ),
        "no_contact_found_rate": report.no_contact_found_rate,
        "no_verified_email_rate": report.no_verified_email_rate,
        "queued_human_phone_verification_rate": (
            report.queued_human_phone_verification_rate
        ),
        "provider_error_rate": report.provider_error_rate,
        "website_match_counts": dict(report.website_match_counts),
        "phone_verification_by_status": dict(report.phone_verification_by_status),
        "run_ids_by_source": {
            key: list(value) for key, value in report.run_ids_by_source.items()
        },
        "run_counts_by_source": dict(report.run_counts_by_source),
        "related_commands": list(report.related_commands),
        "related_routes": list(report.related_routes),
        "local_git": _git_payload(report.local_git),
        "cli_command": report.cli_command,
        "http_route": report.http_route,
    }


def format_contact_validation_plan(
    plan: ContactValidationPlan,
    *,
    as_json: bool = False,
) -> str:
    payload = sanitize_mapping(plan_payload(plan))
    if as_json:
        return json.dumps(payload, sort_keys=True)
    return _format_plan_text(payload)


def format_contact_validation_report(
    report: ContactValidationReport,
    *,
    as_json: bool = False,
) -> str:
    payload = sanitize_mapping(report_payload(report))
    if as_json:
        return json.dumps(payload, sort_keys=True)
    return _format_report_text(payload)


def _safety_kwargs(
    settings: Settings,
    *,
    halt_before: HaltStatus,
    halt_after: HaltStatus,
) -> dict[str, Any]:
    return {
        "read_only": True,
        "dry_run_only": True,
        "no_execution": True,
        "no_outbound": True,
        "no_provider_calls": True,
        "no_spend": True,
        "no_deployment": True,
        "manual_review_only": True,
        "outbound_attempted": False,
        "live_call_attempted": False,
        "live_provider_calls_attempted": False,
        "smtp_attempted": False,
        "autodial_attempted": False,
        "campaign_enrolled": False,
        "booking_attempted": False,
        "meet_link_created": False,
        "ads_launched": False,
        "execution_allowed": False,
        "owner_approved": False,
        "spend_attempted": False,
        "campaign_launched": False,
        "halt_changed": False,
        "settings_applied": False,
        "scoring_thresholds_changed": False,
        "outbound_enabled": settings.outbound_enabled,
        "operator_halt_status": halt_after.value,
        "operator_halt_before": halt_before.value,
        "operator_halt_after": halt_after.value,
        "live_providers_enabled": any_live_provider_enabled(settings),
        "live_providers": dict(live_provider_flags(settings)),
        "decision_maker_live_enabled": settings.decision_maker_live_enabled,
        "email_verification_live_enabled": settings.email_verification_live_enabled,
        "email_verification_smtp_enabled": settings.email_verification_smtp_enabled,
        "contact_validation_is_not_outbound": True,
        "contact_validation_is_not_live_send": True,
        "supervised_validation_run_permitted": False,
    }


def _safety_payload(packet: ContactValidationPlan | ContactValidationReport) -> dict[str, Any]:
    return {
        "read_only": packet.read_only,
        "dry_run_only": packet.dry_run_only,
        "no_execution": packet.no_execution,
        "no_outbound": packet.no_outbound,
        "no_provider_calls": packet.no_provider_calls,
        "no_spend": packet.no_spend,
        "no_deployment": packet.no_deployment,
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
        "live_providers_enabled": packet.live_providers_enabled,
        "live_providers": dict(packet.live_providers),
        "decision_maker_live_enabled": packet.decision_maker_live_enabled,
        "email_verification_live_enabled": packet.email_verification_live_enabled,
        "email_verification_smtp_enabled": packet.email_verification_smtp_enabled,
        "contact_validation_is_not_outbound": packet.contact_validation_is_not_outbound,
        "contact_validation_is_not_live_send": packet.contact_validation_is_not_live_send,
        "supervised_validation_run_permitted": packet.supervised_validation_run_permitted,
    }


def _segment(filters: ContactValidationFilters, matching: int) -> ContactValidationSegment:
    planned = min(matching, filters.max_cohort_size) if matching else filters.max_cohort_size
    return ContactValidationSegment(
        state=filters.state,
        city=filters.city,
        specialty=filters.specialty,
        taxonomy_description=filters.taxonomy_description,
        max_cohort_size=filters.max_cohort_size,
        organizations_matching_filters=matching,
        planned_cohort_size=planned,
    )


def _planned_stages() -> tuple[ContactValidationStage, ...]:
    return tuple(
        ContactValidationStage(
            code=code,
            command_name=command_name,
            json_route=json_route,
            mode="existing_safe_stage_review_only",
            executed=False,
            live_provider_called=False,
        )
        for code, command_name, json_route in PLANNED_STAGES
    )


def _owner_review_thresholds() -> tuple[OwnerReviewThreshold, ...]:
    specs = (
        (
            "min_organizations_considered",
            "organizations_considered",
            "gte",
            float(DEFAULT_MIN_ORGANIZATIONS_CONSIDERED),
        ),
        (
            "min_official_website_verified_rate",
            "official_website_verified_rate",
            "gte",
            DEFAULT_MIN_OFFICIAL_WEBSITE_VERIFIED_RATE,
        ),
        ("min_staff_facts_rate", "staff_facts_found_rate", "gte", DEFAULT_MIN_STAFF_FACTS_RATE),
        (
            "min_job_posting_intent_rate",
            "job_posting_intent_rate",
            "gte",
            DEFAULT_MIN_JOB_POSTING_INTENT_RATE,
        ),
        (
            "min_decision_maker_candidate_rate",
            "decision_maker_candidates_found_rate",
            "gte",
            DEFAULT_MIN_DECISION_MAKER_CANDIDATE_RATE,
        ),
        (
            "min_business_email_rate",
            "business_email_found_rate",
            "gte",
            DEFAULT_MIN_BUSINESS_EMAIL_RATE,
        ),
        ("min_verified_email_rate", "verified_email_rate", "gte", DEFAULT_MIN_VERIFIED_EMAIL_RATE),
        (
            "min_verified_decision_maker_email_rate",
            "verified_decision_maker_role_email_rate",
            "gte",
            DEFAULT_MIN_VERIFIED_DECISION_MAKER_EMAIL_RATE,
        ),
        ("max_provider_error_rate", "provider_error_rate", "lte", DEFAULT_MAX_PROVIDER_ERROR_RATE),
    )
    return tuple(
        OwnerReviewThreshold(
            code=code,
            metric=metric,
            comparator=comparator,
            threshold=threshold,
            applied_to_live_settings=False,
            scoring_thresholds_changed=False,
        )
        for code, metric, comparator, threshold in specs
    )


def _threshold_comparisons(
    *,
    considered: int,
    official_website_verified_rate: float,
    staff_facts_found_rate: float,
    job_posting_intent_rate: float,
    decision_maker_candidates_found_rate: float,
    business_email_found_rate: float,
    verified_email_rate: float,
    verified_decision_maker_role_email_rate: float,
    provider_error_rate: float,
) -> tuple[ThresholdComparison, ...]:
    observed = {
        "organizations_considered": float(considered),
        "official_website_verified_rate": official_website_verified_rate,
        "staff_facts_found_rate": staff_facts_found_rate,
        "job_posting_intent_rate": job_posting_intent_rate,
        "decision_maker_candidates_found_rate": decision_maker_candidates_found_rate,
        "business_email_found_rate": business_email_found_rate,
        "verified_email_rate": verified_email_rate,
        "verified_decision_maker_role_email_rate": verified_decision_maker_role_email_rate,
        "provider_error_rate": provider_error_rate,
    }
    comparisons: list[ThresholdComparison] = []
    for threshold in _owner_review_thresholds():
        value = observed[threshold.metric]
        passed = _compare(value, threshold.comparator, threshold.threshold)
        comparisons.append(
            ThresholdComparison(
                code=threshold.code,
                metric=threshold.metric,
                observed=value,
                threshold=threshold.threshold,
                comparator=threshold.comparator,
                passed=passed,
                blocking=threshold.code == "max_provider_error_rate" and not passed,
                no_contact_found_is_failure=False,
            )
        )
    return tuple(comparisons)


def _funnel_ready(comparisons: Sequence[ThresholdComparison], settings: Settings) -> bool:
    if settings.outbound_enabled or any_live_provider_enabled(settings):
        return False
    return all(item.passed for item in comparisons)


def _plan_status(settings: Settings) -> str:
    if settings.outbound_enabled or any_live_provider_enabled(settings):
        return _checked_status(BLOCKED_STATUS)
    return _checked_status(INFO_STATUS)


def _report_status(
    *,
    settings: Settings,
    considered: int,
    comparisons: Sequence[ThresholdComparison],
    funnel_ready: bool,
) -> str:
    if settings.outbound_enabled or any_live_provider_enabled(settings):
        return _checked_status(BLOCKED_STATUS)
    if any(item.blocking and not item.passed for item in comparisons):
        return _checked_status(BLOCKED_STATUS)
    if funnel_ready:
        return _checked_status(READY_STATUS)
    if considered == 0:
        return _checked_status(INFO_STATUS)
    return _checked_status(WARNING_STATUS)


def _checked_status(status: str) -> str:
    if status not in OVERALL_STATUSES:
        raise RuntimeError(f"unhandled contact validation status: {status!r}")
    return status


def _assert_halt_unchanged(before: HaltStatus, after: HaltStatus) -> None:
    if after is not before:
        raise RuntimeError("contact validation must not change operator halt status")


def _matching_organization_count(db: Session, filters: ContactValidationFilters) -> int:
    query = select(func.count()).select_from(Organization)
    query = _apply_segment_filters(query, filters)
    return int(db.scalar(query) or 0)


def _select_cohort(
    db: Session, filters: ContactValidationFilters
) -> tuple[Organization, ...]:
    query = select(Organization).order_by(Organization.created_at.asc(), Organization.id.asc())
    query = _apply_segment_filters(query, filters)
    return tuple(db.scalars(query.limit(filters.max_cohort_size)).all())


def _apply_segment_filters(query: Any, filters: ContactValidationFilters) -> Any:
    if filters.state:
        query = query.where(Organization.state == filters.state)
    if filters.city:
        query = query.where(Organization.city == filters.city)
    if filters.specialty:
        query = query.where(func.lower(Organization.specialty) == filters.specialty.lower())
    return query


def _contacts_for(db: Session, organization_ids: Sequence[UUID]) -> tuple[Contact, ...]:
    if not organization_ids:
        return ()
    return tuple(
        db.scalars(select(Contact).where(Contact.organization_id.in_(organization_ids))).all()
    )


def _evidence_for(
    db: Session, organization_ids: Sequence[UUID]
) -> tuple[SourceEvidence, ...]:
    if not organization_ids:
        return ()
    return tuple(
        db.scalars(
            select(SourceEvidence).where(SourceEvidence.organization_id.in_(organization_ids))
        ).all()
    )


def _phone_tasks_for(
    db: Session, organization_ids: Sequence[UUID]
) -> tuple[ContactDiscoveryCall, ...]:
    if not organization_ids:
        return ()
    return tuple(
        db.scalars(
            select(ContactDiscoveryCall).where(
                ContactDiscoveryCall.organization_id.in_(organization_ids)
            )
        ).all()
    )


def _runs_for(db: Session, organization_ids: Sequence[UUID]) -> tuple[EnrichmentRun, ...]:
    if not organization_ids:
        return ()
    return tuple(
        db.scalars(
            select(EnrichmentRun)
            .where(EnrichmentRun.organization_id.in_(organization_ids))
            .order_by(EnrichmentRun.started_at.asc(), EnrichmentRun.created_at.asc())
        ).all()
    )


def _discovery_runs_for(
    db: Session, organization_ids: Sequence[UUID]
) -> tuple[DiscoveryRun, ...]:
    if not organization_ids:
        return ()
    evidence_run_ids = {
        row.discovery_run_id
        for row in db.scalars(
            select(SourceEvidence).where(SourceEvidence.organization_id.in_(organization_ids))
        ).all()
        if row.discovery_run_id is not None
    }
    if not evidence_run_ids:
        return ()
    return tuple(
        db.scalars(select(DiscoveryRun).where(DiscoveryRun.id.in_(tuple(evidence_run_ids)))).all()
    )


def _latest_runs(
    runs: Sequence[EnrichmentRun], source: str
) -> dict[UUID, EnrichmentRun]:
    latest: dict[UUID, EnrichmentRun] = {}
    for run in runs:
        if run.source != source:
            continue
        latest[run.organization_id] = run
    return latest


def _run_ids_by_source(
    runs: Sequence[EnrichmentRun],
    discovery_runs: Sequence[DiscoveryRun],
) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {
        NPPES_SOURCE: [],
        WEBSITE_ENRICHMENT_SOURCE: [],
        DECISION_MAKER_SOURCE: [],
        EMAIL_VERIFICATION_SOURCE: [],
    }
    for discovery_run in discovery_runs:
        if discovery_run.source == NPPES_SOURCE:
            grouped[NPPES_SOURCE].append(str(discovery_run.id))
    for enrichment_run in runs:
        if enrichment_run.source in grouped:
            grouped[enrichment_run.source].append(str(enrichment_run.id))
    return {
        key: sorted(set(values))[:MAX_COHORT_SIZE]
        for key, values in grouped.items()
    }


def _optional_state(value: str | None) -> str | None:
    text = _clean_filter(value)
    if text is None:
        return None
    if not STATE_RE.fullmatch(text):
        raise ContactValidationError("invalid_state_filter", "state must be a two-letter code")
    return text.upper()


def _optional_place(value: str | None) -> str | None:
    text = _clean_filter(value)
    if text is None:
        return None
    return text.upper()


def _optional_taxonomy(value: str | None) -> str | None:
    text = _clean_filter(value)
    if text is None:
        return None
    return text


def _clean_filter(value: str | None) -> str | None:
    if value is None:
        return None
    text = " ".join(value.split()).strip()
    if not text:
        return None
    if UNSAFE_FILTER_RE.search(text):
        raise ContactValidationError(
            "unsafe_filter",
            "filter values must not include secrets or emails",
        )
    if len(text) > 120:
        raise ContactValidationError(
            "filter_too_long",
            "filter values must be 120 characters or fewer",
        )
    return text


def _has_text(value: str | None) -> bool:
    return bool(value and value.strip())


def _is_verified_email(row: Contact) -> bool:
    if is_verified_safe_verdict(row.email_verification_verdict):
        return True
    return row.verification_status in {
        ContactVerificationStatus.PROVIDER_VERIFIED.value,
        ContactVerificationStatus.VERIFIER_VALID.value,
    }


def _rate(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 4)


def _count_safe(values: Iterable[str | None], *, allowed: frozenset[str]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for value in values:
        if isinstance(value, str) and value in allowed:
            counts[value] += 1
        elif value:
            counts[UNKNOWN_BUCKET] += 1
    return dict(counts)


def _compare(observed: float, comparator: str, threshold: float) -> bool:
    if comparator == "gte":
        return observed >= threshold
    if comparator == "lte":
        return observed <= threshold
    return _unknown_comparator(comparator)


def _unknown_comparator(comparator: str) -> Never:
    raise RuntimeError(f"unhandled threshold comparator: {comparator!r}")


def _segment_payload(segment: ContactValidationSegment) -> dict[str, Any]:
    return {
        "state": segment.state,
        "city": segment.city,
        "specialty": segment.specialty,
        "taxonomy_description": segment.taxonomy_description,
        "max_cohort_size": segment.max_cohort_size,
        "organizations_matching_filters": segment.organizations_matching_filters,
        "planned_cohort_size": segment.planned_cohort_size,
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


def _git_payload(git: LocalGitMetadata) -> dict[str, Any]:
    return {
        "available": git.available,
        "current_branch": git.current_branch,
        "current_sha": git.current_sha,
        "working_tree_status": git.working_tree_status,
        "git_provider_called": False,
        "github_actions_called": False,
    }


def _format_plan_text(payload: dict[str, Any]) -> str:
    segment = payload["segment"]
    return "\n".join(
        [
            "Contact enrichment validation plan:",
            (
                f"status={payload['overall_status']} "
                f"max_cohort_size={segment['max_cohort_size']} "
                f"matching={segment['organizations_matching_filters']} "
                f"planned={segment['planned_cohort_size']}"
            ),
            (
                f"state={segment['state'] or '-'} "
                f"city={segment['city'] or '-'} "
                f"specialty={segment['specialty'] or '-'}"
            ),
            (
                f"read_only={_bool_text(payload['read_only'])} "
                f"outbound_attempted={_bool_text(payload['outbound_attempted'])} "
                f"live_call_attempted={_bool_text(payload['live_call_attempted'])} "
                f"owner_approved={_bool_text(payload['owner_approved'])} "
                f"halt_changed={_bool_text(payload['halt_changed'])}"
            ),
            (
                "supervised_validation_run_permitted="
                f"{_bool_text(payload['supervised_validation_run_permitted'])} "
                "no_contact_found_is_failure="
                f"{_bool_text(payload['no_contact_found_is_failure'])}"
            ),
        ]
    )


def _format_report_text(payload: dict[str, Any]) -> str:
    return "\n".join(
        [
            "Contact enrichment validation report:",
            (
                f"status={payload['overall_status']} "
                f"considered={payload['organizations_considered']} "
                f"website_verified={payload['official_website_verified_count']} "
                f"staff_facts={payload['staff_facts_found_count']} "
                f"job_intent={payload['job_posting_intent_count']}"
            ),
            (
                f"decision_makers={payload['decision_maker_candidates_found_count']} "
                f"business_email={payload['business_email_found_count']} "
                f"verified_email={payload['verified_email_count']} "
                "verified_decision_maker_email="
                f"{payload['verified_decision_maker_role_email_count']}"
            ),
            (
                f"no_contact_found={payload['no_contact_found_count']} "
                f"no_verified_email={payload['no_verified_email_count']} "
                "queued_phone_verification="
                f"{payload['queued_human_phone_verification_count']} "
                f"provider_errors={payload['provider_error_count']}"
            ),
            (
                "funnel_strong_enough="
                f"{_bool_text(payload['funnel_strong_enough_for_supervised_validation'])} "
                "supervised_run_permitted="
                f"{_bool_text(payload['supervised_validation_run_permitted'])} "
                f"outbound_attempted={_bool_text(payload['outbound_attempted'])} "
                f"halt_changed={_bool_text(payload['halt_changed'])}"
            ),
        ]
    )


def _bool_text(value: object) -> str:
    return "true" if value is True else "false"
