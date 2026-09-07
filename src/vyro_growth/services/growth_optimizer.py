"""Dry-run growth optimizer: operator-review recommendations only.

Reads stored dashboard/pipeline aggregates and writes recommendation drafts.
It never applies a recommendation, never changes campaigns or scoring
thresholds, and never calls live providers or sends outreach.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from vyro_growth.config import Settings
from vyro_growth.domain import (
    LeadStage,
    OptimizerRunStatus,
    RecommendationApprovalStatus,
    RecommendationCategory,
    RecommendationPriority,
)
from vyro_growth.models import (
    Activity,
    BookingPlan,
    CampaignEnrollment,
    Contact,
    Lead,
    LeadScore,
    OptimizerRecommendation,
    OptimizerRun,
    Organization,
    PersonalizationDraft,
    VoiceQualificationPlan,
)
from vyro_growth.services.dashboard import DashboardAnalyticsService, DashboardSummary
from vyro_growth.services.operator_halt import HaltStatus, read_operator_halt

logger = structlog.get_logger(__name__)

OPTIMIZER_ACTOR = "growth_optimizer"
OPTIMIZER_MODEL_VERSION = "growth-optimizer-v1"
CONVERSION_STAGES = frozenset(
    {
        LeadStage.INTERESTED.value,
        LeadStage.QUALIFICATION_PENDING.value,
        LeadStage.MEETING_READY.value,
        LeadStage.MEETING_BOOKED.value,
        LeadStage.WON.value,
    }
)
MIN_SCORING_SAMPLE = 2
MIN_COHORT_SAMPLE = 2


@dataclass(frozen=True)
class RecommendationDraft:
    recommendation_key: str
    category: RecommendationCategory
    priority: RecommendationPriority
    confidence: float
    title: str
    rationale: str
    source_metrics: dict[str, object]


@dataclass(frozen=True)
class OptimizerRecommendationView:
    id: UUID
    recommendation_key: str
    category: str
    priority: str
    confidence: float
    title: str
    rationale: str
    source_metrics: dict[str, object]
    generated_at: datetime
    approval_status: str
    applied: bool


@dataclass(frozen=True)
class OptimizerRunResult:
    optimizer_run_id: UUID
    status: OptimizerRunStatus
    model_version: str
    snapshot_fingerprint: str
    recommendation_count: int
    reused_existing: bool
    applied_count: int
    dry_run_only: bool
    outbound_attempted: bool
    live_call_attempted: bool
    generated_at: datetime
    operator_halt_before: str
    operator_halt_after: str
    recommendations: tuple[OptimizerRecommendationView, ...]


@dataclass(frozen=True)
class SpecialtyCohort:
    specialty: str
    state: str
    leads: int
    conversion_leads: int
    conversion_rate: float

    def as_metrics(self) -> dict[str, object]:
        return {
            "specialty": self.specialty,
            "state": self.state,
            "leads": self.leads,
            "conversion_leads": self.conversion_leads,
            "conversion_rate": self.conversion_rate,
        }


@dataclass(frozen=True)
class ExtraPipelineMetrics:
    orgs_without_verified_website: int
    orgs_without_contacts: int
    scored_leads_without_ready_draft: int
    outreach_skip_reasons: dict[str, int]
    booking_skip_reasons: dict[str, int]
    voice_skip_reasons: dict[str, int]
    specialty_geography: tuple[SpecialtyCohort, ...]


class GrowthOptimizerService:
    """Produce operator-review recommendation drafts from stored pipeline state."""

    def __init__(self, analytics: DashboardAnalyticsService | None = None) -> None:
        self._analytics = analytics or DashboardAnalyticsService()

    def recommend(
        self,
        db: Session,
        settings: Settings,
        *,
        commit: bool = True,
    ) -> OptimizerRunResult:
        halt_before = read_operator_halt(db)
        generated_at = datetime.now(tz=UTC)
        summary = self._analytics.summarize(db, settings)
        extra = self._extra_metrics(db)
        snapshot = _sanitized_snapshot(summary, extra)
        fingerprint = _fingerprint(snapshot)
        existing = db.scalar(
            select(OptimizerRun).where(OptimizerRun.snapshot_fingerprint == fingerprint)
        )
        if existing is not None:
            result = self._view(
                db,
                existing,
                halt_before=halt_before,
                halt_after=halt_before,
                reused=True,
            )
            logger.info(
                "optimizer_run_reused",
                optimizer_run_id=str(existing.id),
                recommendation_count=existing.recommendation_count,
                snapshot_fingerprint=fingerprint,
                outbound_attempted=False,
            )
            return result

        drafts = _build_recommendations(summary, extra)
        run = OptimizerRun(
            status=OptimizerRunStatus.COMPLETED.value,
            model_version=OPTIMIZER_MODEL_VERSION,
            snapshot_fingerprint=fingerprint,
            recommendation_count=len(drafts),
            reused_count=0,
            applied_count=0,
            dry_run_only=True,
            outbound_attempted=False,
            live_call_attempted=False,
            input_params={"dry_run_only": True, "auto_apply": False},
            snapshot_json=snapshot,
            started_at=generated_at,
            finished_at=generated_at,
        )
        db.add(run)
        db.flush()
        for draft in drafts:
            db.add(
                OptimizerRecommendation(
                    optimizer_run_id=run.id,
                    recommendation_key=draft.recommendation_key,
                    category=draft.category.value,
                    priority=draft.priority.value,
                    confidence=draft.confidence,
                    title=draft.title,
                    rationale=draft.rationale,
                    source_metrics_json=draft.source_metrics,
                    generated_at=generated_at,
                    approval_status=RecommendationApprovalStatus.PENDING_OPERATOR_REVIEW.value,
                    applied=False,
                    applied_at=None,
                )
            )
        db.add(
            Activity(
                lead_id=None,
                actor=OPTIMIZER_ACTOR,
                action="optimizer_recommendations_generated",
                details={
                    "optimizer_run_id": str(run.id),
                    "recommendation_count": len(drafts),
                    "categories": [draft.category.value for draft in drafts],
                    "applied_count": 0,
                    "dry_run_only": True,
                    "outbound_attempted": False,
                },
            )
        )
        db.flush()
        halt_after = read_operator_halt(db)
        if halt_after is not halt_before:
            raise RuntimeError("growth optimizer must not change operator halt status")
        if commit:
            db.commit()
            db.refresh(run)
        result = self._view(
            db,
            run,
            halt_before=halt_before,
            halt_after=halt_after,
            reused=False,
        )
        logger.info(
            "optimizer_run_completed",
            optimizer_run_id=str(run.id),
            recommendation_count=len(drafts),
            snapshot_fingerprint=fingerprint,
            outbound_attempted=False,
            applied_count=0,
        )
        return result

    def latest(self, db: Session) -> OptimizerRunResult | None:
        run = db.scalars(select(OptimizerRun).order_by(OptimizerRun.created_at.desc())).first()
        if run is None:
            return None
        halt = read_operator_halt(db)
        return self._view(db, run, halt_before=halt, halt_after=halt, reused=True)

    def _view(
        self,
        db: Session,
        run: OptimizerRun,
        *,
        halt_before: HaltStatus,
        halt_after: HaltStatus,
        reused: bool,
    ) -> OptimizerRunResult:
        rows = list(
            db.scalars(
                select(OptimizerRecommendation)
                .where(OptimizerRecommendation.optimizer_run_id == run.id)
                .order_by(
                    OptimizerRecommendation.category,
                    OptimizerRecommendation.recommendation_key,
                )
            )
        )
        return OptimizerRunResult(
            optimizer_run_id=run.id,
            status=OptimizerRunStatus(run.status),
            model_version=run.model_version,
            snapshot_fingerprint=run.snapshot_fingerprint,
            recommendation_count=run.recommendation_count,
            reused_existing=reused,
            applied_count=run.applied_count,
            dry_run_only=run.dry_run_only,
            outbound_attempted=run.outbound_attempted,
            live_call_attempted=run.live_call_attempted,
            generated_at=run.finished_at or run.created_at,
            operator_halt_before=halt_before.value,
            operator_halt_after=halt_after.value,
            recommendations=tuple(_recommendation_view(row) for row in rows),
        )

    def _extra_metrics(self, db: Session) -> ExtraPipelineMetrics:
        verified = _count_rows(
            db, Organization, Organization.website_match_status == "verified"
        )
        org_count = _count_rows(db, Organization)
        orgs_with_contacts = db.scalar(select(func.count(func.distinct(Contact.organization_id))))
        scored_leads = db.scalar(select(func.count(func.distinct(LeadScore.lead_id))))
        ready_draft_leads = db.scalar(
            select(func.count(func.distinct(PersonalizationDraft.lead_id))).where(
                PersonalizationDraft.readiness_status == "ready"
            )
        )
        return ExtraPipelineMetrics(
            orgs_without_verified_website=max(org_count - verified, 0),
            orgs_without_contacts=max(org_count - int(orgs_with_contacts or 0), 0),
            scored_leads_without_ready_draft=max(
                int(scored_leads or 0) - int(ready_draft_leads or 0), 0
            ),
            outreach_skip_reasons=_counts_by(db, CampaignEnrollment.skip_reason),
            booking_skip_reasons=_counts_by(db, BookingPlan.skip_reason),
            voice_skip_reasons=_counts_by(db, VoiceQualificationPlan.skip_reason),
            specialty_geography=_specialty_geography(db),
        )


def _recommendation_view(row: OptimizerRecommendation) -> OptimizerRecommendationView:
    metrics = row.source_metrics_json if isinstance(row.source_metrics_json, dict) else {}
    return OptimizerRecommendationView(
        id=row.id,
        recommendation_key=row.recommendation_key,
        category=row.category,
        priority=row.priority,
        confidence=row.confidence,
        title=row.title,
        rationale=row.rationale,
        source_metrics=dict(metrics),
        generated_at=row.generated_at,
        approval_status=row.approval_status,
        applied=row.applied,
    )


def _build_recommendations(
    summary: DashboardSummary,
    extra: ExtraPipelineMetrics,
) -> tuple[RecommendationDraft, ...]:
    drafts: list[RecommendationDraft] = []
    drafts.extend(_safety_recommendations(summary))
    drafts.extend(_scoring_recommendations(summary))
    drafts.extend(_specialty_recommendations(extra))
    drafts.extend(_website_recommendations(summary, extra))
    drafts.extend(_decision_maker_recommendations(summary, extra))
    drafts.extend(_personalization_recommendations(summary, extra))
    drafts.extend(_outreach_recommendations(summary, extra))
    drafts.extend(_reply_recommendations(summary))
    drafts.extend(_booking_recommendations(summary, extra))
    drafts.extend(_voice_recommendations(summary, extra))
    return tuple(drafts)


def _safety_recommendations(summary: DashboardSummary) -> list[RecommendationDraft]:
    safety = summary.safety
    drafts: list[RecommendationDraft] = []
    if safety.outbound_enabled:
        drafts.append(
            _draft(
                key="safety_outbound_enabled",
                category=RecommendationCategory.SAFETY_RISK,
                priority=RecommendationPriority.CRITICAL,
                confidence=0.99,
                title="Review safety: outbound is enabled",
                rationale=(
                    "OUTBOUND_ENABLED is true. This optimizer does not send mail or "
                    "change outbound settings; an operator should confirm the flag "
                    "is intentional."
                ),
                metrics={"outbound_enabled": True},
            )
        )
    live_flags = {
        "openai_personalization_enabled": safety.openai_personalization_enabled,
        "openai_reply_classification_enabled": safety.openai_reply_classification_enabled,
        "smartlead_live_enabled": safety.smartlead_live_enabled,
        "google_calendar_live_enabled": safety.google_calendar_live_enabled,
        "voice_live_enabled": safety.voice_live_enabled,
        "decision_maker_live_enabled": safety.decision_maker_live_enabled,
    }
    enabled_live = [name for name, enabled in live_flags.items() if enabled]
    if enabled_live:
        drafts.append(
            _draft(
                key="safety_live_provider_flags",
                category=RecommendationCategory.SAFETY_RISK,
                priority=RecommendationPriority.HIGH,
                confidence=0.99,
                title="Review safety: live provider flags are enabled",
                rationale=(
                    "One or more live-provider flags are true. The optimizer does not "
                    "call those providers; an operator should confirm they stay disabled "
                    "unless explicitly approved."
                ),
                metrics={"enabled_flags": enabled_live, **live_flags},
            )
        )
    live_artifacts: dict[str, object] = {
        "live_calendar_events": safety.live_calendar_events,
        "live_meet_links": safety.live_meet_links,
        "live_phone_calls": safety.live_phone_calls,
        "live_send_attempted_enrollments": safety.live_send_attempted_enrollments,
        "outbound_attempted_classifications": safety.outbound_attempted_classifications,
        "booking_events_created": safety.booking_events_created,
        "booking_meet_links_created": safety.booking_meet_links_created,
        "voice_calls_placed": safety.voice_calls_placed,
    }
    if any(isinstance(count, int) and count > 0 for count in live_artifacts.values()):
        drafts.append(
            _draft(
                key="safety_live_artifacts",
                category=RecommendationCategory.SAFETY_RISK,
                priority=RecommendationPriority.HIGH,
                confidence=0.95,
                title="Review safety: live outbound artifacts are present",
                rationale=(
                    "Stored pipeline state includes live calendar, Meet, call, or send "
                    "attempt counts. The optimizer does not create more artifacts."
                ),
                metrics=live_artifacts,
            )
        )
    if safety.operator_halt_status == HaltStatus.UNAVAILABLE.value:
        drafts.append(
            _draft(
                key="safety_operator_halt_unavailable",
                category=RecommendationCategory.SAFETY_RISK,
                priority=RecommendationPriority.MEDIUM,
                confidence=0.9,
                title="Review safety: persistent operator halt is unavailable",
                rationale=(
                    "The persistent operator halt row is missing or unreadable. "
                    "Outbound guards fail closed in this state; an operator should "
                    "confirm the global halt row exists."
                ),
                metrics={"operator_halt_status": safety.operator_halt_status},
            )
        )
    elif (
        safety.operator_halt_status == HaltStatus.CLEARED.value and safety.outbound_enabled
    ):
        drafts.append(
            _draft(
                key="safety_halt_cleared_with_outbound",
                category=RecommendationCategory.SAFETY_RISK,
                priority=RecommendationPriority.CRITICAL,
                confidence=0.99,
                title="Review safety: operator halt is cleared while outbound is enabled",
                rationale=(
                    "Both the persistent operator halt and OUTBOUND_ENABLED would allow "
                    "outbound-like actions. The optimizer does not lift or set the halt."
                ),
                metrics={
                    "operator_halt_status": safety.operator_halt_status,
                    "outbound_enabled": True,
                },
            )
        )
    return drafts


def _scoring_recommendations(summary: DashboardSummary) -> list[RecommendationDraft]:
    latest = summary.scoring.latest_scores
    if latest < MIN_SCORING_SAMPLE:
        return []
    bands = summary.scoring.by_band
    conservative = bands.get("low", 0) + bands.get("research", 0) + bands.get("disqualified", 0)
    hot = bands.get("hot", 0)
    if conservative / latest >= 0.5:
        return [
            _draft(
                key="icp_scoring_conservative_mix",
                category=RecommendationCategory.ICP_SCORING_THRESHOLD,
                priority=RecommendationPriority.MEDIUM,
                confidence=_confidence(latest, base=0.6),
                title="Review ICP scoring thresholds for a conservative band mix",
                rationale=(
                    f"{conservative} of {latest} latest scores are low, research, or "
                    "disqualified. An operator may review scoring thresholds; this "
                    "layer does not change them."
                ),
                metrics={"latest_scores": latest, "by_band": bands, "conservative": conservative},
            )
        ]
    if hot / latest >= 0.8:
        return [
            _draft(
                key="icp_scoring_hot_heavy_mix",
                category=RecommendationCategory.ICP_SCORING_THRESHOLD,
                priority=RecommendationPriority.MEDIUM,
                confidence=_confidence(latest, base=0.6),
                title="Review ICP scoring thresholds for a hot-heavy band mix",
                rationale=(
                    f"{hot} of {latest} latest scores are hot. An operator may review "
                    "whether qualification is too loose; this layer does not change scores."
                ),
                metrics={"latest_scores": latest, "by_band": bands, "hot": hot},
            )
        ]
    return []


def _specialty_recommendations(extra: ExtraPipelineMetrics) -> list[RecommendationDraft]:
    cohorts = [row for row in extra.specialty_geography if row.leads >= MIN_COHORT_SAMPLE]
    if len(cohorts) < 2:
        return []
    ranked = sorted(cohorts, key=lambda row: (row.conversion_rate, row.leads))
    weakest = ranked[0]
    strongest = ranked[-1]
    if strongest.conversion_rate <= weakest.conversion_rate:
        return []
    return [
        _draft(
            key="specialty_geography_stronger",
            category=RecommendationCategory.SPECIALTY_GEOGRAPHY_SIGNAL,
            priority=RecommendationPriority.LOW,
            confidence=_confidence(strongest.leads, base=0.55),
            title="Review specialties/geographies with stronger conversion signals",
            rationale=(
                f"Stored lead stages show a higher later-pipeline rate for specialty "
                f"{strongest.specialty} in {strongest.state} "
                f"({strongest.conversion_leads} of {strongest.leads}). "
                "This is a review signal only; no campaign change is applied."
            ),
            metrics=strongest.as_metrics(),
        ),
        _draft(
            key="specialty_geography_weaker",
            category=RecommendationCategory.SPECIALTY_GEOGRAPHY_SIGNAL,
            priority=RecommendationPriority.LOW,
            confidence=_confidence(weakest.leads, base=0.55),
            title="Review specialties/geographies with weaker conversion signals",
            rationale=(
                f"Stored lead stages show a lower later-pipeline rate for specialty "
                f"{weakest.specialty} in {weakest.state} "
                f"({weakest.conversion_leads} of {weakest.leads}). "
                "This is a review signal only; no campaign change is applied."
            ),
            metrics=weakest.as_metrics(),
        ),
    ]


def _website_recommendations(
    summary: DashboardSummary, extra: ExtraPipelineMetrics
) -> list[RecommendationDraft]:
    organizations = summary.website_enrichment.organizations
    if organizations == 0 or extra.orgs_without_verified_website == 0:
        return []
    return [
        _draft(
            key="website_enrichment_gap",
            category=RecommendationCategory.WEBSITE_ENRICHMENT_GAP,
            priority=RecommendationPriority.MEDIUM,
            confidence=_confidence(organizations, base=0.7),
            title="Review website enrichment coverage gaps",
            rationale=(
                f"{extra.orgs_without_verified_website} of {organizations} organizations "
                "lack a verified official website match. The optimizer does not fetch "
                "pages or invent websites."
            ),
            metrics={
                "organizations": organizations,
                "orgs_without_verified_website": extra.orgs_without_verified_website,
                "by_match_status": summary.website_enrichment.by_match_status,
            },
        )
    ]


def _decision_maker_recommendations(
    summary: DashboardSummary, extra: ExtraPipelineMetrics
) -> list[RecommendationDraft]:
    org_count = summary.discovery.organizations
    if org_count == 0 or extra.orgs_without_contacts == 0:
        return []
    return [
        _draft(
            key="decision_maker_coverage_gap",
            category=RecommendationCategory.DECISION_MAKER_COVERAGE_GAP,
            priority=RecommendationPriority.MEDIUM,
            confidence=_confidence(org_count, base=0.7),
            title="Review decision-maker enrichment coverage gaps",
            rationale=(
                f"{extra.orgs_without_contacts} of {org_count} organizations have no "
                "stored professional contact. The optimizer does not invent people or "
                "call a paid contact provider."
            ),
            metrics={
                "organizations": org_count,
                "contacts": summary.decision_maker_enrichment.contacts,
                "orgs_without_contacts": extra.orgs_without_contacts,
            },
        )
    ]


def _personalization_recommendations(
    summary: DashboardSummary, extra: ExtraPipelineMetrics
) -> list[RecommendationDraft]:
    not_ready = extra.scored_leads_without_ready_draft
    blocked = summary.personalization.by_readiness.get("blocked", 0)
    needs_evidence = summary.personalization.by_readiness.get("needs_more_evidence", 0)
    if not_ready == 0 and blocked == 0 and needs_evidence == 0:
        return []
    return [
        _draft(
            key="personalization_readiness_gap",
            category=RecommendationCategory.PERSONALIZATION_READINESS_GAP,
            priority=RecommendationPriority.MEDIUM,
            confidence=0.7,
            title="Review personalization readiness gaps",
            rationale=(
                f"{not_ready} scored leads lack a ready personalization draft, with "
                f"{needs_evidence} drafts needing more evidence and {blocked} blocked. "
                "The optimizer does not generate or send copy."
            ),
            metrics={
                "scored_leads_without_ready_draft": not_ready,
                "drafts": summary.personalization.drafts,
                "by_readiness": summary.personalization.by_readiness,
            },
        )
    ]


def _outreach_recommendations(
    summary: DashboardSummary, extra: ExtraPipelineMetrics
) -> list[RecommendationDraft]:
    outreach = summary.outreach_plans
    friction = outreach.skipped_count + outreach.suppressed_count + outreach.blocked_count
    if outreach.enrollments == 0 or friction == 0:
        return []
    return [
        _draft(
            key="outreach_plan_friction",
            category=RecommendationCategory.OUTREACH_PLAN_PATTERN,
            priority=RecommendationPriority.MEDIUM,
            confidence=_confidence(outreach.enrollments, base=0.65),
            title="Review outreach plan skip, block, and suppression patterns",
            rationale=(
                f"{friction} of {outreach.enrollments} dry-run enrollments are skipped, "
                "suppressed, or blocked. The optimizer does not enroll campaigns or send mail."
            ),
            metrics={
                "enrollments": outreach.enrollments,
                "planned_count": outreach.planned_count,
                "skipped_count": outreach.skipped_count,
                "suppressed_count": outreach.suppressed_count,
                "blocked_count": outreach.blocked_count,
                "skip_reasons": extra.outreach_skip_reasons,
            },
        )
    ]


def _reply_recommendations(summary: DashboardSummary) -> list[RecommendationDraft]:
    replies = summary.reply_classifications
    if replies.classifications == 0:
        return []
    intents = replies.by_intent
    notable = {
        "unsubscribe": intents.get("unsubscribe", 0),
        "not_interested": intents.get("not_interested", 0),
        "hostile": intents.get("hostile", 0),
        "interested": intents.get("interested", 0),
        "meeting_request": intents.get("meeting_request", 0),
    }
    if sum(notable.values()) == 0:
        return []
    return [
        _draft(
            key="reply_intent_trend",
            category=RecommendationCategory.REPLY_INTENT_TREND,
            priority=RecommendationPriority.LOW,
            confidence=_confidence(replies.classifications, base=0.6),
            title="Review reply classification intent trends",
            rationale=(
                f"{replies.classifications} stored inbound classifications include "
                f"{notable['meeting_request']} meeting requests, "
                f"{notable['interested']} interested, "
                f"{notable['unsubscribe']} unsubscribe, and "
                f"{notable['not_interested']} not-interested intents. "
                "The optimizer does not send replies."
            ),
            metrics={
                "classifications": replies.classifications,
                "by_intent": intents,
                "by_outcome": replies.by_outcome,
            },
        )
    ]


def _booking_recommendations(
    summary: DashboardSummary, extra: ExtraPipelineMetrics
) -> list[RecommendationDraft]:
    meeting_requests = summary.reply_classifications.by_intent.get("meeting_request", 0)
    booking = summary.booking_plans
    friction = booking.skipped_count + booking.suppressed_count + booking.blocked_count
    if meeting_requests == 0 and booking.plans == 0:
        return []
    if friction == 0 and meeting_requests <= booking.planned_count:
        return []
    return [
        _draft(
            key="booking_plan_bottleneck",
            category=RecommendationCategory.BOOKING_PLAN_BOTTLENECK,
            priority=RecommendationPriority.MEDIUM,
            confidence=0.7,
            title="Review booking-plan bottlenecks",
            rationale=(
                f"{meeting_requests} stored meeting-request classifications and "
                f"{booking.planned_count} planned booking drafts, with {friction} "
                "skipped/suppressed/blocked plans. The optimizer does not create "
                "calendar events or Meet links."
            ),
            metrics={
                "meeting_requests": meeting_requests,
                "plans": booking.plans,
                "planned_count": booking.planned_count,
                "skipped_count": booking.skipped_count,
                "suppressed_count": booking.suppressed_count,
                "blocked_count": booking.blocked_count,
                "events_created": booking.events_created,
                "meet_links_created": booking.meet_links_created,
                "skip_reasons": extra.booking_skip_reasons,
            },
        )
    ]


def _voice_recommendations(
    summary: DashboardSummary, extra: ExtraPipelineMetrics
) -> list[RecommendationDraft]:
    voice = summary.voice_qualification_plans
    friction = voice.skipped_count + voice.suppressed_count + voice.blocked_count
    if voice.plans == 0 and friction == 0:
        return []
    if friction == 0 and voice.calls_placed == 0:
        return []
    return [
        _draft(
            key="voice_plan_bottleneck",
            category=RecommendationCategory.VOICE_PLAN_BOTTLENECK,
            priority=RecommendationPriority.MEDIUM,
            confidence=0.7,
            title="Review voice-plan bottlenecks",
            rationale=(
                f"{voice.planned_count} planned voice qualification drafts, with {friction} "
                "skipped/suppressed/blocked and "
                f"{voice.calls_placed} calls placed. The optimizer does not place calls."
            ),
            metrics={
                "plans": voice.plans,
                "planned_count": voice.planned_count,
                "skipped_count": voice.skipped_count,
                "suppressed_count": voice.suppressed_count,
                "blocked_count": voice.blocked_count,
                "calls_placed": voice.calls_placed,
                "live_call_attempted": voice.live_call_attempted,
                "skip_reasons": extra.voice_skip_reasons,
            },
        )
    ]


def _draft(
    *,
    key: str,
    category: RecommendationCategory,
    priority: RecommendationPriority,
    confidence: float,
    title: str,
    rationale: str,
    metrics: dict[str, object],
) -> RecommendationDraft:
    return RecommendationDraft(
        recommendation_key=key,
        category=category,
        priority=priority,
        confidence=round(min(max(confidence, 0.0), 1.0), 4),
        title=title,
        rationale=rationale,
        source_metrics=metrics,
    )


def _confidence(sample: int, *, base: float) -> float:
    if sample <= 0:
        return base
    return round(min(base + min(sample, 20) * 0.01, 0.95), 4)


def _sanitized_snapshot(
    summary: DashboardSummary, extra: ExtraPipelineMetrics
) -> dict[str, object]:
    payload = asdict(summary)
    payload.pop("generated_at", None)
    payload["extra"] = {
        "orgs_without_verified_website": extra.orgs_without_verified_website,
        "orgs_without_contacts": extra.orgs_without_contacts,
        "scored_leads_without_ready_draft": extra.scored_leads_without_ready_draft,
        "outreach_skip_reasons": extra.outreach_skip_reasons,
        "booking_skip_reasons": extra.booking_skip_reasons,
        "voice_skip_reasons": extra.voice_skip_reasons,
        "specialty_geography": [cohort.as_metrics() for cohort in extra.specialty_geography],
    }
    sanitized = _json_safe(payload)
    if not isinstance(sanitized, dict):
        raise TypeError("optimizer snapshot must be an object")
    return {str(key): item for key, item in sanitized.items()}


def _json_safe(value: object) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def _fingerprint(payload: dict[str, object]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _specialty_geography(db: Session) -> tuple[SpecialtyCohort, ...]:
    rows = db.execute(
        select(
            Organization.specialty,
            Organization.state,
            Lead.stage,
            func.count(),
        )
        .join(Lead, Lead.organization_id == Organization.id)
        .group_by(Organization.specialty, Organization.state, Lead.stage)
    ).all()
    grouped: dict[tuple[str, str], dict[str, int]] = {}
    for specialty, state, stage, count in rows:
        key = (
            "unset" if not specialty else str(specialty),
            "unset" if not state else str(state),
        )
        bucket = grouped.setdefault(key, {"leads": 0, "conversion_leads": 0})
        bucket["leads"] += int(count)
        if stage in CONVERSION_STAGES:
            bucket["conversion_leads"] += int(count)
    results: list[SpecialtyCohort] = []
    for (specialty, state), counts in sorted(grouped.items()):
        leads = counts["leads"]
        conversion_leads = counts["conversion_leads"]
        results.append(
            SpecialtyCohort(
                specialty=specialty,
                state=state,
                leads=leads,
                conversion_leads=conversion_leads,
                conversion_rate=round(conversion_leads / leads, 4) if leads else 0.0,
            )
        )
    return tuple(results)


def _count_rows(db: Session, model: type[Any], *clauses: Any) -> int:
    stmt = select(func.count()).select_from(model)
    if clauses:
        stmt = stmt.where(*clauses)
    return int(db.scalar(stmt) or 0)


def _counts_by(db: Session, column: Any) -> dict[str, int]:
    rows = db.execute(select(column, func.count()).group_by(column)).all()
    result: dict[str, int] = {}
    for key, count in rows:
        if key is None or key == "":
            continue
        result[str(key)] = int(count)
    return result
