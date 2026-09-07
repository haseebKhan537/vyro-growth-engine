"""Read-only contact-enrichment hit-rate JSON export.

Phase 66 exposes sanitized funnel counts only. It never executes outbound,
calls live paid providers, or returns prospect identifiers.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from vyro_growth.config import Settings
from vyro_growth.services.contact_enrichment_metrics import (
    CLI_COMMAND,
    HTTP_ROUTE,
    ContactEnrichmentHitRate,
    ContactEnrichmentMetricsService,
)


class ContactEnrichmentMetricsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    generated_at: datetime
    packet_kind: str = "contact_enrichment_hit_rate"
    purpose: str = "contact_enrichment_validation_only"
    read_only: bool = True
    dry_run_only: bool = True
    no_execution: bool = True
    outbound_attempted: bool = False
    live_call_attempted: bool = False
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
    decision_maker_live_enabled: bool = False
    contact_enrichment_is_not_outbound: bool = True
    organizations_considered: int = 0
    organizations_with_candidate: int = 0
    organizations_with_business_email: int = 0
    organizations_with_provider_verified_email: int = 0
    organizations_with_decision_maker_role: int = 0
    organizations_with_verified_decision_maker_email: int = 0
    no_contact_found_count: int = 0
    provider_error_count: int = 0
    candidate_count: int = 0
    organizations_with_candidate_rate: float = 0.0
    organizations_with_business_email_rate: float = 0.0
    organizations_with_provider_verified_email_rate: float = 0.0
    organizations_with_decision_maker_role_rate: float = 0.0
    organizations_with_verified_decision_maker_email_rate: float = 0.0
    no_contact_found_rate: float = 0.0
    provider_error_rate: float = 0.0
    candidates_by_role_category: dict[str, int] = Field(default_factory=dict)
    candidates_by_verification_status: dict[str, int] = Field(default_factory=dict)
    skipped_by_reason: dict[str, int] = Field(default_factory=dict)
    provider_errors_by_category: dict[str, int] = Field(default_factory=dict)
    cli_command: str = CLI_COMMAND
    http_route: str = HTTP_ROUTE


def metrics_to_response(metrics: ContactEnrichmentHitRate) -> ContactEnrichmentMetricsResponse:
    return ContactEnrichmentMetricsResponse(
        generated_at=metrics.generated_at,
        packet_kind=metrics.packet_kind,
        purpose=metrics.purpose,
        read_only=metrics.read_only,
        dry_run_only=metrics.dry_run_only,
        no_execution=metrics.no_execution,
        outbound_attempted=metrics.outbound_attempted,
        live_call_attempted=metrics.live_call_attempted,
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
        decision_maker_live_enabled=metrics.decision_maker_live_enabled,
        contact_enrichment_is_not_outbound=metrics.contact_enrichment_is_not_outbound,
        organizations_considered=metrics.organizations_considered,
        organizations_with_candidate=metrics.organizations_with_candidate,
        organizations_with_business_email=metrics.organizations_with_business_email,
        organizations_with_provider_verified_email=(
            metrics.organizations_with_provider_verified_email
        ),
        organizations_with_decision_maker_role=metrics.organizations_with_decision_maker_role,
        organizations_with_verified_decision_maker_email=(
            metrics.organizations_with_verified_decision_maker_email
        ),
        no_contact_found_count=metrics.no_contact_found_count,
        provider_error_count=metrics.provider_error_count,
        candidate_count=metrics.candidate_count,
        organizations_with_candidate_rate=metrics.organizations_with_candidate_rate,
        organizations_with_business_email_rate=metrics.organizations_with_business_email_rate,
        organizations_with_provider_verified_email_rate=(
            metrics.organizations_with_provider_verified_email_rate
        ),
        organizations_with_decision_maker_role_rate=(
            metrics.organizations_with_decision_maker_role_rate
        ),
        organizations_with_verified_decision_maker_email_rate=(
            metrics.organizations_with_verified_decision_maker_email_rate
        ),
        no_contact_found_rate=metrics.no_contact_found_rate,
        provider_error_rate=metrics.provider_error_rate,
        candidates_by_role_category=dict(metrics.candidates_by_role_category),
        candidates_by_verification_status=dict(metrics.candidates_by_verification_status),
        skipped_by_reason=dict(metrics.skipped_by_reason),
        provider_errors_by_category=dict(metrics.provider_errors_by_category),
        cli_command=metrics.cli_command,
        http_route=metrics.http_route,
    )


def build_contact_enrichment_metrics_response(
    db: Session,
    settings: Settings,
    *,
    service: ContactEnrichmentMetricsService | None = None,
) -> ContactEnrichmentMetricsResponse:
    metrics_service = service or ContactEnrichmentMetricsService()
    return metrics_to_response(metrics_service.summarize(db, settings))
