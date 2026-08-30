from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from vyro_growth.config import Settings
from vyro_growth.models import (
    GLOBAL_OPERATOR_CONTROL_KEY,
    BookingPlan,
    BookingPlanRun,
    CampaignEnrollment,
    Contact,
    DiscoveryRun,
    EnrichmentRun,
    Lead,
    LeadScore,
    Meeting,
    OperatorControl,
    Organization,
    OutreachPlanRun,
    PersonalizationDraft,
    ReplyClassification,
    Suppression,
    VoiceQualificationPlan,
    VoiceQualificationRun,
)
from vyro_growth.providers.decision_makers import DECISION_MAKER_SOURCE
from vyro_growth.providers.personalization import PERSONALIZATION_SOURCE
from vyro_growth.providers.website import WEBSITE_ENRICHMENT_SOURCE
from vyro_growth.services.lead_scoring import ScoreBand
from vyro_growth.services.operator_halt import read_operator_halt

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class LatestRunSnapshot:
    phase: str
    implemented: bool
    status: str | None
    started_at: datetime | None
    finished_at: datetime | None
    run_id: UUID | None


@dataclass(frozen=True)
class SafetyCard:
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
    phi_fields_present: bool


@dataclass(frozen=True)
class DiscoverySummary:
    organizations: int
    leads: int
    leads_by_stage: dict[str, int]
    discovery_runs: int
    records_fetched: int
    records_upserted: int
    records_skipped: int


@dataclass(frozen=True)
class WebsiteEnrichmentSummary:
    organizations: int
    by_match_status: dict[str, int]
    enrichment_runs: int
    by_run_status: dict[str, int]


@dataclass(frozen=True)
class DecisionMakerSummary:
    contacts: int
    by_role_category: dict[str, int]
    enrichment_runs: int
    by_run_status: dict[str, int]


@dataclass(frozen=True)
class ScoringSummary:
    scores_total: int
    latest_scores: int
    by_band: dict[str, int]


@dataclass(frozen=True)
class PersonalizationSummary:
    drafts: int
    by_readiness: dict[str, int]
    enrichment_runs: int


@dataclass(frozen=True)
class OutreachPlanSummary:
    plan_runs: int
    enrollments: int
    by_status: dict[str, int]
    planned_count: int
    skipped_count: int
    suppressed_count: int
    blocked_count: int


@dataclass(frozen=True)
class ReplyClassificationSummary:
    classifications: int
    by_intent: dict[str, int]
    by_outcome: dict[str, int]


@dataclass(frozen=True)
class BookingPlanSummary:
    plan_runs: int
    plans: int
    by_status: dict[str, int]
    planned_count: int
    skipped_count: int
    suppressed_count: int
    blocked_count: int
    events_created: int
    meet_links_created: int


@dataclass(frozen=True)
class VoiceQualificationSummary:
    plan_runs: int
    plans: int
    by_status: dict[str, int]
    planned_count: int
    skipped_count: int
    suppressed_count: int
    blocked_count: int
    calls_placed: int
    live_call_attempted: int


@dataclass(frozen=True)
class SuppressionSummary:
    records: int
    by_reason: dict[str, int]
    with_email: int
    with_domain: int
    with_phone: int
    with_organization: int


@dataclass(frozen=True)
class DashboardSummary:
    generated_at: datetime
    read_only: bool
    safety: SafetyCard
    discovery: DiscoverySummary
    website_enrichment: WebsiteEnrichmentSummary
    decision_maker_enrichment: DecisionMakerSummary
    scoring: ScoringSummary
    personalization: PersonalizationSummary
    outreach_plans: OutreachPlanSummary
    reply_classifications: ReplyClassificationSummary
    booking_plans: BookingPlanSummary
    voice_qualification_plans: VoiceQualificationSummary
    suppressions: SuppressionSummary
    latest_runs: tuple[LatestRunSnapshot, ...]


