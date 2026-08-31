from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from vyro_growth.config import Settings, any_live_provider_enabled, live_provider_flags
from vyro_growth.domain import (
    ContentBriefApprovalStatus,
    EnrollmentStatus,
    FindingCode,
    FindingSeverity,
    RecommendationApprovalStatus,
)
from vyro_growth.models import (
    Activity,
    BookingPlan,
    BookingPlanRun,
    CampaignEnrollment,
    ChannelPlan,
    ChannelPlanRun,
    ContentBrief,
    ContentBriefRun,
    DiscoveryRun,
    EnrichmentRun,
    OptimizerRecommendation,
    OptimizerRun,
    OutreachPlanRun,
    PersonalizationDraft,
    VoiceQualificationPlan,
    VoiceQualificationRun,
)
from vyro_growth.observability import sanitize_error_message, sanitize_operator_text
from vyro_growth.providers.decision_makers import DECISION_MAKER_SOURCE
from vyro_growth.providers.personalization import PERSONALIZATION_SOURCE
from vyro_growth.providers.website import WEBSITE_ENRICHMENT_SOURCE
from vyro_growth.services.dashboard import DashboardAnalyticsService, SafetyCard
from vyro_growth.services.operator_halt import HaltStatus
from vyro_growth.services.readiness import ReadinessPayload, assess_readiness
from vyro_growth.workers.booking_plan_handler import PLAN_BOOKING_SLOTS_JOB
from vyro_growth.workers.channel_planning_handler import GENERATE_CHANNEL_PLANS_JOB
from vyro_growth.workers.contact_enrichment_handler import ENRICH_DECISION_MAKERS_JOB
from vyro_growth.workers.content_brief_handler import GENERATE_CONTENT_BRIEFS_JOB
from vyro_growth.workers.discovery_handler import DISCOVER_NPPES_PRACTICES_JOB
from vyro_growth.workers.growth_optimizer_handler import GENERATE_GROWTH_RECOMMENDATIONS_JOB
from vyro_growth.workers.outreach_enrollment_handler import PLAN_OUTREACH_ENROLLMENTS_JOB
from vyro_growth.workers.personalization_handler import PERSONALIZE_SCORED_LEADS_JOB
from vyro_growth.workers.reply_classification_handler import CLASSIFY_INBOUND_REPLIES_JOB
from vyro_growth.workers.scoring_handler import SCORE_DISCOVERED_LEADS_JOB
from vyro_growth.workers.voice_qualification_handler import PLAN_VOICE_QUALIFICATIONS_JOB
from vyro_growth.workers.website_enrichment_handler import ENRICH_ORGANIZATION_WEBSITES_JOB

logger = structlog.get_logger(__name__)

FAILED_STATUS = "failed"
DEFAULT_FAILURE_LIMIT = 10
_SEVERITY_RANK = {
    FindingSeverity.INFO: 0,
    FindingSeverity.WARNING: 1,
    FindingSeverity.BLOCKED: 2,
}
PHASE_JOB_NAMES: dict[str, str] = {
    "discovery": DISCOVER_NPPES_PRACTICES_JOB,
    "website_enrichment": ENRICH_ORGANIZATION_WEBSITES_JOB,
    "decision_maker_enrichment": ENRICH_DECISION_MAKERS_JOB,
    "scoring": SCORE_DISCOVERED_LEADS_JOB,
    "personalization": PERSONALIZE_SCORED_LEADS_JOB,
    "outreach_plans": PLAN_OUTREACH_ENROLLMENTS_JOB,
    "reply_classifications": CLASSIFY_INBOUND_REPLIES_JOB,
    "booking_plans": PLAN_BOOKING_SLOTS_JOB,
    "voice_qualification_plans": PLAN_VOICE_QUALIFICATIONS_JOB,
    "growth_optimizer": GENERATE_GROWTH_RECOMMENDATIONS_JOB,
    "acquisition_channel_plans": GENERATE_CHANNEL_PLANS_JOB,
    "content_briefs": GENERATE_CONTENT_BRIEFS_JOB,
}


