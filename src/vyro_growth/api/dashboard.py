from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from vyro_growth.config import Settings
from vyro_growth.services.dashboard import DashboardAnalyticsService, DashboardSummary, SafetyCard


class LatestRunStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    phase: str
    implemented: bool
    status: str | None
    started_at: datetime | None
    finished_at: datetime | None
    run_id: UUID | None


class SafetyCardResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outbound_enabled: bool
    outbound_halted_settings: bool
    operator_halt_status: str
    operator_halt_reason: str | None
    operator_halt_updated_at: datetime | None
    openai_personalization_enabled: bool
    openai_reply_classification_enabled: bool
    smartlead_live_enabled: bool
    google_calendar_live_enabled: bool
    voice_live_enabled: bool
    planned_count: int
    skipped_count: int
    suppressed_count: int
    blocked_count: int
    suppression_records: int
    live_calendar_events: int
    live_meet_links: int
    live_phone_calls: int
    live_send_attempted_enrollments: int
    outbound_attempted_classifications: int
    booking_events_created: int
    booking_meet_links_created: int
    voice_calls_placed: int
    phi_fields_present: bool = False


class DiscoverySummaryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    organizations: int
    leads: int
    leads_by_stage: dict[str, int] = Field(default_factory=dict)
    discovery_runs: int
    records_fetched: int
    records_upserted: int
    records_skipped: int


class WebsiteEnrichmentSummaryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    organizations: int
    by_match_status: dict[str, int] = Field(default_factory=dict)
    enrichment_runs: int
    by_run_status: dict[str, int] = Field(default_factory=dict)


class DecisionMakerSummaryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contacts: int
    by_role_category: dict[str, int] = Field(default_factory=dict)
    enrichment_runs: int
    by_run_status: dict[str, int] = Field(default_factory=dict)


class ScoringSummaryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scores_total: int
    latest_scores: int
    by_band: dict[str, int] = Field(default_factory=dict)


class PersonalizationSummaryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    drafts: int
    by_readiness: dict[str, int] = Field(default_factory=dict)
    enrichment_runs: int


class OutreachPlanSummaryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_runs: int
    enrollments: int
    by_status: dict[str, int] = Field(default_factory=dict)
    planned_count: int
    skipped_count: int
    suppressed_count: int
    blocked_count: int


class ReplyClassificationSummaryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    classifications: int
    by_intent: dict[str, int] = Field(default_factory=dict)
    by_outcome: dict[str, int] = Field(default_factory=dict)


class BookingPlanSummaryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_runs: int
    plans: int
    by_status: dict[str, int] = Field(default_factory=dict)
    planned_count: int
    skipped_count: int
    suppressed_count: int
    blocked_count: int
    events_created: int
    meet_links_created: int


class VoiceQualificationSummaryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_runs: int
    plans: int
    by_status: dict[str, int] = Field(default_factory=dict)
    planned_count: int
    skipped_count: int
    suppressed_count: int
    blocked_count: int
    calls_placed: int
    live_call_attempted: int


class SuppressionSummaryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    records: int
    by_reason: dict[str, int] = Field(default_factory=dict)
    with_email: int
    with_domain: int
    with_phone: int
    with_organization: int


class DashboardSummaryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    generated_at: datetime
    read_only: bool = True
    safety: SafetyCardResponse
    discovery: DiscoverySummaryResponse
    website_enrichment: WebsiteEnrichmentSummaryResponse
    decision_maker_enrichment: DecisionMakerSummaryResponse
    scoring: ScoringSummaryResponse
    personalization: PersonalizationSummaryResponse
    outreach_plans: OutreachPlanSummaryResponse
    reply_classifications: ReplyClassificationSummaryResponse
    booking_plans: BookingPlanSummaryResponse
    voice_qualification_plans: VoiceQualificationSummaryResponse
    suppressions: SuppressionSummaryResponse
    latest_runs: list[LatestRunStatus]


def dashboard_summary_to_response(summary: DashboardSummary) -> DashboardSummaryResponse:
    return DashboardSummaryResponse.model_validate(asdict(summary))


def safety_card_to_response(card: SafetyCard) -> SafetyCardResponse:
    return SafetyCardResponse.model_validate(asdict(card))


def build_dashboard_summary_response(
    db: Session,
    settings: Settings,
    *,
    service: DashboardAnalyticsService | None = None,
) -> DashboardSummaryResponse:
    analytics = service or DashboardAnalyticsService()
    return dashboard_summary_to_response(analytics.summarize(db, settings))