class DashboardAnalyticsService:
    """Read-only pipeline analytics. Does not write rows or call live providers."""

    def summarize(self, db: Session, settings: Settings) -> DashboardSummary:
        discovery = self._discovery(db)
        website = self._website(db)
        decision_makers = self._decision_makers(db)
        scoring = self._scoring(db)
        personalization = self._personalization(db)
        outreach = self._outreach(db)
        replies = self._replies(db)
        booking = self._booking(db)
        voice = self._voice(db)
        suppressions = self._suppressions(db)
        safety = self._safety(
            db,
            settings,
            outreach=outreach,
            replies=replies,
            booking=booking,
            voice=voice,
            suppressions=suppressions,
        )
        latest_runs = (
            self._latest_discovery(db),
            self._latest_enrichment(db, "website_enrichment", WEBSITE_ENRICHMENT_SOURCE),
            self._latest_enrichment(
                db, "decision_maker_enrichment", DECISION_MAKER_SOURCE
            ),
            self._latest_scoring(db),
            self._latest_enrichment(db, "personalization", PERSONALIZATION_SOURCE),
            self._latest_outreach(db),
            self._latest_replies(db),
            self._latest_booking(db),
            self._latest_voice(db),
        )
        summary = DashboardSummary(
            generated_at=datetime.now(tz=UTC),
            read_only=True,
            safety=safety,
            discovery=discovery,
            website_enrichment=website,
            decision_maker_enrichment=decision_makers,
            scoring=scoring,
            personalization=personalization,
            outreach_plans=outreach,
            reply_classifications=replies,
            booking_plans=booking,
            voice_qualification_plans=voice,
            suppressions=suppressions,
            latest_runs=latest_runs,
        )
        logger.info(
            "dashboard_summary_built",
            read_only=True,
            organizations=discovery.organizations,
            leads=discovery.leads,
            outbound_enabled=safety.outbound_enabled,
            operator_halt_status=safety.operator_halt_status,
        )
        return summary

    def _discovery(self, db: Session) -> DiscoverySummary:
        fetched = db.scalar(select(func.coalesce(func.sum(DiscoveryRun.records_fetched), 0)))
        upserted = db.scalar(select(func.coalesce(func.sum(DiscoveryRun.records_upserted), 0)))
        skipped = db.scalar(select(func.coalesce(func.sum(DiscoveryRun.records_skipped), 0)))
        return DiscoverySummary(
            organizations=_count_rows(db, Organization),
            leads=_count_rows(db, Lead),
            leads_by_stage=_counts_by(db, Lead.stage),
            discovery_runs=_count_rows(db, DiscoveryRun),
            records_fetched=int(fetched or 0),
            records_upserted=int(upserted or 0),
            records_skipped=int(skipped or 0),
        )

    def _website(self, db: Session) -> WebsiteEnrichmentSummary:
        return WebsiteEnrichmentSummary(
            organizations=_count_rows(db, Organization),
            by_match_status=_counts_by(db, Organization.website_match_status),
            enrichment_runs=_count_rows(
                db, EnrichmentRun, EnrichmentRun.source == WEBSITE_ENRICHMENT_SOURCE
            ),
            by_run_status=_counts_by_filtered(
                db,
                EnrichmentRun.status,
                EnrichmentRun.source == WEBSITE_ENRICHMENT_SOURCE,
            ),
        )

    def _decision_makers(self, db: Session) -> DecisionMakerSummary:
        return DecisionMakerSummary(
            contacts=_count_rows(db, Contact),
            by_role_category=_counts_by(db, Contact.role_category),
            enrichment_runs=_count_rows(
                db, EnrichmentRun, EnrichmentRun.source == DECISION_MAKER_SOURCE
            ),
            by_run_status=_counts_by_filtered(
                db,
                EnrichmentRun.status,
                EnrichmentRun.source == DECISION_MAKER_SOURCE,
            ),
        )

    def _scoring(self, db: Session) -> ScoringSummary:
        scores = db.scalars(
            select(LeadScore).order_by(LeadScore.created_at.desc(), LeadScore.id.desc())
        ).all()
        by_band = {band.value: 0 for band in ScoreBand}
        seen: set[UUID] = set()
        latest = 0
        for score in scores:
            if score.lead_id in seen:
                continue
            seen.add(score.lead_id)
            latest += 1
            rationale = score.rationale if isinstance(score.rationale, dict) else {}
            raw = rationale.get("band")
            if isinstance(raw, str) and raw in by_band:
                by_band[raw] += 1
        return ScoringSummary(
            scores_total=len(scores),
            latest_scores=latest,
            by_band=by_band,
        )

    def _personalization(self, db: Session) -> PersonalizationSummary:
        return PersonalizationSummary(
            drafts=_count_rows(db, PersonalizationDraft),
            by_readiness=_counts_by(db, PersonalizationDraft.readiness_status),
            enrichment_runs=_count_rows(
                db, EnrichmentRun, EnrichmentRun.source == PERSONALIZATION_SOURCE
            ),
        )

    def _outreach(self, db: Session) -> OutreachPlanSummary:
        by_status = _counts_by(db, CampaignEnrollment.status)
        return OutreachPlanSummary(
            plan_runs=_count_rows(db, OutreachPlanRun),
            enrollments=_count_rows(db, CampaignEnrollment),
            by_status=by_status,
            planned_count=by_status.get("planned", 0),
            skipped_count=by_status.get("skipped", 0),
            suppressed_count=by_status.get("suppressed", 0),
            blocked_count=by_status.get("blocked", 0),
        )

    def _replies(self, db: Session) -> ReplyClassificationSummary:
        return ReplyClassificationSummary(
            classifications=_count_rows(db, ReplyClassification),
            by_intent=_counts_by(db, ReplyClassification.intent),
            by_outcome=_counts_by(db, ReplyClassification.outcome),
        )

    def _booking(self, db: Session) -> BookingPlanSummary:
        by_status = _counts_by(db, BookingPlan.status)
        return BookingPlanSummary(
            plan_runs=_count_rows(db, BookingPlanRun),
            plans=_count_rows(db, BookingPlan),
            by_status=by_status,
            planned_count=by_status.get("planned", 0),
            skipped_count=by_status.get("skipped", 0),
            suppressed_count=by_status.get("suppressed", 0),
            blocked_count=by_status.get("blocked", 0),
            events_created=_count_rows(db, BookingPlan, BookingPlan.event_created.is_(True)),
            meet_links_created=_count_rows(
                db, BookingPlan, BookingPlan.meet_link_created.is_(True)
            ),
        )

    def _voice(self, db: Session) -> VoiceQualificationSummary:
        by_status = _counts_by(db, VoiceQualificationPlan.status)
        return VoiceQualificationSummary(
            plan_runs=_count_rows(db, VoiceQualificationRun),
            plans=_count_rows(db, VoiceQualificationPlan),
            by_status=by_status,
            planned_count=by_status.get("planned", 0),
            skipped_count=by_status.get("skipped", 0),
            suppressed_count=by_status.get("suppressed", 0),
            blocked_count=by_status.get("blocked", 0),
            calls_placed=_count_rows(
                db, VoiceQualificationPlan, VoiceQualificationPlan.call_placed.is_(True)
            ),
            live_call_attempted=_count_rows(
                db,
                VoiceQualificationPlan,
                VoiceQualificationPlan.live_call_attempted.is_(True),
            ),
        )

    def _suppressions(self, db: Session) -> SuppressionSummary:
        return SuppressionSummary(
            records=_count_rows(db, Suppression),
            by_reason=_counts_by(db, Suppression.reason),
            with_email=_count_rows(db, Suppression, Suppression.email.is_not(None)),
            with_domain=_count_rows(db, Suppression, Suppression.domain.is_not(None)),
            with_phone=_count_rows(db, Suppression, Suppression.phone.is_not(None)),
            with_organization=_count_rows(
                db, Suppression, Suppression.organization_id.is_not(None)
            ),
        )

    def _safety(
        self,
        db: Session,
        settings: Settings,
        *,
        outreach: OutreachPlanSummary,
        replies: ReplyClassificationSummary,
        booking: BookingPlanSummary,
        voice: VoiceQualificationSummary,
        suppressions: SuppressionSummary,
    ) -> SafetyCard:
        halt_status = read_operator_halt(db)
        control = db.get(OperatorControl, GLOBAL_OPERATOR_CONTROL_KEY)
        reply_outcomes = replies.by_outcome
        return SafetyCard(
            outbound_enabled=settings.outbound_enabled,
            outbound_halted_settings=settings.outbound_halted,
            operator_halt_status=halt_status.value,
            operator_halt_reason=control.reason if control is not None else None,
            operator_halt_updated_at=control.updated_at if control is not None else None,
            openai_personalization_enabled=settings.openai_personalization_enabled,
            openai_reply_classification_enabled=settings.openai_reply_classification_enabled,
            smartlead_live_enabled=settings.smartlead_live_enabled,
            google_calendar_live_enabled=settings.google_calendar_live_enabled,
            voice_live_enabled=settings.voice_live_enabled,
            planned_count=(
                outreach.planned_count + booking.planned_count + voice.planned_count
            ),
            skipped_count=(
                outreach.skipped_count
                + booking.skipped_count
                + voice.skipped_count
                + reply_outcomes.get("skipped", 0)
            ),
            suppressed_count=(
                outreach.suppressed_count
                + booking.suppressed_count
                + voice.suppressed_count
                + reply_outcomes.get("suppressed", 0)
            ),
            blocked_count=(
                outreach.blocked_count
                + booking.blocked_count
                + voice.blocked_count
                + reply_outcomes.get("blocked", 0)
            ),
            suppression_records=suppressions.records,
            live_calendar_events=_count_rows(
                db, Meeting, Meeting.provider_event_id.is_not(None)
            ),
            live_meet_links=_count_rows(db, Meeting, Meeting.meeting_url.is_not(None)),
            live_phone_calls=voice.calls_placed,
            live_send_attempted_enrollments=_count_rows(
                db, CampaignEnrollment, CampaignEnrollment.live_send_attempted.is_(True)
            ),
            outbound_attempted_classifications=_count_rows(
                db, ReplyClassification, ReplyClassification.outbound_attempted.is_(True)
            ),
            booking_events_created=booking.events_created,
            booking_meet_links_created=booking.meet_links_created,
            voice_calls_placed=voice.calls_placed,
            phi_fields_present=False,
        )

    def _latest_discovery(self, db: Session) -> LatestRunSnapshot:
        run = _latest_row(db, DiscoveryRun)
        if run is None:
            return _empty_run("discovery")
        return LatestRunSnapshot(
            phase="discovery",
            implemented=True,
            status=run.status,
            started_at=run.started_at,
            finished_at=run.finished_at,
            run_id=run.id,
        )

    def _latest_enrichment(self, db: Session, phase: str, source: str) -> LatestRunSnapshot:
        run = _latest_row(db, EnrichmentRun, EnrichmentRun.source == source)
        if run is None:
            return _empty_run(phase)
        return LatestRunSnapshot(
            phase=phase,
            implemented=True,
            status=run.status,
            started_at=run.started_at,
            finished_at=run.finished_at,
            run_id=run.id,
        )

    def _latest_scoring(self, db: Session) -> LatestRunSnapshot:
        score = _latest_row(db, LeadScore)
        if score is None:
            return _empty_run("scoring")
        return LatestRunSnapshot(
            phase="scoring",
            implemented=True,
            status="completed",
            started_at=score.created_at,
            finished_at=score.created_at,
            run_id=score.id,
        )

    def _latest_outreach(self, db: Session) -> LatestRunSnapshot:
        run = _latest_row(db, OutreachPlanRun)
        if run is None:
            return _empty_run("outreach_plans")
        return LatestRunSnapshot(
            phase="outreach_plans",
            implemented=True,
            status=run.status,
            started_at=run.started_at,
            finished_at=run.finished_at,
            run_id=run.id,
        )

    def _latest_replies(self, db: Session) -> LatestRunSnapshot:
        row = _latest_row(db, ReplyClassification)
        if row is None:
            return _empty_run("reply_classifications")
        return LatestRunSnapshot(
            phase="reply_classifications",
            implemented=True,
            status=row.outcome,
            started_at=row.created_at,
            finished_at=row.updated_at,
            run_id=row.id,
        )

    def _latest_booking(self, db: Session) -> LatestRunSnapshot:
        run = _latest_row(db, BookingPlanRun)
        if run is None:
            return _empty_run("booking_plans")
        return LatestRunSnapshot(
            phase="booking_plans",
            implemented=True,
            status=run.status,
            started_at=run.started_at,
            finished_at=run.finished_at,
            run_id=run.id,
        )

    def _latest_voice(self, db: Session) -> LatestRunSnapshot:
        run = _latest_row(db, VoiceQualificationRun)
        if run is None:
            return _empty_run("voice_qualification_plans")
        return LatestRunSnapshot(
            phase="voice_qualification_plans",
            implemented=True,
            status=run.status,
            started_at=run.started_at,
            finished_at=run.finished_at,
            run_id=run.id,
        )


