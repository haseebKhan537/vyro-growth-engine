"""Sanitized contact-enrichment hit-rate metrics.

Phase 66 measures whether stored professional contacts exist at a practical
hit rate. It does not send email, enroll campaigns, place calls, book meetings,
spend money, publish content, or call live paid providers.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from vyro_growth.config import Settings, any_live_provider_enabled, live_provider_flags
from vyro_growth.domain import (
    ContactRoleCategory,
    ContactVerificationStatus,
    EnrichmentRunStatus,
)
from vyro_growth.models import Contact, EnrichmentRun
from vyro_growth.observability import sanitize_mapping
from vyro_growth.providers.decision_makers import (
    DECISION_MAKER_SOURCE,
    NO_CONTACT_FOUND,
    ContactSkipReason,
    skip_reason_value,
)
from vyro_growth.services.operator_halt import read_operator_halt

PACKET_KIND = "contact_enrichment_hit_rate"
PACKET_PURPOSE = "contact_enrichment_validation_only"
CLI_COMMAND = "contact-enrichment-metrics"
HTTP_ROUTE = "/internal/contact-enrichment/metrics"
SAFE_ERROR_CATEGORIES = (
    "live_disabled",
    "missing_config",
    "retryable",
    "non_retryable",
    "malformed",
    "not_implemented",
    "timeout",
    "unknown",
)
SAFE_SKIP_REASONS = frozenset(skip_reason_value(reason) for reason in ContactSkipReason)
SAFE_ROLE_CATEGORIES = frozenset(category.value for category in ContactRoleCategory)
SAFE_VERIFICATION_STATUSES = frozenset(status.value for status in ContactVerificationStatus)
UNKNOWN_BUCKET = "unknown"


@dataclass(frozen=True)
class ContactEnrichmentHitRate:
    generated_at: datetime
    packet_kind: str
    purpose: str
    read_only: bool
    dry_run_only: bool
    no_execution: bool
    outbound_attempted: bool
    live_call_attempted: bool
    execution_allowed: bool
    owner_approved: bool
    spend_attempted: bool
    campaign_launched: bool
    halt_changed: bool
    outbound_enabled: bool
    operator_halt_status: str
    operator_halt_before: str
    operator_halt_after: str
    live_providers_enabled: bool
    live_providers: dict[str, bool]
    decision_maker_live_enabled: bool
    contact_enrichment_is_not_outbound: bool
    organizations_considered: int
    organizations_with_candidate: int
    organizations_with_business_email: int
    organizations_with_provider_verified_email: int
    organizations_with_decision_maker_role: int
    organizations_with_verified_decision_maker_email: int
    no_contact_found_count: int
    provider_error_count: int
    candidate_count: int
    organizations_with_candidate_rate: float
    organizations_with_business_email_rate: float
    organizations_with_provider_verified_email_rate: float
    organizations_with_decision_maker_role_rate: float
    organizations_with_verified_decision_maker_email_rate: float
    no_contact_found_rate: float
    provider_error_rate: float
    candidates_by_role_category: dict[str, int]
    candidates_by_verification_status: dict[str, int]
    skipped_by_reason: dict[str, int]
    provider_errors_by_category: dict[str, int]
    cli_command: str
    http_route: str


class ContactEnrichmentMetricsService:
    """Summarize stored contact-enrichment funnel counts. Never calls providers."""

    def summarize(self, db: Session, settings: Settings) -> ContactEnrichmentHitRate:
        halt_before = read_operator_halt(db)
        runs = db.scalars(
            select(EnrichmentRun)
            .where(EnrichmentRun.source == DECISION_MAKER_SOURCE)
            .order_by(EnrichmentRun.started_at.asc(), EnrichmentRun.created_at.asc())
        ).all()
        latest_by_org: dict[object, EnrichmentRun] = {}
        for run in runs:
            latest_by_org[run.organization_id] = run
        latest_runs = tuple(latest_by_org.values())
        considered_ids = tuple(latest_by_org)
        contacts: tuple[Contact, ...] = ()
        if considered_ids:
            contacts = tuple(
                db.scalars(
                    select(Contact).where(Contact.organization_id.in_(considered_ids))
                ).all()
            )
        halt_after = read_operator_halt(db)
        if halt_after is not halt_before:
            raise RuntimeError("contact enrichment metrics must not change operator halt status")

        orgs_with_candidate = {row.organization_id for row in contacts}
        orgs_with_email = {
            row.organization_id for row in contacts if _has_text(row.email)
        }
        orgs_with_verified_email = {
            row.organization_id
            for row in contacts
            if _has_text(row.email) and _is_provider_verified(row.verification_status)
        }
        orgs_with_role = {
            row.organization_id
            for row in contacts
            if row.role_category in SAFE_ROLE_CATEGORIES
        }
        orgs_with_verified_role_email = {
            row.organization_id
            for row in contacts
            if row.role_category in SAFE_ROLE_CATEGORIES
            and _has_text(row.email)
            and _is_provider_verified(row.verification_status)
        }

        no_contact_orgs = 0
        error_orgs = 0
        error_categories: Counter[str] = Counter()
        skip_reasons: Counter[str] = Counter()
        for run in latest_runs:
            if run.status == EnrichmentRunStatus.FAILED.value:
                error_orgs += 1
                error_categories[_error_category(run.error_message)] += 1
                continue
            if run.organization_id not in orgs_with_candidate:
                no_contact_orgs += 1
                skip_reasons[NO_CONTACT_FOUND] += 1
            skip_reasons.update(_skip_reasons_from_run(run))

        considered = len(considered_ids)
        role_counts = _count_safe(
            (row.role_category for row in contacts),
            allowed=SAFE_ROLE_CATEGORIES,
        )
        verification_counts = _count_safe(
            (row.verification_status for row in contacts),
            allowed=SAFE_VERIFICATION_STATUSES,
        )

        return ContactEnrichmentHitRate(
            generated_at=datetime.now(tz=UTC),
            packet_kind=PACKET_KIND,
            purpose=PACKET_PURPOSE,
            read_only=True,
            dry_run_only=True,
            no_execution=True,
            outbound_attempted=False,
            live_call_attempted=False,
            execution_allowed=False,
            owner_approved=False,
            spend_attempted=False,
            campaign_launched=False,
            halt_changed=False,
            outbound_enabled=settings.outbound_enabled,
            operator_halt_status=halt_after.value,
            operator_halt_before=halt_before.value,
            operator_halt_after=halt_after.value,
            live_providers_enabled=any_live_provider_enabled(settings),
            live_providers=dict(live_provider_flags(settings)),
            decision_maker_live_enabled=settings.decision_maker_live_enabled,
            contact_enrichment_is_not_outbound=True,
            organizations_considered=considered,
            organizations_with_candidate=len(orgs_with_candidate),
            organizations_with_business_email=len(orgs_with_email),
            organizations_with_provider_verified_email=len(orgs_with_verified_email),
            organizations_with_decision_maker_role=len(orgs_with_role),
            organizations_with_verified_decision_maker_email=len(orgs_with_verified_role_email),
            no_contact_found_count=no_contact_orgs,
            provider_error_count=error_orgs,
            candidate_count=len(contacts),
            organizations_with_candidate_rate=_rate(len(orgs_with_candidate), considered),
            organizations_with_business_email_rate=_rate(len(orgs_with_email), considered),
            organizations_with_provider_verified_email_rate=_rate(
                len(orgs_with_verified_email), considered
            ),
            organizations_with_decision_maker_role_rate=_rate(len(orgs_with_role), considered),
            organizations_with_verified_decision_maker_email_rate=_rate(
                len(orgs_with_verified_role_email), considered
            ),
            no_contact_found_rate=_rate(no_contact_orgs, considered),
            provider_error_rate=_rate(error_orgs, considered),
            candidates_by_role_category=dict(sorted(role_counts.items())),
            candidates_by_verification_status=dict(sorted(verification_counts.items())),
            skipped_by_reason=dict(sorted(skip_reasons.items())),
            provider_errors_by_category=dict(sorted(error_categories.items())),
            cli_command=CLI_COMMAND,
            http_route=HTTP_ROUTE,
        )


def metrics_payload(metrics: ContactEnrichmentHitRate) -> dict[str, Any]:
    return {
        "generated_at": metrics.generated_at.isoformat(),
        "packet_kind": metrics.packet_kind,
        "purpose": metrics.purpose,
        "read_only": metrics.read_only,
        "dry_run_only": metrics.dry_run_only,
        "no_execution": metrics.no_execution,
        "outbound_attempted": metrics.outbound_attempted,
        "live_call_attempted": metrics.live_call_attempted,
        "execution_allowed": metrics.execution_allowed,
        "owner_approved": metrics.owner_approved,
        "spend_attempted": metrics.spend_attempted,
        "campaign_launched": metrics.campaign_launched,
        "halt_changed": metrics.halt_changed,
        "outbound_enabled": metrics.outbound_enabled,
        "operator_halt_status": metrics.operator_halt_status,
        "operator_halt_before": metrics.operator_halt_before,
        "operator_halt_after": metrics.operator_halt_after,
        "live_providers_enabled": metrics.live_providers_enabled,
        "live_providers": dict(metrics.live_providers),
        "decision_maker_live_enabled": metrics.decision_maker_live_enabled,
        "contact_enrichment_is_not_outbound": metrics.contact_enrichment_is_not_outbound,
        "organizations_considered": metrics.organizations_considered,
        "organizations_with_candidate": metrics.organizations_with_candidate,
        "organizations_with_business_email": metrics.organizations_with_business_email,
        "organizations_with_provider_verified_email": (
            metrics.organizations_with_provider_verified_email
        ),
        "organizations_with_decision_maker_role": metrics.organizations_with_decision_maker_role,
        "organizations_with_verified_decision_maker_email": (
            metrics.organizations_with_verified_decision_maker_email
        ),
        "no_contact_found_count": metrics.no_contact_found_count,
        "provider_error_count": metrics.provider_error_count,
        "candidate_count": metrics.candidate_count,
        "organizations_with_candidate_rate": metrics.organizations_with_candidate_rate,
        "organizations_with_business_email_rate": metrics.organizations_with_business_email_rate,
        "organizations_with_provider_verified_email_rate": (
            metrics.organizations_with_provider_verified_email_rate
        ),
        "organizations_with_decision_maker_role_rate": (
            metrics.organizations_with_decision_maker_role_rate
        ),
        "organizations_with_verified_decision_maker_email_rate": (
            metrics.organizations_with_verified_decision_maker_email_rate
        ),
        "no_contact_found_rate": metrics.no_contact_found_rate,
        "provider_error_rate": metrics.provider_error_rate,
        "candidates_by_role_category": dict(metrics.candidates_by_role_category),
        "candidates_by_verification_status": dict(metrics.candidates_by_verification_status),
        "skipped_by_reason": dict(metrics.skipped_by_reason),
        "provider_errors_by_category": dict(metrics.provider_errors_by_category),
        "cli_command": metrics.cli_command,
        "http_route": metrics.http_route,
    }


def format_contact_enrichment_metrics(
    metrics: ContactEnrichmentHitRate,
    *,
    as_json: bool = False,
) -> str:
    payload = sanitize_mapping(metrics_payload(metrics))
    if as_json:
        return json.dumps(payload, sort_keys=True)
    return _format_text(payload)


def _format_text(payload: dict[str, Any]) -> str:
    return "\n".join(
        [
            "Contact enrichment hit-rate:",
            (
                f"considered={payload['organizations_considered']} "
                f"with_candidate={payload['organizations_with_candidate']} "
                f"business_email={payload['organizations_with_business_email']} "
                f"verified_email={payload['organizations_with_provider_verified_email']}"
            ),
            (
                f"decision_maker_role={payload['organizations_with_decision_maker_role']} "
                "verified_decision_maker_email="
                f"{payload['organizations_with_verified_decision_maker_email']} "
                f"no_contact_found={payload['no_contact_found_count']} "
                f"provider_errors={payload['provider_error_count']}"
            ),
            (
                f"candidate_rate={payload['organizations_with_candidate_rate']} "
                "verified_decision_maker_email_rate="
                f"{payload['organizations_with_verified_decision_maker_email_rate']} "
                f"no_contact_found_rate={payload['no_contact_found_rate']}"
            ),
            (
                f"read_only={_bool_text(payload['read_only'])} "
                f"outbound_attempted={_bool_text(payload['outbound_attempted'])} "
                f"live_call_attempted={_bool_text(payload['live_call_attempted'])} "
                f"owner_approved={_bool_text(payload['owner_approved'])} "
                f"halt_changed={_bool_text(payload['halt_changed'])}"
            ),
            (
                "contact_enrichment_is_not_outbound="
                f"{_bool_text(payload['contact_enrichment_is_not_outbound'])} "
                f"decision_maker_live_enabled="
                f"{_bool_text(payload['decision_maker_live_enabled'])}"
            ),
        ]
    )


def _has_text(value: str | None) -> bool:
    return bool(value and value.strip())


def _is_provider_verified(value: str | None) -> bool:
    return value == ContactVerificationStatus.PROVIDER_VERIFIED.value


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


def _skip_reasons_from_run(run: EnrichmentRun) -> Counter[str]:
    counts: Counter[str] = Counter()
    params = run.input_params if isinstance(run.input_params, dict) else {}
    skipped = params.get("skip_reasons")
    if not isinstance(skipped, list):
        return counts
    for item in skipped:
        if not isinstance(item, dict):
            counts[UNKNOWN_BUCKET] += 1
            continue
        reason = item.get("reason")
        if isinstance(reason, str) and reason in SAFE_SKIP_REASONS:
            counts[reason] += 1
        else:
            counts[UNKNOWN_BUCKET] += 1
    return counts


def _error_category(error_message: str | None) -> str:
    text = (error_message or "").lower()
    if "disabled" in text:
        category = "live_disabled"
    elif "api key" in text or "base url" in text or "not configured" in text:
        category = "missing_config"
    elif "timed out" in text or "timeout" in text:
        category = "timeout"
    elif "not implemented" in text or "does not perform live" in text:
        category = "not_implemented"
    elif "malformed" in text or "not valid json" in text or "not a json object" in text:
        category = "malformed"
    elif any(code in text for code in ("429", "500", "502", "503", "504")):
        category = "retryable"
    elif any(code in text for code in ("401", "403", "400", "404", "422")):
        category = "non_retryable"
    else:
        category = "unknown"
    if category not in SAFE_ERROR_CATEGORIES:
        return "unknown"
    return category


def _bool_text(value: object) -> str:
    return "true" if value is True else "false"