@dataclass(frozen=True)
class LatestJobStatus:
    phase: str
    job_name: str | None
    implemented: bool
    status: str | None
    started_at: datetime | None
    finished_at: datetime | None
    run_id: UUID | None


@dataclass(frozen=True)
class SanitizedFailure:
    phase: str
    status: str
    occurred_at: datetime | None
    run_id: UUID | None
    error_message: str | None


@dataclass(frozen=True)
class MonitoringSafety:
    outbound_enabled: bool
    outbound_halted_settings: bool
    operator_halt_status: str
    operator_halt_reason: str | None
    live_providers_enabled: bool
    live_providers: dict[str, bool]
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
class MonitoringReadiness:
    status: str
    environment: str
    database: str
    config_ok: bool
    config_issues: tuple[str, ...]
    outbound_enabled: bool
    live_providers_enabled: bool
    live_providers: dict[str, bool]
    ready_for_manual_rollout: bool


@dataclass(frozen=True)
class PendingReviewCounts:
    personalization_drafts: int
    enrollment_plans: int
    booking_plans: int
    voice_plans: int
    optimizer_recommendations: int
    channel_plans: int
    content_briefs: int

    @property
    def total(self) -> int:
        return (
            self.personalization_drafts
            + self.enrollment_plans
            + self.booking_plans
            + self.voice_plans
            + self.optimizer_recommendations
            + self.channel_plans
            + self.content_briefs
        )


@dataclass(frozen=True)
class ActivityActionCount:
    action: str
    count: int


@dataclass(frozen=True)
class OperationalFinding:
    severity: FindingSeverity
    code: FindingCode
    message: str
    phase: str | None = None


@dataclass(frozen=True)
class MonitoringSnapshot:
    generated_at: datetime
    read_only: bool
    overall_severity: FindingSeverity
    latest_runs: tuple[LatestJobStatus, ...]
    recent_failures: tuple[SanitizedFailure, ...]
    safety: MonitoringSafety
    readiness: MonitoringReadiness
    pending_review: PendingReviewCounts
    activity_summary: tuple[ActivityActionCount, ...]
    findings: tuple[OperationalFinding, ...]