def _empty_run(phase: str) -> LatestRunSnapshot:
    return LatestRunSnapshot(
        phase=phase,
        implemented=True,
        status="not_started",
        started_at=None,
        finished_at=None,
        run_id=None,
    )


def _count_rows(db: Session, model: type[Any], *clauses: Any) -> int:
    stmt = select(func.count()).select_from(model)
    if clauses:
        stmt = stmt.where(*clauses)
    return int(db.scalar(stmt) or 0)


def _counts_by(db: Session, column: Any) -> dict[str, int]:
    rows = db.execute(select(column, func.count()).group_by(column)).all()
    result: dict[str, int] = {}
    for key, count in rows:
        label = "unset" if key is None or key == "" else str(key)
        result[label] = int(count)
    return result


def _counts_by_filtered(db: Session, column: Any, *clauses: Any) -> dict[str, int]:
    stmt = select(column, func.count()).group_by(column)
    if clauses:
        stmt = stmt.where(*clauses)
    rows = db.execute(stmt).all()
    result: dict[str, int] = {}
    for key, count in rows:
        label = "unset" if key is None or key == "" else str(key)
        result[label] = int(count)
    return result


def _latest_row(db: Session, model: type[Any], *clauses: Any) -> Any | None:
    stmt = select(model)
    if clauses:
        stmt = stmt.where(*clauses)
    stmt = stmt.order_by(model.created_at.desc())
    return db.scalars(stmt).first()
