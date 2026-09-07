"""Read-only email-verification funnel JSON export.

Phase 69 exposes sanitized counts only. It never executes outbound, calls live
verifiers, or returns prospect identifiers.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from vyro_growth.config import Settings
from vyro_growth.services.email_verification_metrics import (
    CLI_COMMAND,
    HTTP_ROUTE,
    EmailVerificationFunnel,
    EmailVerificationMetricsService,
)


class EmailVerificationMetricsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    generated_at: datetime
    packet_kind: str = "email_verification_funnel"
    purpose: str = "email_verification_validation_only"
    read_only: bool = True
    dry_run_only: bool = True
    no_execution: bool = True
    outbound_attempted: bool = False
    live_call_attempted: bool = False
    smtp_attempted: bool = False
    execution_allowed: bool = False
    owner_approved: bool = False
    spend_attempted: bool = False
    campaign_launched: bool = False
    halt_changed: bool = False
    outbound_enabled: bool = False
    operator_halt_status: str
    operator_halt_before: str
    operator_halt_after: str
    live_providers_enabled: bool = False
    live_providers: dict[str, bool] = Field(default_factory=dict)
    email_verification_live_enabled: bool = False
    email_verification_smtp_enabled: bool = False
    email_verification_is_not_outbound: bool = True
    contacts_considered: int = 0
    contacts_with_business_email: int = 0
    contacts_with_verified_safe_email: int = 0
    no_verified_email_count: int = 0
    inferred_candidate_count: int = 0
    inferred_unverified_count: int = 0
    inferred_promoted_count: int = 0
    provider_error_count: int = 0
    verified_email_rate: float = 0.0
    no_verified_email_rate: float = 0.0
    inferred_candidate_rate: float = 0.0
    inferred_promoted_rate: float = 0.0
    verdicts_by_status: dict[str, int] = Field(default_factory=dict)
    outcomes_by_status: dict[str, int] = Field(default_factory=dict)
    inferred_by_status: dict[str, int] = Field(default_factory=dict)
    skipped_by_reason: dict[str, int] = Field(default_factory=dict)
    provider_errors_by_category: dict[str, int] = Field(default_factory=dict)
    cli_command: str = CLI_COMMAND
    http_route: str = HTTP_ROUTE


def metrics_to_response(metrics: EmailVerificationFunnel) -> EmailVerificationMetricsResponse:
    return EmailVerificationMetricsResponse(
        generated_at=metrics.generated_at,
        packet_kind=metrics.packet_kind,
        purpose=metrics.purpose,
        read_only=metrics.read_only,
        dry_run_only=metrics.dry_run_only,
        no_execution=metrics.no_execution,
        outbound_attempted=metrics.outbound_attempted,
        live_call_attempted=metrics.live_call_attempted,
        smtp_attempted=metrics.smtp_attempted,
        execution_allowed=metrics.execution_allowed,
        owner_approved=metrics.owner_approved,
        spend_attempted=metrics.spend_attempted,
        campaign_launched=metrics.campaign_launched,
        halt_changed=metrics.halt_changed,
        outbound_enabled=metrics.outbound_enabled,
        operator_halt_status=metrics.operator_halt_status,
        operator_halt_before=metrics.operator_halt_before,
        operator_halt_after=metrics.operator_halt_after,
        live_providers_enabled=metrics.live_providers_enabled,
        live_providers=dict(metrics.live_providers),
        email_verification_live_enabled=metrics.email_verification_live_enabled,
        email_verification_smtp_enabled=metrics.email_verification_smtp_enabled,
        email_verification_is_not_outbound=metrics.email_verification_is_not_outbound,
        contacts_considered=metrics.contacts_considered,
        contacts_with_business_email=metrics.contacts_with_business_email,
        contacts_with_verified_safe_email=metrics.contacts_with_verified_safe_email,
        no_verified_email_count=metrics.no_verified_email_count,
        inferred_candidate_count=metrics.inferred_candidate_count,
        inferred_unverified_count=metrics.inferred_unverified_count,
        inferred_promoted_count=metrics.inferred_promoted_count,
        provider_error_count=metrics.provider_error_count,
        verified_email_rate=metrics.verified_email_rate,
        no_verified_email_rate=metrics.no_verified_email_rate,
        inferred_candidate_rate=metrics.inferred_candidate_rate,
        inferred_promoted_rate=metrics.inferred_promoted_rate,
        verdicts_by_status=dict(metrics.verdicts_by_status),
        outcomes_by_status=dict(metrics.outcomes_by_status),
        inferred_by_status=dict(metrics.inferred_by_status),
        skipped_by_reason=dict(metrics.skipped_by_reason),
        provider_errors_by_category=dict(metrics.provider_errors_by_category),
        cli_command=metrics.cli_command,
        http_route=metrics.http_route,
    )


def build_email_verification_metrics_response(
    db: Session,
    settings: Settings,
    *,
    service: EmailVerificationMetricsService | None = None,
) -> EmailVerificationMetricsResponse:
    metrics_service = service or EmailVerificationMetricsService()
    return metrics_to_response(metrics_service.summarize(db, settings))
