"""Read-only supervised pilot candidate readiness export.

Phase 57 summarizes whether the current system has a safe small-pilot
candidate pool ready for owner review. It reuses discovery, enrichment,
scoring, and outreach aggregates plus the supervised pilot plan, provider
setup, rehearsal outcome, launch readiness, and operator halt surfaces.
It never executes, applies settings, lifts halt, enables outbound, calls
providers, scrapes, builds, publishes, deploys, spends, or changes live
state. This export is not permission to go live and not an execution
surface.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from vyro_growth.config import Settings
from vyro_growth.domain import (
    EnrichmentRunStatus,
    FindingSeverity,
    LeadStage,
    NextActionCode,
    WebsiteMatchStatus,
)
from vyro_growth.models import (
    Contact,
    EnrichmentRun,
    Lead,
    LeadScore,
    Organization,
    SourceEvidence,
    Suppression,
)
from vyro_growth.observability import sanitize_mapping, sanitize_operator_text
from vyro_growth.providers.website import WEBSITE_ENRICHMENT_SOURCE
from vyro_growth.services.dashboard import DashboardAnalyticsService, DashboardSummary
from vyro_growth.services.lead_scoring import (
    US_STATE_CODES,
    ScoreBand,
    SpecialtyFit,
    classify_specialty,
)
from vyro_growth.services.operator_halt import HaltStatus, read_operator_halt
from vyro_growth.services.release_artifact_manifest import LocalGitMetadata
from vyro_growth.services.supervised_pilot_plan import (
    CLI_COMMAND as PILOT_CLI_COMMAND,
)
from vyro_growth.services.supervised_pilot_plan import (
    HTML_ROUTE as PILOT_HTML_ROUTE,
)
from vyro_growth.services.supervised_pilot_plan import (
    HTTP_ROUTE as PILOT_HTTP_ROUTE,
)
from vyro_growth.services.supervised_pilot_plan import (
    SUGGESTED_MAX_DAILY_ACTIVITY,
    SUGGESTED_MAX_DRAFTS,
    SUGGESTED_MAX_LEADS,
    SUGGESTED_MAX_MANUALLY_REVIEWED_SENDS,
    PilotScopeRecommendation,
    SupervisedPilotPlan,
    SupervisedPilotPlanService,
)

logger = structlog.get_logger(__name__)

PACKET_KIND = "supervised_pilot_candidates"
PACKET_PURPOSE = "manual_owner_supervised_pilot_candidate_review_only"
CANDIDATES_NOT_GO_LIVE_CODE = (
    NextActionCode.SUPERVISED_PILOT_CANDIDATES_IS_NOT_GO_LIVE.value
)
EXECUTION_DISABLED_CODE = "execution_disabled_in_this_phase"
CLI_COMMAND = "supervised-pilot-candidates"
HTTP_ROUTE = "/internal/supervised-pilot-candidates"
HTML_ROUTE = "/internal/operator-supervised-pilot-candidates"
READY_SCORE_BANDS: frozenset[str] = frozenset(
    {ScoreBand.HOT.value, ScoreBand.HIGH.value, ScoreBand.MEDIUM.value}
)
KNOWN_READINESS_KEYS: tuple[str, ...] = (
    "ready_for_owner_review",
    FindingSeverity.WARNING.value,
    FindingSeverity.BLOCKED.value,
    ScoreBand.RESEARCH.value,
    ScoreBand.DISQUALIFIED.value,
    "unset",
)
KNOWN_STAGE_KEYS: tuple[str, ...] = tuple(item.value for item in LeadStage) + ("other",)
KNOWN_SOURCE_KEYS: tuple[str, ...] = (
    "nppes",
    "cms",
    "operator",
    "manual",
    "import",
    "website",
    "unknown",
    "other",
    "unset",
)
KNOWN_SPECIALTY_KEYS: tuple[str, ...] = (
    SpecialtyFit.TARGET.value,
    SpecialtyFit.EXCLUDED.value,
    SpecialtyFit.UNKNOWN.value,
    "unset",
)
KNOWN_WEBSITE_KEYS: tuple[str, ...] = (
    WebsiteMatchStatus.VERIFIED.value,
    WebsiteMatchStatus.AMBIGUOUS.value,
    WebsiteMatchStatus.NO_MATCH.value,
    "unset",
)
KNOWN_SCORE_BANDS: tuple[str, ...] = tuple(item.value for item in ScoreBand) + ("unset",)
BLOCKED_REASON_KEYS: tuple[str, ...] = (
    "missing_website",
    "missing_enrichment",
    "missing_evidence",
    "missing_score",
    "suppression",
    "consent",
    "owner_approval",
)
GENERIC_SOURCES: frozenset[str] = frozenset(
    {"nppes", "cms", "operator", "manual", "import", "website", "unknown"}
)
RELATED_COMMANDS: tuple[str, ...] = (
    "launch-readiness",
    "go-live-readiness-index",
    "launch-blockers-plan",
    "staged-rollout-plan",
    "owner-launch-dossier",
    "provider-setup-checklist",
    "go-live-rehearsal-checklist",
    "rehearsal-outcome-report",
    PILOT_CLI_COMMAND,
    "settings-execution-preflight",
    "dashboard-summary",
    "check-config",
    "smoke-dry-run",
    CLI_COMMAND,
    "supervised-pilot-go-no-go",
    "supervised-pilot-first-send-preflight",
    "supervised-pilot-launch-rehearsal-control-map",
    "system-status",
)
RELATED_ROUTES: tuple[str, ...] = (
    "/internal/launch-readiness",
    "/internal/operator-go-live-readiness-index",
    "/internal/go-live-readiness-index",
    "/internal/operator-launch-blockers-plan",
    "/internal/launch-blockers-plan",
    "/internal/operator-staged-rollout-plan",
    "/internal/staged-rollout-plan",
    "/internal/operator-owner-launch-dossier",
    "/internal/owner-launch-dossier",
    "/internal/operator-provider-setup-checklist",
    "/internal/provider-setup-checklist",
    "/internal/operator-go-live-rehearsal-checklist",
    "/internal/go-live-rehearsal-checklist",
    "/internal/operator-rehearsal-outcome-report",
    "/internal/rehearsal-outcome-report",
    PILOT_HTML_ROUTE,
    PILOT_HTTP_ROUTE,
    "/internal/dashboard/summary",
    HTML_ROUTE,
    HTTP_ROUTE,
    "/internal/operator-supervised-pilot-go-no-go",
    "/internal/supervised-pilot-go-no-go",
    "/internal/operator-supervised-pilot-first-send-preflight",
    "/internal/supervised-pilot-first-send-preflight",
    "/internal/operator-supervised-pilot-launch-rehearsal-control-map",
    "/internal/supervised-pilot-launch-rehearsal-control-map",
)
_STATUS_RANK = {
    FindingSeverity.INFO.value: 0,
    "ready_for_owner_review": 1,
    "open": 1,
    "missing": 2,
    "closed": 2,
    FindingSeverity.WARNING.value: 2,
    FindingSeverity.BLOCKED.value: 3,
}


@dataclass(frozen=True)
class CandidateCount:
    key: str
    count: int


@dataclass(frozen=True)
class CandidateScopeRecommendation:
    suggested_candidate_count: int
    suggested_max_leads: int
    suggested_max_drafts: int
    suggested_max_manually_reviewed_sends: int
    suggested_max_daily_activity: int
    ready_for_review_count: int
    blocked_candidate_count: int
    total_candidate_count: int
    stop_conditions: tuple[str, ...]
    recommendation_summary: str


@dataclass(frozen=True)
class CandidateNextAction:
    code: str
    status: str
    label: str
    command_name: str | None
    json_route: str | None
    html_route: str | None
    config_name: str | None


@dataclass(frozen=True)
class SupervisedPilotCandidates:
    generated_at: datetime
    packet_kind: str
    purpose: str
    overall_status: str
    read_only: bool
    no_execution: bool
    no_go_live: bool
    no_deployment: bool
    no_outbound: bool
    no_provider_calls: bool
    no_spend: bool
    dry_run_only: bool
    executed: int
    execution_attempted: bool
    outbound_attempted: bool
    live_call_attempted: bool
    recommendation_applied: bool
    spend_attempted: bool
    spend_allowed: bool
    campaign_launched: bool
    pages_published: bool
    ads_launched: bool
    owner_approved: bool
    settings_applied: bool
    halt_changed: bool
    live_action: bool
    execution_allowed: bool
    future_execution_phase_exists: bool
    future_deployment_phase_exists: bool
    go_live_permitted: bool
    deployment_allowed: bool
    deployment_attempted: bool
    deployed: bool
    build_allowed: bool
    artifact_publish_allowed: bool
    container_build_attempted: bool
    artifact_publish_attempted: bool
    outbound_enabled: bool
    live_providers_enabled: bool
    manual_review_only: bool
    supervised_pilot_candidates_is_not_go_live: bool
    export_is_not_permission_to_go_live: bool
    export_is_not_execution: bool
    supervised_pilot_plan_is_not_go_live: bool
    rehearsal_outcome_report_is_not_go_live: bool
    go_live_rehearsal_checklist_is_not_go_live: bool
    provider_setup_checklist_is_not_go_live: bool
    operator_halt_status: str
    operator_halt_before: str
    operator_halt_after: str
    candidate_scope: CandidateScopeRecommendation
    candidate_counts_by_readiness: tuple[CandidateCount, ...]
    candidate_counts_by_status: tuple[CandidateCount, ...]
    candidate_counts_by_stage: tuple[CandidateCount, ...]
    candidate_counts_by_source: tuple[CandidateCount, ...]
    candidate_counts_by_specialty: tuple[CandidateCount, ...]
    candidate_counts_by_state: tuple[CandidateCount, ...]
    scoring_distribution: tuple[CandidateCount, ...]
    website_match_counts: tuple[CandidateCount, ...]
    outreach_status_counts: tuple[CandidateCount, ...]
    suppression_counts_by_reason: tuple[CandidateCount, ...]
    kill_switch_outbound_disabled: bool
    kill_switch_operator_halt_active: bool
    kill_switch_live_providers_closed: bool
    suppression_record_count: int
    blocked_counts: tuple[CandidateCount, ...]
    missing_prerequisite_codes: tuple[str, ...]
    remaining_owner_approval_types: tuple[str, ...]
    closed_provider_flag_names: tuple[str, ...]
    missing_credential_names: tuple[str, ...]
    missing_config_names: tuple[str, ...]
    blocker_codes: tuple[str, ...]
    gate_codes: tuple[str, ...]
    cli_command: str
    http_route: str
    source_pilot_plan_command: str
    source_pilot_plan_route: str
    source_pilot_plan_html_route: str
    source_pilot_plan_overall_status: str
    source_outcome_command: str
    source_outcome_route: str
    source_outcome_overall_status: str
    source_rehearsal_command: str
    source_rehearsal_route: str
    source_rehearsal_overall_status: str
    source_launch_readiness_command: str
    source_launch_readiness_route: str
    source_launch_readiness_overall_status: str
    source_index_command: str
    source_index_route: str
    source_index_overall_status: str
    source_provider_setup_command: str
    source_provider_setup_route: str
    source_provider_setup_overall_status: str
    related_commands: tuple[str, ...]
    related_routes: tuple[str, ...]
    local_git: LocalGitMetadata
    next_actions: tuple[CandidateNextAction, ...]


class SupervisedPilotCandidateService:
    """Compose a sanitized candidate-readiness packet from existing surfaces."""

    def __init__(
        self,
        *,
        plan: SupervisedPilotPlanService | None = None,
        dashboard: DashboardAnalyticsService | None = None,
    ) -> None:
        self.plan = plan or SupervisedPilotPlanService()
        self.dashboard = dashboard or DashboardAnalyticsService()

    def build(self, db: Session, settings: Settings) -> SupervisedPilotCandidates:
        halt_before = read_operator_halt(db)
        plan = self.plan.build(db, settings)
        dashboard = self.dashboard.summarize(db, settings)
        pool = _scan_candidate_pool(
            db,
            owner_approval_blocked=bool(plan.remaining_owner_approval_types),
        )
        halt_after = read_operator_halt(db)
        if halt_after != halt_before:
            raise RuntimeError("supervised pilot candidates must not change operator halt status")
        export = _from_sources(
            plan,
            dashboard,
            pool,
            halt_before=halt_before,
            halt_after=halt_after,
        )
        logger.info(
            "supervised_pilot_candidates_built",
            read_only=True,
            no_execution=True,
            no_go_live=True,
            no_outbound=True,
            no_provider_calls=True,
            no_spend=True,
            overall_status=export.overall_status,
            operator_halt_status=export.operator_halt_status,
            outbound_enabled=export.outbound_enabled,
            go_live_permitted=False,
            execution_allowed=False,
            deployment_allowed=False,
            settings_applied=False,
            halt_changed=False,
            owner_approved=False,
            spend_allowed=False,
            executed=0,
            total_candidate_count=export.candidate_scope.total_candidate_count,
            ready_for_review_count=export.candidate_scope.ready_for_review_count,
            supervised_pilot_candidates_is_not_go_live=True,
        )
        return export


@dataclass(frozen=True)
class _CandidatePool:
    total: int
    ready: int
    blocked: int
    by_readiness: tuple[CandidateCount, ...]
    by_stage: tuple[CandidateCount, ...]
    by_source: tuple[CandidateCount, ...]
    by_specialty: tuple[CandidateCount, ...]
    by_state: tuple[CandidateCount, ...]
    by_score_band: tuple[CandidateCount, ...]
    by_website: tuple[CandidateCount, ...]
    blocked_reasons: tuple[CandidateCount, ...]


def _scan_candidate_pool(db: Session, *, owner_approval_blocked: bool) -> _CandidatePool:
    leads = list(db.scalars(select(Lead)).all())
    organizations = {
        item.id: item for item in db.scalars(select(Organization)).all()
    }
    latest_scores = _latest_score_bands(db)
    enriched_orgs = set(
        db.scalars(
            select(EnrichmentRun.organization_id).where(
                EnrichmentRun.source == WEBSITE_ENRICHMENT_SOURCE,
                EnrichmentRun.status == EnrichmentRunStatus.COMPLETED.value,
            )
        ).all()
    )
    evidenced_orgs = set(db.scalars(select(SourceEvidence.organization_id)).all())
    suppressed_orgs = {
        item
        for item in db.scalars(select(Suppression.organization_id)).all()
        if item is not None
    }
    consented_orgs = set(
        db.scalars(select(Contact.organization_id).where(Contact.email_verified.is_(True))).all()
    )
    readiness: Counter[str] = Counter()
    stages: Counter[str] = Counter()
    sources: Counter[str] = Counter()
    specialties: Counter[str] = Counter()
    states: Counter[str] = Counter()
    bands: Counter[str] = Counter()
    websites: Counter[str] = Counter()
    blocked_reasons: Counter[str] = Counter({key: 0 for key in BLOCKED_REASON_KEYS})
    ready = 0
    blocked = 0
    for lead in leads:
        organization = organizations.get(lead.organization_id)
        reasons = _blocked_reasons(
            lead,
            organization,
            score_band=latest_scores.get(lead.id),
            enriched=lead.organization_id in enriched_orgs,
            evidenced=lead.organization_id in evidenced_orgs,
            org_suppressed=lead.organization_id in suppressed_orgs,
            consented=lead.organization_id in consented_orgs,
            owner_approval_blocked=owner_approval_blocked,
        )
        band = latest_scores.get(lead.id) or "unset"
        readiness_key = _readiness_key(reasons, band)
        if readiness_key == "ready_for_owner_review":
            ready += 1
        if reasons:
            blocked += 1
        for reason in reasons:
            blocked_reasons[reason] += 1
        readiness[readiness_key] += 1
        stages[_safe_stage(lead.stage)] += 1
        sources[_safe_source(lead.source)] += 1
        specialties[_safe_specialty(organization.specialty if organization else None)] += 1
        states[_safe_state(organization.state if organization else None)] += 1
        bands[_safe_score_band(band)] += 1
        websites[_safe_website(organization.website_match_status if organization else None)] += 1
    return _CandidatePool(
        total=len(leads),
        ready=ready,
        blocked=blocked,
        by_readiness=_counts_from_counter(readiness, known=KNOWN_READINESS_KEYS),
        by_stage=_counts_from_counter(stages, known=KNOWN_STAGE_KEYS),
        by_source=_counts_from_counter(sources, known=KNOWN_SOURCE_KEYS),
        by_specialty=_counts_from_counter(specialties, known=KNOWN_SPECIALTY_KEYS),
        by_state=_state_counts(states),
        by_score_band=_counts_from_counter(bands, known=KNOWN_SCORE_BANDS),
        by_website=_counts_from_counter(websites, known=KNOWN_WEBSITE_KEYS),
        blocked_reasons=_counts_from_counter(blocked_reasons, known=BLOCKED_REASON_KEYS),
    )


def _latest_score_bands(db: Session) -> dict[UUID, str]:
    scores = db.scalars(
        select(LeadScore).order_by(LeadScore.created_at.desc(), LeadScore.id.desc())
    ).all()
    latest: dict[UUID, str] = {}
    for score in scores:
        if score.lead_id in latest:
            continue
        rationale = score.rationale if isinstance(score.rationale, dict) else {}
        raw = rationale.get("band")
        latest[score.lead_id] = (
            raw if isinstance(raw, str) and raw in KNOWN_SCORE_BANDS else "unset"
        )
    return latest


def _blocked_reasons(
    lead: Lead,
    organization: Organization | None,
    *,
    score_band: str | None,
    enriched: bool,
    evidenced: bool,
    org_suppressed: bool,
    consented: bool,
    owner_approval_blocked: bool,
) -> tuple[str, ...]:
    reasons: list[str] = []
    website_status = organization.website_match_status if organization is not None else None
    if website_status != WebsiteMatchStatus.VERIFIED.value:
        reasons.append("missing_website")
    if not enriched:
        reasons.append("missing_enrichment")
    if not evidenced:
        reasons.append("missing_evidence")
    if score_band is None or score_band == "unset":
        reasons.append("missing_score")
    if lead.stage == LeadStage.SUPPRESSED.value or org_suppressed:
        reasons.append("suppression")
    if not consented:
        reasons.append("consent")
    if owner_approval_blocked:
        reasons.append("owner_approval")
    return tuple(reasons)


def _readiness_key(reasons: Sequence[str], band: str) -> str:
    if reasons:
        return FindingSeverity.BLOCKED.value
    if band in READY_SCORE_BANDS:
        return "ready_for_owner_review"
    if band == ScoreBand.RESEARCH.value:
        return ScoreBand.RESEARCH.value
    if band == ScoreBand.DISQUALIFIED.value:
        return ScoreBand.DISQUALIFIED.value
    if band == ScoreBand.LOW.value:
        return FindingSeverity.WARNING.value
    return "unset"


def _from_sources(
    plan: SupervisedPilotPlan,
    dashboard: DashboardSummary,
    pool: _CandidatePool,
    *,
    halt_before: HaltStatus,
    halt_after: HaltStatus,
) -> SupervisedPilotCandidates:
    missing_prereqs = _unique_sorted(
        item.key for item in plan.prerequisites if _needs_follow_up(item.status)
    )
    candidate_status = _candidate_status(pool, plan)
    overall_status = _worst_status(plan.overall_status, candidate_status)
    scope = _candidate_scope(plan.pilot_scope, pool)
    next_actions = _next_actions(plan, pool, overall_status)
    return SupervisedPilotCandidates(
        generated_at=datetime.now(tz=UTC),
        packet_kind=PACKET_KIND,
        purpose=PACKET_PURPOSE,
        overall_status=overall_status,
        read_only=True,
        no_execution=True,
        no_go_live=True,
        no_deployment=True,
        no_outbound=True,
        no_provider_calls=True,
        no_spend=True,
        dry_run_only=True,
        executed=0,
        execution_attempted=False,
        outbound_attempted=False,
        live_call_attempted=False,
        recommendation_applied=False,
        spend_attempted=False,
        spend_allowed=False,
        campaign_launched=False,
        pages_published=False,
        ads_launched=False,
        owner_approved=False,
        settings_applied=False,
        halt_changed=False,
        live_action=False,
        execution_allowed=False,
        future_execution_phase_exists=False,
        future_deployment_phase_exists=False,
        go_live_permitted=False,
        deployment_allowed=False,
        deployment_attempted=False,
        deployed=False,
        build_allowed=False,
        artifact_publish_allowed=False,
        container_build_attempted=False,
        artifact_publish_attempted=False,
        outbound_enabled=plan.outbound_enabled,
        live_providers_enabled=plan.live_providers_enabled,
        manual_review_only=True,
        supervised_pilot_candidates_is_not_go_live=True,
        export_is_not_permission_to_go_live=True,
        export_is_not_execution=True,
        supervised_pilot_plan_is_not_go_live=True,
        rehearsal_outcome_report_is_not_go_live=True,
        go_live_rehearsal_checklist_is_not_go_live=True,
        provider_setup_checklist_is_not_go_live=True,
        operator_halt_status=halt_after.value,
        operator_halt_before=halt_before.value,
        operator_halt_after=halt_after.value,
        candidate_scope=scope,
        candidate_counts_by_readiness=pool.by_readiness,
        candidate_counts_by_status=_status_counts(dashboard),
        candidate_counts_by_stage=pool.by_stage,
        candidate_counts_by_source=pool.by_source,
        candidate_counts_by_specialty=pool.by_specialty,
        candidate_counts_by_state=pool.by_state,
        scoring_distribution=pool.by_score_band,
        website_match_counts=pool.by_website,
        outreach_status_counts=_counts_from_mapping(dashboard.outreach_plans.by_status),
        suppression_counts_by_reason=_counts_from_mapping(dashboard.suppressions.by_reason),
        kill_switch_outbound_disabled=not plan.outbound_enabled,
        kill_switch_operator_halt_active=halt_after is HaltStatus.HALTED,
        kill_switch_live_providers_closed=not plan.live_providers_enabled,
        suppression_record_count=dashboard.suppressions.records,
        blocked_counts=pool.blocked_reasons,
        missing_prerequisite_codes=missing_prereqs,
        remaining_owner_approval_types=tuple(plan.remaining_owner_approval_types),
        closed_provider_flag_names=tuple(plan.closed_provider_flag_names),
        missing_credential_names=tuple(plan.missing_credential_names),
        missing_config_names=tuple(plan.missing_config_names),
        blocker_codes=tuple(plan.blocker_codes),
        gate_codes=tuple(plan.gate_codes),
        cli_command=CLI_COMMAND,
        http_route=HTTP_ROUTE,
        source_pilot_plan_command=PILOT_CLI_COMMAND,
        source_pilot_plan_route=PILOT_HTTP_ROUTE,
        source_pilot_plan_html_route=PILOT_HTML_ROUTE,
        source_pilot_plan_overall_status=plan.overall_status,
        source_outcome_command=plan.source_outcome_command,
        source_outcome_route=plan.source_outcome_route,
        source_outcome_overall_status=plan.source_outcome_overall_status,
        source_rehearsal_command=plan.source_rehearsal_command,
        source_rehearsal_route=plan.source_rehearsal_route,
        source_rehearsal_overall_status=plan.source_rehearsal_overall_status,
        source_launch_readiness_command=plan.source_launch_readiness_command,
        source_launch_readiness_route=plan.source_launch_readiness_route,
        source_launch_readiness_overall_status=plan.source_launch_readiness_overall_status,
        source_index_command=plan.source_index_command,
        source_index_route=plan.source_index_route,
        source_index_overall_status=plan.source_index_overall_status,
        source_provider_setup_command=plan.source_provider_setup_command,
        source_provider_setup_route=plan.source_provider_setup_route,
        source_provider_setup_overall_status=plan.source_provider_setup_overall_status,
        related_commands=RELATED_COMMANDS,
        related_routes=RELATED_ROUTES,
        local_git=plan.local_git,
        next_actions=next_actions,
    )


def _candidate_status(pool: _CandidatePool, plan: SupervisedPilotPlan) -> str:
    if plan.outbound_enabled or plan.halt_changed or plan.go_live_permitted:
        return FindingSeverity.BLOCKED.value
    if pool.total == 0:
        return FindingSeverity.WARNING.value
    if pool.ready == 0:
        return FindingSeverity.WARNING.value
    return "ready_for_owner_review"


def _candidate_scope(
    plan_scope: PilotScopeRecommendation,
    pool: _CandidatePool,
) -> CandidateScopeRecommendation:
    suggested = min(plan_scope.suggested_max_leads, pool.ready)
    return CandidateScopeRecommendation(
        suggested_candidate_count=suggested,
        suggested_max_leads=plan_scope.suggested_max_leads,
        suggested_max_drafts=plan_scope.suggested_max_drafts,
        suggested_max_manually_reviewed_sends=plan_scope.suggested_max_manually_reviewed_sends,
        suggested_max_daily_activity=plan_scope.suggested_max_daily_activity,
        ready_for_review_count=pool.ready,
        blocked_candidate_count=pool.blocked,
        total_candidate_count=pool.total,
        stop_conditions=plan_scope.stop_conditions,
        recommendation_summary=_safe_text(
            "Supervised first-pilot candidate counts only. "
            f"total={pool.total} ready_for_review={pool.ready} "
            f"blocked={pool.blocked} "
            f"suggested_candidate_count={suggested} "
            f"max_leads={SUGGESTED_MAX_LEADS} "
            f"max_drafts={SUGGESTED_MAX_DRAFTS} "
            f"max_manually_reviewed_sends={SUGGESTED_MAX_MANUALLY_REVIEWED_SENDS} "
            f"max_daily_activity={SUGGESTED_MAX_DAILY_ACTIVITY}. "
            "This export does not select, enroll, send, or contact candidates."
        ),
    )


def _status_counts(dashboard: DashboardSummary) -> tuple[CandidateCount, ...]:
    return _counts_from_mapping(
        {
            "planned": dashboard.outreach_plans.planned_count,
            "skipped": dashboard.outreach_plans.skipped_count,
            "suppressed": dashboard.outreach_plans.suppressed_count,
            "blocked": dashboard.outreach_plans.blocked_count,
        }
    )


def _next_actions(
    plan: SupervisedPilotPlan,
    pool: _CandidatePool,
    overall_status: str,
) -> tuple[CandidateNextAction, ...]:
    actions = [
        _action(
            CANDIDATES_NOT_GO_LIVE_CODE,
            FindingSeverity.INFO.value,
            (
                "This supervised pilot candidate readiness export is a "
                "sanitized count-only review packet. It is not permission "
                "to go live and not an execution surface."
            ),
            command_name=CLI_COMMAND,
            json_route=HTTP_ROUTE,
            html_route=HTML_ROUTE,
        ),
        _action(
            EXECUTION_DISABLED_CODE,
            FindingSeverity.INFO.value,
            (
                "Execution remains disabled. This export does not select "
                "candidates, run commands, apply settings, lift halt, "
                "enable outbound, deploy, build, publish, send, or spend."
            ),
            command_name=CLI_COMMAND,
            json_route=HTTP_ROUTE,
            html_route=HTML_ROUTE,
        ),
        _action(
            NextActionCode.SUPERVISED_PILOT_PLAN_IS_NOT_GO_LIVE.value,
            plan.overall_status,
            (
                "Review the source supervised pilot launch plan. "
                "Planning export only; it is not permission to go live."
            ),
            command_name=PILOT_CLI_COMMAND,
            json_route=PILOT_HTTP_ROUTE,
            html_route=PILOT_HTML_ROUTE,
        ),
        _action(
            NextActionCode.KEEP_OUTBOUND_DISABLED.value,
            FindingSeverity.INFO.value,
            "Keep OUTBOUND_ENABLED=false.",
            command_name="launch-readiness",
            json_route="/internal/launch-readiness",
            config_name="OUTBOUND_ENABLED",
        ),
    ]
    if pool.ready == 0:
        actions.append(
            _action(
                "review_candidate_blockers",
                overall_status,
                (
                    "No ready-for-review candidates are available. Review "
                    "blocked-count reasons as codes only. Do not scrape, "
                    "contact, or invent missing facts."
                ),
                command_name=CLI_COMMAND,
                json_route=HTTP_ROUTE,
            )
        )
    return tuple(actions)


def _action(
    code: str,
    status: str,
    label: str,
    *,
    command_name: str | None = None,
    json_route: str | None = None,
    html_route: str | None = None,
    config_name: str | None = None,
) -> CandidateNextAction:
    return CandidateNextAction(
        code=_safe_text(code),
        status=_safe_text(status) or FindingSeverity.INFO.value,
        label=_safe_text(label),
        command_name=_safe_optional(command_name),
        json_route=_safe_optional(json_route),
        html_route=_safe_optional(html_route),
        config_name=_safe_optional(config_name),
    )


def _needs_follow_up(status: str) -> bool:
    return status not in {FindingSeverity.INFO.value, "ready_for_owner_review"}


def _counts_from_counter(
    tally: Counter[str],
    *,
    known: Sequence[str],
) -> tuple[CandidateCount, ...]:
    counts: Counter[str] = Counter()
    for key in known:
        counts[key] = 0
    for raw, value in tally.items():
        key = _safe_text(raw)
        if key:
            counts[key] += int(value)
    return tuple(CandidateCount(key=key, count=counts[key]) for key in sorted(counts))


def _counts_from_mapping(mapping: dict[str, int]) -> tuple[CandidateCount, ...]:
    cleaned: dict[str, int] = {}
    for raw, value in mapping.items():
        key = _safe_text(raw)
        if key:
            cleaned[key] = int(value)
    return tuple(CandidateCount(key=key, count=cleaned[key]) for key in sorted(cleaned))


def _state_counts(tally: Counter[str]) -> tuple[CandidateCount, ...]:
    cleaned = {
        _safe_text(key): int(value)
        for key, value in tally.items()
        if _safe_text(key)
    }
    return tuple(CandidateCount(key=key, count=cleaned[key]) for key in sorted(cleaned))


def _safe_stage(value: str | None) -> str:
    text = _safe_text(value)
    if text in {item.value for item in LeadStage}:
        return text
    return "other" if text else "unset"


def _safe_source(value: str | None) -> str:
    text = _safe_text(value).lower()
    if not text:
        return "unset"
    if text in GENERIC_SOURCES:
        return text
    return "other"


def _safe_specialty(value: str | None) -> str:
    if value is None or not str(value).strip():
        return "unset"
    return classify_specialty(value).value


def _safe_state(value: str | None) -> str:
    text = _safe_text(value).upper()
    if text in US_STATE_CODES:
        return text
    return "unset"


def _safe_score_band(value: str | None) -> str:
    text = _safe_text(value)
    if text in {item.value for item in ScoreBand}:
        return text
    return "unset"


def _safe_website(value: str | None) -> str:
    text = _safe_text(value)
    if text in {item.value for item in WebsiteMatchStatus}:
        return text
    return "unset"


def _worst_status(*values: str) -> str:
    cleaned = [_safe_text(item) or FindingSeverity.INFO.value for item in values if item]
    if not cleaned:
        return FindingSeverity.INFO.value
    return max(cleaned, key=lambda item: _STATUS_RANK.get(item, 0))


def _unique_sorted(values: Iterable[str | None]) -> tuple[str, ...]:
    cleaned = [_safe_text(item) for item in values if item]
    return tuple(sorted({item for item in cleaned if item}))


def _safe_optional(value: str | None) -> str | None:
    cleaned = _safe_text(value) if value is not None else ""
    return cleaned or None


def _safe_text(value: object) -> str:
    if value is None:
        return ""
    text = sanitize_operator_text(str(value))
    return text or ""


def _bool_text(value: object) -> str:
    return "true" if value else "false"


def supervised_pilot_candidates_payload(export: SupervisedPilotCandidates) -> dict[str, Any]:
    return {
        "generated_at": export.generated_at.isoformat(),
        "packet_kind": export.packet_kind,
        "purpose": export.purpose,
        "overall_status": export.overall_status,
        "read_only": True,
        "no_execution": True,
        "no_go_live": True,
        "no_deployment": True,
        "no_outbound": True,
        "no_provider_calls": True,
        "no_spend": True,
        "dry_run_only": True,
        "executed": 0,
        "execution_attempted": False,
        "outbound_attempted": False,
        "live_call_attempted": False,
        "recommendation_applied": False,
        "spend_attempted": False,
        "spend_allowed": False,
        "campaign_launched": False,
        "pages_published": False,
        "ads_launched": False,
        "owner_approved": False,
        "settings_applied": False,
        "halt_changed": False,
        "live_action": False,
        "execution_allowed": False,
        "future_execution_phase_exists": False,
        "future_deployment_phase_exists": False,
        "go_live_permitted": False,
        "deployment_allowed": False,
        "deployment_attempted": False,
        "deployed": False,
        "build_allowed": False,
        "artifact_publish_allowed": False,
        "container_build_attempted": False,
        "artifact_publish_attempted": False,
        "outbound_enabled": export.outbound_enabled,
        "live_providers_enabled": export.live_providers_enabled,
        "manual_review_only": True,
        "supervised_pilot_candidates_is_not_go_live": True,
        "export_is_not_permission_to_go_live": True,
        "export_is_not_execution": True,
        "supervised_pilot_plan_is_not_go_live": True,
        "rehearsal_outcome_report_is_not_go_live": True,
        "go_live_rehearsal_checklist_is_not_go_live": True,
        "provider_setup_checklist_is_not_go_live": True,
        "operator_halt_status": export.operator_halt_status,
        "operator_halt_before": export.operator_halt_before,
        "operator_halt_after": export.operator_halt_after,
        "candidate_scope": {
            "suggested_candidate_count": export.candidate_scope.suggested_candidate_count,
            "suggested_max_leads": export.candidate_scope.suggested_max_leads,
            "suggested_max_drafts": export.candidate_scope.suggested_max_drafts,
            "suggested_max_manually_reviewed_sends": (
                export.candidate_scope.suggested_max_manually_reviewed_sends
            ),
            "suggested_max_daily_activity": export.candidate_scope.suggested_max_daily_activity,
            "ready_for_review_count": export.candidate_scope.ready_for_review_count,
            "blocked_candidate_count": export.candidate_scope.blocked_candidate_count,
            "total_candidate_count": export.candidate_scope.total_candidate_count,
            "stop_conditions": list(export.candidate_scope.stop_conditions),
            "recommendation_summary": export.candidate_scope.recommendation_summary,
        },
        "candidate_counts_by_readiness": [
            _count_payload(item) for item in export.candidate_counts_by_readiness
        ],
        "candidate_counts_by_status": [
            _count_payload(item) for item in export.candidate_counts_by_status
        ],
        "candidate_counts_by_stage": [
            _count_payload(item) for item in export.candidate_counts_by_stage
        ],
        "candidate_counts_by_source": [
            _count_payload(item) for item in export.candidate_counts_by_source
        ],
        "candidate_counts_by_specialty": [
            _count_payload(item) for item in export.candidate_counts_by_specialty
        ],
        "candidate_counts_by_state": [
            _count_payload(item) for item in export.candidate_counts_by_state
        ],
        "scoring_distribution": [_count_payload(item) for item in export.scoring_distribution],
        "website_match_counts": [_count_payload(item) for item in export.website_match_counts],
        "outreach_status_counts": [_count_payload(item) for item in export.outreach_status_counts],
        "suppression_counts_by_reason": [
            _count_payload(item) for item in export.suppression_counts_by_reason
        ],
        "kill_switch_outbound_disabled": export.kill_switch_outbound_disabled,
        "kill_switch_operator_halt_active": export.kill_switch_operator_halt_active,
        "kill_switch_live_providers_closed": export.kill_switch_live_providers_closed,
        "suppression_record_count": export.suppression_record_count,
        "blocked_counts": [_count_payload(item) for item in export.blocked_counts],
        "missing_prerequisite_codes": list(export.missing_prerequisite_codes),
        "remaining_owner_approval_types": list(export.remaining_owner_approval_types),
        "closed_provider_flag_names": list(export.closed_provider_flag_names),
        "missing_credential_names": list(export.missing_credential_names),
        "missing_config_names": list(export.missing_config_names),
        "blocker_codes": list(export.blocker_codes),
        "gate_codes": list(export.gate_codes),
        "cli_command": CLI_COMMAND,
        "http_route": HTTP_ROUTE,
        "source_pilot_plan_command": export.source_pilot_plan_command,
        "source_pilot_plan_route": export.source_pilot_plan_route,
        "source_pilot_plan_html_route": export.source_pilot_plan_html_route,
        "source_pilot_plan_overall_status": export.source_pilot_plan_overall_status,
        "source_outcome_command": export.source_outcome_command,
        "source_outcome_route": export.source_outcome_route,
        "source_outcome_overall_status": export.source_outcome_overall_status,
        "source_rehearsal_command": export.source_rehearsal_command,
        "source_rehearsal_route": export.source_rehearsal_route,
        "source_rehearsal_overall_status": export.source_rehearsal_overall_status,
        "source_launch_readiness_command": export.source_launch_readiness_command,
        "source_launch_readiness_route": export.source_launch_readiness_route,
        "source_launch_readiness_overall_status": export.source_launch_readiness_overall_status,
        "source_index_command": export.source_index_command,
        "source_index_route": export.source_index_route,
        "source_index_overall_status": export.source_index_overall_status,
        "source_provider_setup_command": export.source_provider_setup_command,
        "source_provider_setup_route": export.source_provider_setup_route,
        "source_provider_setup_overall_status": export.source_provider_setup_overall_status,
        "related_commands": list(export.related_commands),
        "related_routes": list(export.related_routes),
        "local_git": {
            "available": export.local_git.available,
            "current_branch": export.local_git.current_branch,
            "current_sha": export.local_git.current_sha,
            "working_tree_status": export.local_git.working_tree_status,
            "git_provider_called": False,
            "github_actions_called": False,
        },
        "next_actions": [_action_payload(action) for action in export.next_actions],
    }


def _count_payload(item: CandidateCount) -> dict[str, Any]:
    return {"key": item.key, "count": item.count}


def _action_payload(action: CandidateNextAction) -> dict[str, Any]:
    return {
        "code": action.code,
        "status": action.status,
        "label": action.label,
        "command_name": action.command_name,
        "json_route": action.json_route,
        "html_route": action.html_route,
        "config_name": action.config_name,
    }


def format_supervised_pilot_candidates(
    export: SupervisedPilotCandidates,
    *,
    as_json: bool = False,
) -> str:
    payload = sanitize_mapping(supervised_pilot_candidates_payload(export))
    if as_json:
        return json.dumps(payload, sort_keys=True)
    return _format_markdown(export, payload)


def _format_markdown(export: SupervisedPilotCandidates, payload: dict[str, Any]) -> str:
    lines = [
        "# Supervised pilot candidate readiness",
        "",
        "This export is a sanitized candidate-readiness review packet over "
        "existing discovery, enrichment, scoring, outreach, supervised pilot "
        "plan, provider setup, rehearsal outcome, and launch-readiness "
        "surfaces. It reuses those services as source material and never "
        "executes commands, applies settings, lifts halt, enables outbound, "
        "deploys, builds, publishes, sends, or spends. It is not permission "
        "to go live and not an execution surface.",
        "",
        f"- overall: {payload['overall_status']}",
        f"- packet_kind: {payload['packet_kind']}",
        f"- purpose: {payload['purpose']}",
        f"- read_only: {_bool_text(payload['read_only'])}",
        f"- no_execution: {_bool_text(payload['no_execution'])}",
        f"- no_go_live: {_bool_text(payload['no_go_live'])}",
        f"- no_deployment: {_bool_text(payload['no_deployment'])}",
        f"- no_outbound: {_bool_text(payload['no_outbound'])}",
        f"- no_provider_calls: {_bool_text(payload['no_provider_calls'])}",
        f"- no_spend: {_bool_text(payload['no_spend'])}",
        f"- dry_run_only: {_bool_text(payload['dry_run_only'])}",
        f"- executed: {payload['executed']}",
        f"- owner_approved: {_bool_text(payload['owner_approved'])}",
        f"- settings_applied: {_bool_text(payload['settings_applied'])}",
        f"- halt_changed: {_bool_text(payload['halt_changed'])}",
        f"- live_action: {_bool_text(payload['live_action'])}",
        f"- execution_allowed: {_bool_text(payload['execution_allowed'])}",
        f"- go_live_permitted: {_bool_text(payload['go_live_permitted'])}",
        f"- deployment_allowed: {_bool_text(payload['deployment_allowed'])}",
        f"- spend_allowed: {_bool_text(payload['spend_allowed'])}",
        f"- manual_review_only: {_bool_text(payload['manual_review_only'])}",
        (
            "- supervised_pilot_candidates_is_not_go_live: "
            f"{_bool_text(payload['supervised_pilot_candidates_is_not_go_live'])}"
        ),
        (
            "- export_is_not_permission_to_go_live: "
            f"{_bool_text(payload['export_is_not_permission_to_go_live'])}"
        ),
        f"- export_is_not_execution: {_bool_text(payload['export_is_not_execution'])}",
        (
            "- operator_halt: "
            f"status={payload['operator_halt_status']} "
            f"before={payload['operator_halt_before']} "
            f"after={payload['operator_halt_after']}"
        ),
        f"- outbound_enabled: {_bool_text(payload['outbound_enabled'])}",
        f"- live_providers_enabled: {_bool_text(payload['live_providers_enabled'])}",
        f"- cli_command: {payload['cli_command']}",
        f"- http_route: {payload['http_route']}",
        f"- source_pilot_plan_command: {payload['source_pilot_plan_command']}",
        f"- source_outcome_command: {payload['source_outcome_command']}",
        f"- source_rehearsal_command: {payload['source_rehearsal_command']}",
        f"- source_launch_readiness_command: {payload['source_launch_readiness_command']}",
        f"- source_index_command: {payload['source_index_command']}",
        f"- source_provider_setup_command: {payload['source_provider_setup_command']}",
        f"- blocker_codes: {_format_codes(export.blocker_codes)}",
        f"- gate_codes: {_format_codes(export.gate_codes)}",
        f"- missing_prerequisite_codes: {_format_codes(export.missing_prerequisite_codes)}",
        f"- remaining_owner_approval_types: {_format_codes(export.remaining_owner_approval_types)}",
        f"- missing_credential_names: {_format_codes(export.missing_credential_names)}",
        f"- missing_config_names: {_format_codes(export.missing_config_names)}",
        f"- closed_provider_flag_names: {_format_codes(export.closed_provider_flag_names)}",
        "",
        "## Live-blocking flags",
        f"- OUTBOUND_ENABLED={_bool_text(export.outbound_enabled)}",
        f"- operator_halt_status={export.operator_halt_status}",
        f"- live_providers_enabled={_bool_text(export.live_providers_enabled)}",
        "- read_only=true",
        "- no_execution=true",
        "- no_go_live=true",
        "- no_outbound=true",
        "- no_provider_calls=true",
        "- no_spend=true",
        "- manual_review_only=true",
        "- execution_allowed=false",
        "- go_live_permitted=false",
        "- deployment_allowed=false",
        "- spend_allowed=false",
        "- settings_applied=false",
        "- halt_changed=false",
        "- owner_approved=false",
        "- supervised_pilot_candidates_is_not_go_live=true",
        "- export_is_not_permission_to_go_live=true",
        "- export_is_not_execution=true",
        f"- kill_switch_outbound_disabled: {_bool_text(export.kill_switch_outbound_disabled)}",
        (
            "- kill_switch_operator_halt_active: "
            f"{_bool_text(export.kill_switch_operator_halt_active)}"
        ),
        (
            "- kill_switch_live_providers_closed: "
            f"{_bool_text(export.kill_switch_live_providers_closed)}"
        ),
        f"- suppression_record_count: {export.suppression_record_count}",
        f"- local_git_available: {_bool_text(export.local_git.available)}",
        f"- current_branch: {export.local_git.current_branch}",
        f"- current_sha: {export.local_git.current_sha}",
        f"- working_tree_status: {export.local_git.working_tree_status}",
        f"- git_provider_called: {_bool_text(export.local_git.git_provider_called)}",
        f"- github_actions_called: {_bool_text(export.local_git.github_actions_called)}",
        "",
        "## Pilot candidate scope recommendation",
        f"- suggested_candidate_count: {export.candidate_scope.suggested_candidate_count}",
        f"- suggested_max_leads: {export.candidate_scope.suggested_max_leads}",
        f"- suggested_max_drafts: {export.candidate_scope.suggested_max_drafts}",
        (
            "- suggested_max_manually_reviewed_sends: "
            f"{export.candidate_scope.suggested_max_manually_reviewed_sends}"
        ),
        f"- suggested_max_daily_activity: {export.candidate_scope.suggested_max_daily_activity}",
        f"- ready_for_review_count: {export.candidate_scope.ready_for_review_count}",
        f"- blocked_candidate_count: {export.candidate_scope.blocked_candidate_count}",
        f"- total_candidate_count: {export.candidate_scope.total_candidate_count}",
        f"- stop_conditions: {_format_codes(export.candidate_scope.stop_conditions)}",
        f"- recommendation_summary: {export.candidate_scope.recommendation_summary}",
        "",
        "## Candidate counts by readiness",
    ]
    _append_counts(lines, export.candidate_counts_by_readiness)
    lines.extend(["", "## Candidate counts by status"])
    _append_counts(lines, export.candidate_counts_by_status)
    lines.extend(["", "## Candidate counts by stage"])
    _append_counts(lines, export.candidate_counts_by_stage)
    lines.extend(["", "## Candidate counts by source"])
    _append_counts(lines, export.candidate_counts_by_source)
    lines.extend(["", "## Candidate counts by specialty category"])
    _append_counts(lines, export.candidate_counts_by_specialty)
    lines.extend(["", "## Candidate counts by state"])
    _append_counts(lines, export.candidate_counts_by_state)
    lines.extend(["", "## Scoring distribution"])
    _append_counts(lines, export.scoring_distribution)
    lines.extend(["", "## Blocked-count reasons"])
    _append_counts(lines, export.blocked_counts)
    lines.extend(["", "## Owner next actions"])
    for action in export.next_actions:
        command_name = action.command_name or "-"
        json_route = action.json_route or "-"
        html_route = action.html_route or "-"
        config_name = action.config_name or "-"
        lines.append(
            f"- [{action.status}] {action.code} command={command_name} "
            f"json_route={json_route} html_route={html_route} "
            f"config_name={config_name} label={action.label}"
        )
    if not export.next_actions:
        lines.append("- next_actions: none")
    return "\n".join(lines)


def _append_counts(lines: list[str], items: Sequence[CandidateCount]) -> None:
    visible = [item for item in items if item.count or item.key in BLOCKED_REASON_KEYS]
    if not visible:
        lines.append("- counts: none")
        return
    for item in visible:
        lines.append(f"- {item.key}: {item.count}")


def _format_codes(values: Sequence[str]) -> str:
    return ",".join(values) if values else "-"