class OperatorMonitoringService:
    """Read-only operational status. Does not write rows or call live providers."""

    def __init__(
        self,
        *,
        dashboard: DashboardAnalyticsService | None = None,
        failure_limit: int = DEFAULT_FAILURE_LIMIT,
    ) -> None:
        self.dashboard = dashboard or DashboardAnalyticsService()
        self.failure_limit = failure_limit

    def snapshot(self, db: Session, settings: Settings) -> MonitoringSnapshot:
        summary = self.dashboard.summarize(db, settings)
        readiness_status, readiness_payload = assess_readiness(settings, db)
        del readiness_status
        pending = self._pending_review(db)
        failures = self._recent_failures(db)
        latest_runs = self._latest_runs(db, summary.latest_runs)
        safety = self._safety(summary.safety, settings)
        readiness = self._readiness(readiness_payload, safety)
        activity_summary = self._activity_summary(db)
        findings = self._findings(
            safety=safety,
            readiness=readiness,
            pending=pending,
            failures=failures,
        )
        snapshot = MonitoringSnapshot(
            generated_at=datetime.now(tz=UTC),
            read_only=True,
            overall_severity=_highest_severity(findings),
            latest_runs=latest_runs,
            recent_failures=failures,
            safety=safety,
            readiness=readiness,
            pending_review=pending,
            activity_summary=activity_summary,
            findings=findings,
        )
        logger.info(
            "operator_status_built",
            read_only=True,
            overall_severity=snapshot.overall_severity.value,
            recent_failures=len(failures),
            pending_review=pending.total,
            outbound_enabled=safety.outbound_enabled,
            operator_halt_status=safety.operator_halt_status,
        )
        return snapshot

    def _latest_runs(
        self, db: Session, dashboard_runs: tuple[Any, ...]
    ) -> tuple[LatestJobStatus, ...]:
        runs = [
            LatestJobStatus(
                phase=run.phase,
                job_name=PHASE_JOB_NAMES.get(run.phase),
                implemented=run.implemented,
                status=run.status,
                started_at=run.started_at,
                finished_at=run.finished_at,
                run_id=run.run_id,
            )
            for run in dashboard_runs
        ]
        optimizer = _latest_row(db, OptimizerRun)
        if optimizer is None:
            runs.append(
                LatestJobStatus(
                    phase="growth_optimizer",
                    job_name=PHASE_JOB_NAMES["growth_optimizer"],
                    implemented=True,
                    status="not_started",
                    started_at=None,
                    finished_at=None,
                    run_id=None,
                )
            )
        else:
            runs.append(
                LatestJobStatus(
                    phase="growth_optimizer",
                    job_name=PHASE_JOB_NAMES["growth_optimizer"],
                    implemented=True,
                    status=optimizer.status,
                    started_at=optimizer.started_at,
                    finished_at=optimizer.finished_at,
                    run_id=optimizer.id,
                )
            )
        channel_run = _latest_row(db, ChannelPlanRun)
        if channel_run is None:
            runs.append(
                LatestJobStatus(
                    phase="acquisition_channel_plans",
                    job_name=PHASE_JOB_NAMES["acquisition_channel_plans"],
                    implemented=True,
                    status="not_started",
                    started_at=None,
                    finished_at=None,
                    run_id=None,
                )
            )
        else:
            runs.append(
                LatestJobStatus(
                    phase="acquisition_channel_plans",
                    job_name=PHASE_JOB_NAMES["acquisition_channel_plans"],
                    implemented=True,
                    status=channel_run.status,
                    started_at=channel_run.started_at,
                    finished_at=channel_run.finished_at,
                    run_id=channel_run.id,
                )
            )
        briefs = _latest_row(db, ContentBriefRun)
        if briefs is None:
            runs.append(
                LatestJobStatus(
                    phase="content_briefs",
                    job_name=PHASE_JOB_NAMES["content_briefs"],
                    implemented=True,
                    status="not_started",
                    started_at=None,
                    finished_at=None,
                    run_id=None,
                )
            )
        else:
            runs.append(
                LatestJobStatus(
                    phase="content_briefs",
                    job_name=PHASE_JOB_NAMES["content_briefs"],
                    implemented=True,
                    status=briefs.status,
                    started_at=briefs.started_at,
                    finished_at=briefs.finished_at,
                    run_id=briefs.id,
                )
            )
        return tuple(runs)

    def _recent_failures(self, db: Session) -> tuple[SanitizedFailure, ...]:
        collected: list[SanitizedFailure] = []
        sources: tuple[tuple[str, type[Any], Any | None], ...] = (
            ("discovery", DiscoveryRun, None),
            (
                "website_enrichment",
                EnrichmentRun,
                EnrichmentRun.source == WEBSITE_ENRICHMENT_SOURCE,
            ),
            (
                "decision_maker_enrichment",
                EnrichmentRun,
                EnrichmentRun.source == DECISION_MAKER_SOURCE,
            ),
            ("personalization", EnrichmentRun, EnrichmentRun.source == PERSONALIZATION_SOURCE),
            ("outreach_plans", OutreachPlanRun, None),
            ("booking_plans", BookingPlanRun, None),
            ("voice_qualification_plans", VoiceQualificationRun, None),
            ("growth_optimizer", OptimizerRun, None),
            ("acquisition_channel_plans", ChannelPlanRun, None),
            ("content_briefs", ContentBriefRun, None),
        )
        for phase, model, extra in sources:
            stmt = select(model).where(model.status == FAILED_STATUS)
            if extra is not None:
                stmt = stmt.where(extra)
            stmt = stmt.order_by(model.created_at.desc())
            for row in db.scalars(stmt).all():
                collected.append(
                    SanitizedFailure(
                        phase=phase,
                        status=row.status,
                        occurred_at=getattr(row, "finished_at", None) or row.created_at,
                        run_id=row.id,
                        error_message=sanitize_error_message(getattr(row, "error_message", None)),
                    )
                )
        collected.sort(key=lambda item: _sort_timestamp(item.occurred_at), reverse=True)
        return tuple(collected[: self.failure_limit])

    def _safety(self, card: SafetyCard, settings: Settings) -> MonitoringSafety:
        return MonitoringSafety(
            outbound_enabled=card.outbound_enabled,
            outbound_halted_settings=card.outbound_halted_settings,
            operator_halt_status=card.operator_halt_status,
            operator_halt_reason=sanitize_operator_text(card.operator_halt_reason),
            live_providers_enabled=any_live_provider_enabled(settings),
            live_providers=live_provider_flags(settings),
            live_calendar_events=card.live_calendar_events,
            live_meet_links=card.live_meet_links,
            live_phone_calls=card.live_phone_calls,
            live_send_attempted_enrollments=card.live_send_attempted_enrollments,
            outbound_attempted_classifications=card.outbound_attempted_classifications,
            booking_events_created=card.booking_events_created,
            booking_meet_links_created=card.booking_meet_links_created,
            voice_calls_placed=card.voice_calls_placed,
            phi_fields_present=card.phi_fields_present,
        )

    def _readiness(
        self, payload: ReadinessPayload, safety: MonitoringSafety
    ) -> MonitoringReadiness:
        live_artifact_count = (
            safety.live_calendar_events
            + safety.live_meet_links
            + safety.live_phone_calls
            + safety.live_send_attempted_enrollments
            + safety.outbound_attempted_classifications
            + safety.booking_events_created
            + safety.booking_meet_links_created
            + safety.voice_calls_placed
        )
        ready_for_manual_rollout = (
            payload["status"] == "ready"
            and not payload["outbound_enabled"]
            and not payload["live_providers_enabled"]
            and live_artifact_count == 0
        )
        issues = tuple(str(item) for item in payload["config_issues"])
        return MonitoringReadiness(
            status=str(payload["status"]),
            environment=str(payload["environment"]),
            database=str(payload["database"]),
            config_ok=bool(payload["config_ok"]),
            config_issues=issues,
            outbound_enabled=bool(payload["outbound_enabled"]),
            live_providers_enabled=bool(payload["live_providers_enabled"]),
            live_providers=dict(payload["live_providers"]),
            ready_for_manual_rollout=ready_for_manual_rollout,
        )

    def _pending_review(self, db: Session) -> PendingReviewCounts:
        return PendingReviewCounts(
            personalization_drafts=_count_rows(db, PersonalizationDraft),
            enrollment_plans=_count_rows(
                db, CampaignEnrollment, CampaignEnrollment.status == EnrollmentStatus.PLANNED.value
            ),
            booking_plans=_count_rows(db, BookingPlan, BookingPlan.status == "planned"),
            voice_plans=_count_rows(
                db, VoiceQualificationPlan, VoiceQualificationPlan.status == "planned"
            ),
            optimizer_recommendations=_count_rows(
                db,
                OptimizerRecommendation,
                OptimizerRecommendation.approval_status
                == RecommendationApprovalStatus.PENDING_OPERATOR_REVIEW.value,
                OptimizerRecommendation.applied.is_(False),
            ),
            channel_plans=_count_rows(
                db,
                ChannelPlan,
                ChannelPlan.approval_status
                == RecommendationApprovalStatus.PENDING_OPERATOR_REVIEW.value,
                ChannelPlan.launched.is_(False),
            ),
            content_briefs=_count_rows(
                db,
                ContentBrief,
                ContentBrief.approval_status
                == ContentBriefApprovalStatus.PENDING_OPERATOR_REVIEW.value,
                ContentBrief.published.is_(False),
            ),
        )

    def _activity_summary(self, db: Session) -> tuple[ActivityActionCount, ...]:
        rows = db.execute(
            select(Activity.action, func.count())
            .group_by(Activity.action)
            .order_by(Activity.action)
        ).all()
        return tuple(
            ActivityActionCount(action=str(action), count=int(count)) for action, count in rows
        )

    def _findings(
        self,
        *,
        safety: MonitoringSafety,
        readiness: MonitoringReadiness,
        pending: PendingReviewCounts,
        failures: tuple[SanitizedFailure, ...],
    ) -> tuple[OperationalFinding, ...]:
        findings: list[OperationalFinding] = []
        if safety.outbound_enabled:
            findings.append(
                OperationalFinding(
                    FindingSeverity.BLOCKED,
                    FindingCode.OUTBOUND_ENABLED,
                    "OUTBOUND_ENABLED is true. Do not treat this as a dry-run-only environment.",
                )
            )
        if safety.live_providers_enabled:
            enabled = sorted(name for name, on in safety.live_providers.items() if on)
            findings.append(
                OperationalFinding(
                    FindingSeverity.BLOCKED,
                    FindingCode.LIVE_PROVIDER_ENABLED,
                    "Live provider flag(s) are enabled: " + ", ".join(enabled) + ".",
                )
            )
        live_artifacts = (
            safety.live_calendar_events
            + safety.live_meet_links
            + safety.live_phone_calls
            + safety.live_send_attempted_enrollments
            + safety.voice_calls_placed
            + safety.booking_events_created
            + safety.booking_meet_links_created
        )
        if live_artifacts:
            findings.append(
                OperationalFinding(
                    FindingSeverity.BLOCKED,
                    FindingCode.LIVE_OUTBOUND_ARTIFACT,
                    "Stored live calendar, Meet, send, or call artifacts are present.",
                )
            )
        if readiness.database != "ok":
            findings.append(
                OperationalFinding(
                    FindingSeverity.BLOCKED,
                    FindingCode.DATABASE_UNAVAILABLE,
                    "Database readiness check failed.",
                )
            )
        if not readiness.config_ok:
            findings.append(
                OperationalFinding(
                    FindingSeverity.WARNING,
                    FindingCode.CONFIG_NOT_READY,
                    "Phase 12 runtime config is not ready. Run vyro-growth check-config.",
                )
            )
        if safety.operator_halt_status == HaltStatus.UNAVAILABLE.value:
            findings.append(
                OperationalFinding(
                    FindingSeverity.WARNING,
                    FindingCode.OPERATOR_HALT_UNAVAILABLE,
                    "Persistent operator halt row is missing or unreadable (fail-closed).",
                )
            )
        if failures:
            findings.append(
                OperationalFinding(
                    FindingSeverity.WARNING,
                    FindingCode.RECENT_FAILURES,
                    f"{len(failures)} recent failed run(s) require operator review.",
                )
            )
        if pending.total:
            findings.append(
                OperationalFinding(
                    FindingSeverity.INFO,
                    FindingCode.PENDING_OPERATOR_REVIEW,
                    f"{pending.total} item(s) are waiting for operator review.",
                )
            )
        if safety.operator_halt_status == HaltStatus.HALTED.value:
            findings.append(
                OperationalFinding(
                    FindingSeverity.INFO,
                    FindingCode.OPERATOR_HALT_ACTIVE,
                    "Persistent operator halt is active.",
                )
            )
        if (
            not safety.outbound_enabled
            and not safety.live_providers_enabled
            and live_artifacts == 0
        ):
            findings.append(
                OperationalFinding(
                    FindingSeverity.INFO,
                    FindingCode.SAFE_DEFAULTS,
                    "Outbound and live-provider flags remain disabled.",
                )
            )
        findings.sort(key=lambda item: (-_SEVERITY_RANK[item.severity], item.code.value))
        return tuple(findings)


def _sort_timestamp(value: datetime | None) -> datetime:
    if value is None:
        return datetime.min.replace(tzinfo=UTC)
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def _highest_severity(findings: tuple[OperationalFinding, ...]) -> FindingSeverity:
    if not findings:
        return FindingSeverity.INFO
    return max(findings, key=lambda item: _SEVERITY_RANK[item.severity]).severity


def _count_rows(db: Session, model: type[Any], *clauses: Any) -> int:
    stmt = select(func.count()).select_from(model)
    if clauses:
        stmt = stmt.where(*clauses)
    return int(db.scalar(stmt) or 0)


def _latest_row(db: Session, model: type[Any], *clauses: Any) -> Any | None:
    stmt = select(model)
    if clauses:
        stmt = stmt.where(*clauses)
    stmt = stmt.order_by(model.created_at.desc())
    return db.scalars(stmt).first()
