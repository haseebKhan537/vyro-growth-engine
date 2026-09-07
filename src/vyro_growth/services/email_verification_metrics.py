"""Sanitized email-verification funnel metrics.

Phase 69 reports verified-email rates and inference outcomes only. It never
exposes emails, phones, names, secrets, or unsafe errors.
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
    EmailCandidateOrigin,
    EmailVerificationOutcome,
    EmailVerificationVerdict,
    EnrichmentRunStatus,
)
from vyro_growth.models import Contact, EmailPatternCandidate, EnrichmentRun
from vyro_growth.observability import sanitize_mapping
from vyro_growth.providers.email_verification import (
    EMAIL_VERIFICATION_SOURCE,
    NO_VERIFIED_EMAIL,
    is_verified_safe_verdict,
)
from vyro_growth.services.operator_halt import read_operator_halt

PACKET_KIND = "email_verification_funnel"
PACKET_PURPOSE = "email_verification_validation_only"
CLI_COMMAND = "email-verification-metrics"
HTTP_ROUTE = "/internal/email-verification/metrics"
SAFE_ERROR_CATEGORIES = (
    "live_disabled",
    "missing_config",
    "retryable",
    "non_retryable",
    "malformed",
    "not_implemented",
    "smtp_forbidden",
    "timeout",
    "unknown",
)
SAFE_VERDICTS = frozenset(item.value for item in EmailVerificationVerdict)
SAFE_OUTCOMES = frozenset(item.value for item in EmailVerificationOutcome)
SAFE_ORIGINS = frozenset(item.value for item in EmailCandidateOrigin)
UNKNOWN_BUCKET = "unknown"


@dataclass(frozen=True)
class EmailVerificationFunnel:
    generated_at: datetime
    packet_kind: str
    purpose: str
    read_only: bool
    dry_run_only: bool
    no_execution: bool
    outbound_attempted: bool
    live_call_attempted: bool
    smtp_attempted: bool
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
    email_verification_live_enabled: bool
    email_verification_smtp_enabled: bool
    email_verification_is_not_outbound: bool
    contacts_considered: int
    contacts_with_business_email: int
    contacts_with_verified_safe_email: int
    no_verified_email_count: int
    inferred_candidate_count: int
    inferred_unverified_count: int
    inferred_promoted_count: int
    provider_error_count: int
    verified_email_rate: float
    no_verified_email_rate: float
    inferred_candidate_rate: float
    inferred_promoted_rate: float
    verdicts_by_status: dict[str, int]
    outcomes_by_status: dict[str, int]
    inferred_by_status: dict[str, int]
    skipped_by_reason: dict[str, int]
    provider_errors_by_category: dict[str, int]
    cli_command: str
    http_route: str


class EmailVerificationMetricsService:
    """Summarize stored verification/inference counts. Never calls providers."""

    def summarize(self, db: Session, settings: Settings) -> EmailVerificationFunnel:
        halt_before = read_operator_halt(db)
        contacts = tuple(db.scalars(select(Contact)).all())
        candidates = tuple(db.scalars(select(EmailPatternCandidate)).all())
        runs = db.scalars(
            select(EnrichmentRun)
            .where(EnrichmentRun.source == EMAIL_VERIFICATION_SOURCE)
            .order_by(EnrichmentRun.started_at.asc(), EnrichmentRun.created_at.asc())
        ).all()
        halt_after = read_operator_halt(db)
        if halt_after is not halt_before:
            raise RuntimeError("email verification metrics must not change operator halt status")

        with_email = [row for row in contacts if _has_text(row.email)]
        verified = [
            row for row in with_email if is_verified_safe_verdict(row.email_verification_verdict)
        ]
        inferred_unverified = [
            row
            for row in candidates
            if not row.promoted
            and not is_verified_safe_verdict(row.verification_verdict)
        ]
        inferred_promoted = [row for row in candidates if row.promoted]
        no_verified = max(len(with_email) - len(verified), 0)

        error_runs = 0
        error_categories: Counter[str] = Counter()
        skip_reasons: Counter[str] = Counter()
        for run in runs:
            if run.status == EnrichmentRunStatus.FAILED.value:
                error_runs += 1
                error_categories[_error_category(run.error_message)] += 1
                continue
            skip_reasons.update(_skip_reasons_from_run(run))
        if no_verified and NO_VERIFIED_EMAIL not in skip_reasons:
            skip_reasons[NO_VERIFIED_EMAIL] += no_verified

        considered = len(contacts)
        return EmailVerificationFunnel(
            generated_at=datetime.now(tz=UTC),
            packet_kind=PACKET_KIND,
            purpose=PACKET_PURPOSE,
            read_only=True,
            dry_run_only=True,
            no_execution=True,
            outbound_attempted=False,
            live_call_attempted=False,
            smtp_attempted=False,
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
            email_verification_live_enabled=settings.email_verification_live_enabled,
            email_verification_smtp_enabled=settings.email_verification_smtp_enabled,
            email_verification_is_not_outbound=True,
            contacts_considered=considered,
            contacts_with_business_email=len(with_email),
            contacts_with_verified_safe_email=len(verified),
            no_verified_email_count=no_verified,
            inferred_candidate_count=len(candidates),
            inferred_unverified_count=len(inferred_unverified),
            inferred_promoted_count=len(inferred_promoted),
            provider_error_count=error_runs,
            verified_email_rate=_rate(len(verified), len(with_email)),
            no_verified_email_rate=_rate(no_verified, len(with_email)),
            inferred_candidate_rate=_rate(len(candidates), considered),
            inferred_promoted_rate=_rate(len(inferred_promoted), len(candidates)),
            verdicts_by_status=_count_safe(
                (row.email_verification_verdict for row in with_email),
                allowed=SAFE_VERDICTS,
            ),
            outcomes_by_status=_outcome_counts(
                verified_count=len(verified),
                no_verified=no_verified,
            ),
            inferred_by_status=_count_safe(
                (row.verification_verdict for row in candidates),
                allowed=SAFE_VERDICTS,
            ),
            skipped_by_reason=dict(sorted(skip_reasons.items())),
            provider_errors_by_category=dict(sorted(error_categories.items())),
            cli_command=CLI_COMMAND,
            http_route=HTTP_ROUTE,
        )


def metrics_payload(metrics: EmailVerificationFunnel) -> dict[str, Any]:
    return {
        "generated_at": metrics.generated_at.isoformat(),
        "packet_kind": metrics.packet_kind,
        "purpose": metrics.purpose,
        "read_only": metrics.read_only,
        "dry_run_only": metrics.dry_run_only,
        "no_execution": metrics.no_execution,
        "outbound_attempted": metrics.outbound_attempted,
        "live_call_attempted": metrics.live_call_attempted,
        "smtp_attempted": metrics.smtp_attempted,
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
        "email_verification_live_enabled": metrics.email_verification_live_enabled,
        "email_verification_smtp_enabled": metrics.email_verification_smtp_enabled,
        "email_verification_is_not_outbound": metrics.email_verification_is_not_outbound,
        "contacts_considered": metrics.contacts_considered,
        "contacts_with_business_email": metrics.contacts_with_business_email,
        "contacts_with_verified_safe_email": metrics.contacts_with_verified_safe_email,
        "no_verified_email_count": metrics.no_verified_email_count,
        "inferred_candidate_count": metrics.inferred_candidate_count,
        "inferred_unverified_count": metrics.inferred_unverified_count,
        "inferred_promoted_count": metrics.inferred_promoted_count,
        "provider_error_count": metrics.provider_error_count,
        "verified_email_rate": metrics.verified_email_rate,
        "no_verified_email_rate": metrics.no_verified_email_rate,
        "inferred_candidate_rate": metrics.inferred_candidate_rate,
        "inferred_promoted_rate": metrics.inferred_promoted_rate,
        "verdicts_by_status": dict(metrics.verdicts_by_status),
        "outcomes_by_status": dict(metrics.outcomes_by_status),
        "inferred_by_status": dict(metrics.inferred_by_status),
        "skipped_by_reason": dict(metrics.skipped_by_reason),
        "provider_errors_by_category": dict(metrics.provider_errors_by_category),
        "cli_command": metrics.cli_command,
        "http_route": metrics.http_route,
    }


def format_email_verification_metrics(
    metrics: EmailVerificationFunnel,
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
            "Email verification funnel:",
            (
                f"considered={payload['contacts_considered']} "
                f"business_email={payload['contacts_with_business_email']} "
                f"verified_safe={payload['contacts_with_verified_safe_email']} "
                f"no_verified_email={payload['no_verified_email_count']}"
            ),
            (
                f"inferred={payload['inferred_candidate_count']} "
                f"inferred_unverified={payload['inferred_unverified_count']} "
                f"inferred_promoted={payload['inferred_promoted_count']} "
                f"provider_errors={payload['provider_error_count']}"
            ),
            (
                f"verified_email_rate={payload['verified_email_rate']} "
                f"no_verified_email_rate={payload['no_verified_email_rate']} "
                f"inferred_promoted_rate={payload['inferred_promoted_rate']}"
            ),
            (
                f"read_only={_bool_text(payload['read_only'])} "
                f"outbound_attempted={_bool_text(payload['outbound_attempted'])} "
                f"live_call_attempted={_bool_text(payload['live_call_attempted'])} "
                f"smtp_attempted={_bool_text(payload['smtp_attempted'])} "
                f"halt_changed={_bool_text(payload['halt_changed'])}"
            ),
            (
                "email_verification_is_not_outbound="
                f"{_bool_text(payload['email_verification_is_not_outbound'])} "
                f"email_verification_live_enabled="
                f"{_bool_text(payload['email_verification_live_enabled'])}"
            ),
        ]
    )


def _has_text(value: str | None) -> bool:
    return bool(value and value.strip())


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
    return dict(sorted(counts.items()))


def _outcome_counts(*, verified_count: int, no_verified: int) -> dict[str, int]:
    counts: dict[str, int] = {}
    if verified_count:
        counts[EmailVerificationOutcome.VERIFIED.value] = verified_count
    if no_verified:
        counts[EmailVerificationOutcome.NO_VERIFIED_EMAIL.value] = no_verified
    return counts


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
        if isinstance(reason, str) and reason == NO_VERIFIED_EMAIL:
            counts[NO_VERIFIED_EMAIL] += 1
        else:
            counts[UNKNOWN_BUCKET] += 1
    return counts


def _error_category(error_message: str | None) -> str:
    text = (error_message or "").lower()
    if "disabled" in text:
        category = "live_disabled"
    elif "smtp" in text:
        category = "smtp_forbidden"
    elif "api key" in text or "base url" in text or "not configured" in text:
        category = "missing_config"
    elif "timed out" in text or "timeout" in text:
        category = "timeout"
    elif "not implemented" in text or "does not perform live" in text:
        category = "not_implemented"
    elif "malformed" in text or "not valid json" in text:
        category = "malformed"
    else:
        category = "unknown"
    if category not in SAFE_ERROR_CATEGORIES:
        return "unknown"
    return category


def _bool_text(value: object) -> str:
    return "true" if value is True else "false"
