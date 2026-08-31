"""Dry-run acquisition channel planning: operator-review drafts only.

Reads stored specialty/geography aggregates and optional operator seed inputs.
It never launches ads, publishes pages, spends money, or calls live providers.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from vyro_growth.domain import (
    AcquisitionChannel,
    ChannelPlanRunStatus,
    ChannelPlanType,
    LeadStage,
    RecommendationApprovalStatus,
    RecommendationPriority,
    ReplyIntent,
)
from vyro_growth.models import (
    Activity,
    ChannelPlan,
    ChannelPlanRun,
    Lead,
    LeadScore,
    Organization,
    ReplyClassification,
)
from vyro_growth.services.operator_halt import HaltStatus, read_operator_halt
from vyro_growth.services.review_queue import sanitize_operator_text

logger = structlog.get_logger(__name__)

CHANNEL_PLANNING_ACTOR = "channel_planning"
CHANNEL_PLANNING_MODEL_VERSION = "channel-planning-v1"
MAX_COHORTS = 5
MAX_SEED_KEYWORDS = 5
MAX_TOKEN_LENGTH = 80
SAFE_TOKEN_RE = re.compile(r"[^A-Za-z0-9 +/#&.,'-]+")
CONVERSION_STAGES = frozenset(
    {
        LeadStage.INTERESTED.value,
        LeadStage.QUALIFICATION_PENDING.value,
        LeadStage.MEETING_READY.value,
        LeadStage.MEETING_BOOKED.value,
        LeadStage.WON.value,
    }
)


@dataclass(frozen=True)
class ChannelPlanSeeds:
    specialty: str | None = None
    geography: str | None = None
    keywords: tuple[str, ...] = ()
    partner_type: str | None = None

    def as_refs(self) -> dict[str, object]:
        refs: dict[str, object] = {}
        if self.specialty:
            refs["seed_specialty"] = self.specialty
        if self.geography:
            refs["seed_geography"] = self.geography
        if self.keywords:
            refs["seed_keywords"] = list(self.keywords)
        if self.partner_type:
            refs["seed_partner_type"] = self.partner_type
        return refs

    def has_any(self) -> bool:
        return bool(self.specialty or self.geography or self.keywords or self.partner_type)


@dataclass(frozen=True)
class ChannelPlanDraft:
    plan_key: str
    channel: AcquisitionChannel
    plan_type: ChannelPlanType
    title: str
    summary: str
    target_specialty: str | None
    target_geography: str | None
    target_icp: str | None
    priority: RecommendationPriority
    confidence: float
    source_metrics: dict[str, object]
    seed_input_refs: dict[str, object]


@dataclass(frozen=True)
class ChannelPlanView:
    id: UUID
    plan_key: str
    channel: str
    plan_type: str
    title: str
    summary: str
    target_specialty: str | None
    target_geography: str | None
    target_icp: str | None
    priority: str
    confidence: float
    source_metrics: dict[str, object]
    seed_input_refs: dict[str, object]
    generated_at: datetime
    approval_status: str
    dry_run_only: bool
    no_spend: bool
    launched: bool
    spend_attempted: bool
    campaign_launched: bool
    pages_published: bool
    outbound_attempted: bool


@dataclass(frozen=True)
class ChannelPlanRunResult:
    channel_plan_run_id: UUID
    status: ChannelPlanRunStatus
    model_version: str
    snapshot_fingerprint: str
    plan_count: int
    reused_existing: bool
    dry_run_only: bool
    no_spend: bool
    spend_attempted: bool
    campaign_launched: bool
    pages_published: bool
    outbound_attempted: bool
    live_call_attempted: bool
    generated_at: datetime
    operator_halt_before: str
    operator_halt_after: str
    plans: tuple[ChannelPlanView, ...]


@dataclass(frozen=True)
class SpecialtyCohort:
    specialty: str
    state: str
    organizations: int
    leads: int
    conversion_leads: int
    conversion_rate: float
    score_bands: dict[str, int]

    def as_metrics(self) -> dict[str, object]:
        return {
            "specialty": self.specialty,
            "state": self.state,
            "organizations": self.organizations,
            "leads": self.leads,
            "conversion_leads": self.conversion_leads,
            "conversion_rate": self.conversion_rate,
            "score_bands": dict(self.score_bands),
        }


@dataclass(frozen=True)
class ChannelPlanningSnapshot:
    organization_count: int
    lead_count: int
    referral_intent_count: int
    specialty_geography: tuple[SpecialtyCohort, ...]


class ChannelPlanningService:
    """Produce dry-run acquisition channel plans from stored aggregates and seeds."""

    def plan(
        self,
        db: Session,
        *,
        seeds: ChannelPlanSeeds | None = None,
        commit: bool = True,
    ) -> ChannelPlanRunResult:
        halt_before = read_operator_halt(db)
        generated_at = datetime.now(tz=UTC)
        sanitized_seeds = sanitize_seeds(seeds)
        snapshot = _collect_snapshot(db)
        payload = _sanitized_snapshot(snapshot, sanitized_seeds)
        fingerprint = _fingerprint(payload)
        existing = db.scalar(
            select(ChannelPlanRun).where(ChannelPlanRun.snapshot_fingerprint == fingerprint)
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
                "channel_plan_run_reused",
                channel_plan_run_id=str(existing.id),
                plan_count=existing.plan_count,
                snapshot_fingerprint=fingerprint,
                spend_attempted=False,
                outbound_attempted=False,
            )
            return result

        drafts = _build_plans(snapshot, sanitized_seeds)
        run = ChannelPlanRun(
            status=ChannelPlanRunStatus.COMPLETED.value,
            model_version=CHANNEL_PLANNING_MODEL_VERSION,
            snapshot_fingerprint=fingerprint,
            plan_count=len(drafts),
            reused_count=0,
            dry_run_only=True,
            no_spend=True,
            spend_attempted=False,
            campaign_launched=False,
            pages_published=False,
            outbound_attempted=False,
            live_call_attempted=False,
            input_params={
                "dry_run_only": True,
                "no_spend": True,
                "auto_launch": False,
                "seeds": sanitized_seeds.as_refs(),
            },
            snapshot_json=payload,
            started_at=generated_at,
            finished_at=generated_at,
        )
        db.add(run)
        db.flush()
        for draft in drafts:
            db.add(
                ChannelPlan(
                    channel_plan_run_id=run.id,
                    plan_key=draft.plan_key,
                    channel=draft.channel.value,
                    plan_type=draft.plan_type.value,
                    title=draft.title,
                    summary=draft.summary,
                    target_specialty=draft.target_specialty,
                    target_geography=draft.target_geography,
                    target_icp=draft.target_icp,
                    priority=draft.priority.value,
                    confidence=draft.confidence,
                    source_metrics_json=draft.source_metrics,
                    seed_input_refs_json=draft.seed_input_refs,
                    generated_at=generated_at,
                    approval_status=RecommendationApprovalStatus.PENDING_OPERATOR_REVIEW.value,
                    dry_run_only=True,
                    no_spend=True,
                    launched=False,
                    spend_attempted=False,
                    campaign_launched=False,
                    pages_published=False,
                    outbound_attempted=False,
                )
            )
        db.add(
            Activity(
                lead_id=None,
                actor=CHANNEL_PLANNING_ACTOR,
                action="channel_plans_generated",
                details={
                    "channel_plan_run_id": str(run.id),
                    "plan_count": len(drafts),
                    "channels": [draft.channel.value for draft in drafts],
                    "dry_run_only": True,
                    "no_spend": True,
                    "spend_attempted": False,
                    "campaign_launched": False,
                    "pages_published": False,
                    "outbound_attempted": False,
                },
            )
        )
        db.flush()
        halt_after = read_operator_halt(db)
        if halt_after is not halt_before:
            raise RuntimeError("channel planning must not change operator halt status")
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
            "channel_plan_run_completed",
            channel_plan_run_id=str(run.id),
            plan_count=len(drafts),
            snapshot_fingerprint=fingerprint,
            spend_attempted=False,
            outbound_attempted=False,
        )
        return result

    def latest(self, db: Session) -> ChannelPlanRunResult | None:
        run = db.scalars(select(ChannelPlanRun).order_by(ChannelPlanRun.created_at.desc())).first()
        if run is None:
            return None
        halt = read_operator_halt(db)
        return self._view(db, run, halt_before=halt, halt_after=halt, reused=True)

    def _view(
        self,
        db: Session,
        run: ChannelPlanRun,
        *,
        halt_before: HaltStatus,
        halt_after: HaltStatus,
        reused: bool,
    ) -> ChannelPlanRunResult:
        rows = list(
            db.scalars(
                select(ChannelPlan)
                .where(ChannelPlan.channel_plan_run_id == run.id)
                .order_by(ChannelPlan.channel, ChannelPlan.plan_key)
            )
        )
        return ChannelPlanRunResult(
            channel_plan_run_id=run.id,
            status=ChannelPlanRunStatus(run.status),
            model_version=run.model_version,
            snapshot_fingerprint=run.snapshot_fingerprint,
            plan_count=run.plan_count,
            reused_existing=reused,
            dry_run_only=run.dry_run_only,
            no_spend=run.no_spend,
            spend_attempted=run.spend_attempted,
            campaign_launched=run.campaign_launched,
            pages_published=run.pages_published,
            outbound_attempted=run.outbound_attempted,
            live_call_attempted=run.live_call_attempted,
            generated_at=run.finished_at or run.created_at,
            operator_halt_before=halt_before.value,
            operator_halt_after=halt_after.value,
            plans=tuple(_plan_view(row) for row in rows),
        )


def sanitize_seeds(seeds: ChannelPlanSeeds | None) -> ChannelPlanSeeds:
    if seeds is None:
        return ChannelPlanSeeds()
    keywords: list[str] = []
    for raw in seeds.keywords[:MAX_SEED_KEYWORDS]:
        cleaned = _safe_token(raw)
        if cleaned and cleaned not in keywords:
            keywords.append(cleaned)
    return ChannelPlanSeeds(
        specialty=_safe_token(seeds.specialty),
        geography=_safe_geography(seeds.geography),
        keywords=tuple(keywords),
        partner_type=_safe_token(seeds.partner_type),
    )


def _safe_token(value: str | None) -> str | None:
    if value is None:
        return None
    sanitized = sanitize_operator_text(value)
    if sanitized is None or sanitized == "[REDACTED_UNSAFE_TEXT]":
        return None
    cleaned = SAFE_TOKEN_RE.sub(" ", sanitized).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    if not cleaned or not re.search(r"[A-Za-z]", cleaned):
        return None
    if "REDACTED" in cleaned.upper():
        return None
    return cleaned[:MAX_TOKEN_LENGTH]


def _safe_geography(value: str | None) -> str | None:
    token = _safe_token(value)
    if token is None:
        return None
    compact = token.replace(" ", "")
    if len(compact) == 2 and compact.isalpha():
        return compact.upper()
    return token


def _plan_view(row: ChannelPlan) -> ChannelPlanView:
    metrics = row.source_metrics_json if isinstance(row.source_metrics_json, dict) else {}
    seeds = row.seed_input_refs_json if isinstance(row.seed_input_refs_json, dict) else {}
    return ChannelPlanView(
        id=row.id,
        plan_key=row.plan_key,
        channel=row.channel,
        plan_type=row.plan_type,
        title=row.title,
        summary=row.summary,
        target_specialty=row.target_specialty,
        target_geography=row.target_geography,
        target_icp=row.target_icp,
        priority=row.priority,
        confidence=row.confidence,
        source_metrics=dict(metrics),
        seed_input_refs=dict(seeds),
        generated_at=row.generated_at,
        approval_status=row.approval_status,
        dry_run_only=row.dry_run_only,
        no_spend=row.no_spend,
        launched=row.launched,
        spend_attempted=row.spend_attempted,
        campaign_launched=row.campaign_launched,
        pages_published=row.pages_published,
        outbound_attempted=row.outbound_attempted,
    )


def _build_plans(
    snapshot: ChannelPlanningSnapshot,
    seeds: ChannelPlanSeeds,
) -> tuple[ChannelPlanDraft, ...]:
    drafts: list[ChannelPlanDraft] = []
    drafts.extend(_ads_plans(snapshot, seeds))
    drafts.extend(_seo_plans(snapshot, seeds))
    drafts.extend(_referral_plans(snapshot, seeds))
    drafts.extend(_positioning_plans(snapshot, seeds))
    return tuple(drafts)


def _usable_cohorts(snapshot: ChannelPlanningSnapshot) -> list[SpecialtyCohort]:
    usable = [
        row
        for row in snapshot.specialty_geography
        if row.specialty != "unset" or row.state != "unset"
    ]
    ranked = sorted(usable, key=lambda row: (row.leads, row.organizations), reverse=True)
    return ranked[:MAX_COHORTS]


def _ads_plans(
    snapshot: ChannelPlanningSnapshot, seeds: ChannelPlanSeeds
) -> list[ChannelPlanDraft]:
    drafts: list[ChannelPlanDraft] = []
    for cohort in _usable_cohorts(snapshot):
        specialty = None if cohort.specialty == "unset" else cohort.specialty
        geography = None if cohort.state == "unset" else cohort.state
        concepts = _keyword_concepts(specialty, geography, None)
        if not concepts:
            continue
        drafts.append(
            _draft(
                key=f"google_search_ads:{_slug(specialty)}:{_slug(geography)}",
                channel=AcquisitionChannel.GOOGLE_SEARCH_ADS,
                plan_type=ChannelPlanType.KEYWORD_GROUP,
                title=_title("Search ads concept", specialty, geography),
                summary=(
                    "Keyword-group concept from stored specialty/geography aggregates. "
                    "No ad account is called and no spend is attempted."
                ),
                specialty=specialty,
                geography=geography,
                icp=_icp_label(cohort),
                priority=RecommendationPriority.MEDIUM,
                confidence=_confidence(cohort.organizations + cohort.leads, base=0.6),
                metrics={
                    **cohort.as_metrics(),
                    "keyword_group_concepts": concepts,
                    "source": "stored_specialty_geography",
                },
                seeds={},
            )
        )
    for keyword in seeds.keywords:
        specialty = seeds.specialty
        geography = seeds.geography
        drafts.append(
            _draft(
                key=f"google_search_ads:seed:{_slug(keyword)}",
                channel=AcquisitionChannel.GOOGLE_SEARCH_ADS,
                plan_type=ChannelPlanType.KEYWORD_GROUP,
                title="Search ads concept from operator seed keyword",
                summary=(
                    "Keyword-group concept from an explicit operator seed. "
                    "No ad account is called and no spend is attempted."
                ),
                specialty=specialty,
                geography=geography,
                icp=None,
                priority=RecommendationPriority.LOW,
                confidence=0.55,
                metrics={
                    "keyword_group_concepts": _keyword_concepts(specialty, geography, keyword),
                    "source": "operator_seed",
                },
                seeds={"seed_keyword": keyword, **seeds.as_refs()},
            )
        )
    return drafts


def _seo_plans(
    snapshot: ChannelPlanningSnapshot, seeds: ChannelPlanSeeds
) -> list[ChannelPlanDraft]:
    drafts: list[ChannelPlanDraft] = []
    for cohort in _usable_cohorts(snapshot):
        specialty = None if cohort.specialty == "unset" else cohort.specialty
        geography = None if cohort.state == "unset" else cohort.state
        topic = _topic_label(specialty, geography)
        if topic is None:
            continue
        drafts.append(
            _draft(
                key=f"seo_content:{_slug(specialty)}:{_slug(geography)}",
                channel=AcquisitionChannel.SEO_CONTENT,
                plan_type=ChannelPlanType.LANDING_PAGE_TOPIC,
                title=_title("SEO landing-page topic", specialty, geography),
                summary=(
                    "Content/landing-page topic idea from stored specialty/geography aggregates. "
                    "No page is published."
                ),
                specialty=specialty,
                geography=geography,
                icp=_icp_label(cohort),
                priority=RecommendationPriority.MEDIUM,
                confidence=_confidence(cohort.organizations + cohort.leads, base=0.58),
                metrics={
                    **cohort.as_metrics(),
                    "topic_concept": topic,
                    "source": "stored_specialty_geography",
                },
                seeds={},
            )
        )
    for keyword in seeds.keywords:
        drafts.append(
            _draft(
                key=f"seo_content:seed:{_slug(keyword)}",
                channel=AcquisitionChannel.SEO_CONTENT,
                plan_type=ChannelPlanType.LANDING_PAGE_TOPIC,
                title="SEO topic from operator seed keyword",
                summary=(
                    "Content/landing-page topic idea from an explicit operator seed. "
                    "No page is published."
                ),
                specialty=seeds.specialty,
                geography=seeds.geography,
                icp=None,
                priority=RecommendationPriority.LOW,
                confidence=0.52,
                metrics={
                    "topic_concept": keyword,
                    "source": "operator_seed",
                },
                seeds={"seed_keyword": keyword, **seeds.as_refs()},
            )
        )
    return drafts


def _referral_plans(
    snapshot: ChannelPlanningSnapshot, seeds: ChannelPlanSeeds
) -> list[ChannelPlanDraft]:
    drafts: list[ChannelPlanDraft] = []
    if snapshot.referral_intent_count > 0:
        drafts.append(
            _draft(
                key="referral_partner:stored_referral_intents",
                channel=AcquisitionChannel.REFERRAL_PARTNER,
                plan_type=ChannelPlanType.PARTNER_CAMPAIGN,
                title="Referral/partner idea from stored referral-intent replies",
                summary=(
                    "Partner-campaign idea referenced to stored referral-intent counts. "
                    "No partner is contacted and no campaign is launched."
                ),
                specialty=seeds.specialty,
                geography=seeds.geography,
                icp=None,
                priority=RecommendationPriority.LOW,
                confidence=_confidence(snapshot.referral_intent_count, base=0.57),
                metrics={
                    "referral_intent_count": snapshot.referral_intent_count,
                    "source": "stored_reply_intents",
                },
                seeds=seeds.as_refs() if seeds.has_any() else {},
            )
        )
    if seeds.partner_type:
        drafts.append(
            _draft(
                key=f"referral_partner:seed:{_slug(seeds.partner_type)}",
                channel=AcquisitionChannel.REFERRAL_PARTNER,
                plan_type=ChannelPlanType.PARTNER_CAMPAIGN,
                title="Referral/partner idea from operator seed",
                summary=(
                    "Partner-campaign idea from an explicit operator seed type. "
                    "No partner name is invented and no outreach is sent."
                ),
                specialty=seeds.specialty,
                geography=seeds.geography,
                icp=None,
                priority=RecommendationPriority.LOW,
                confidence=0.5,
                metrics={
                    "partner_type_concept": seeds.partner_type,
                    "source": "operator_seed",
                },
                seeds=seeds.as_refs(),
            )
        )
    elif seeds.specialty or seeds.geography:
        drafts.append(
            _draft(
                key=f"referral_partner:seed:{_slug(seeds.specialty)}:{_slug(seeds.geography)}",
                channel=AcquisitionChannel.REFERRAL_PARTNER,
                plan_type=ChannelPlanType.PARTNER_CAMPAIGN,
                title=_title("Referral/partner idea", seeds.specialty, seeds.geography),
                summary=(
                    "Generic partner-campaign idea scoped to operator seed specialty/geography. "
                    "No partner organization is invented or contacted."
                ),
                specialty=seeds.specialty,
                geography=seeds.geography,
                icp=None,
                priority=RecommendationPriority.LOW,
                confidence=0.48,
                metrics={"source": "operator_seed"},
                seeds=seeds.as_refs(),
            )
        )
    return drafts


def _positioning_plans(
    snapshot: ChannelPlanningSnapshot, seeds: ChannelPlanSeeds
) -> list[ChannelPlanDraft]:
    drafts: list[ChannelPlanDraft] = []
    cohorts = [row for row in _usable_cohorts(snapshot) if row.leads > 0]
    if len(cohorts) >= 2:
        ranked = sorted(cohorts, key=lambda row: (row.conversion_rate, row.leads))
        weakest = ranked[0]
        strongest = ranked[-1]
        if strongest.conversion_rate > weakest.conversion_rate:
            drafts.append(
                _positioning_draft(
                    key="specialty_geography:stronger",
                    cohort=strongest,
                    title="Positioning idea from stronger stored specialty/geography mix",
                    summary=(
                        "Review-only positioning idea from stored lead-stage aggregates. "
                        "No campaign, page, or spend change is applied."
                    ),
                )
            )
            drafts.append(
                _positioning_draft(
                    key="specialty_geography:weaker",
                    cohort=weakest,
                    title="Positioning idea from weaker stored specialty/geography mix",
                    summary=(
                        "Review-only positioning idea from stored lead-stage aggregates. "
                        "No campaign, page, or spend change is applied."
                    ),
                )
            )
        else:
            drafts.append(_positioning_draft_from_cohort(cohorts[0]))
    elif len(cohorts) == 1:
        drafts.append(_positioning_draft_from_cohort(cohorts[0]))
    elif seeds.specialty or seeds.geography:
        drafts.append(
            _draft(
                key=f"specialty_geography:seed:{_slug(seeds.specialty)}:{_slug(seeds.geography)}",
                channel=AcquisitionChannel.SPECIALTY_GEOGRAPHY,
                plan_type=ChannelPlanType.POSITIONING,
                title=_title("Positioning idea", seeds.specialty, seeds.geography),
                summary=(
                    "Positioning idea from explicit operator seed inputs only. "
                    "Missing stored aggregates stay missing."
                ),
                specialty=seeds.specialty,
                geography=seeds.geography,
                icp=None,
                priority=RecommendationPriority.LOW,
                confidence=0.45,
                metrics={"source": "operator_seed", "stored_cohorts": 0},
                seeds=seeds.as_refs(),
            )
        )
    return drafts


def _positioning_draft_from_cohort(cohort: SpecialtyCohort) -> ChannelPlanDraft:
    specialty = None if cohort.specialty == "unset" else cohort.specialty
    geography = None if cohort.state == "unset" else cohort.state
    return _positioning_draft(
        key=f"specialty_geography:{_slug(specialty)}:{_slug(geography)}",
        cohort=cohort,
        title=_title("Positioning idea", specialty, geography),
        summary=(
            "Review-only positioning idea from stored specialty/geography lead counts. "
            "No campaign, page, or spend change is applied."
        ),
    )


def _positioning_draft(
    *,
    key: str,
    cohort: SpecialtyCohort,
    title: str,
    summary: str,
) -> ChannelPlanDraft:
    specialty = None if cohort.specialty == "unset" else cohort.specialty
    geography = None if cohort.state == "unset" else cohort.state
    return _draft(
        key=key,
        channel=AcquisitionChannel.SPECIALTY_GEOGRAPHY,
        plan_type=ChannelPlanType.POSITIONING,
        title=title,
        summary=summary,
        specialty=specialty,
        geography=geography,
        icp=_icp_label(cohort),
        priority=RecommendationPriority.LOW,
        confidence=_confidence(cohort.leads, base=0.55),
        metrics={**cohort.as_metrics(), "source": "stored_specialty_geography"},
        seeds={},
    )


def _draft(
    *,
    key: str,
    channel: AcquisitionChannel,
    plan_type: ChannelPlanType,
    title: str,
    summary: str,
    specialty: str | None,
    geography: str | None,
    icp: str | None,
    priority: RecommendationPriority,
    confidence: float,
    metrics: dict[str, object],
    seeds: dict[str, object],
) -> ChannelPlanDraft:
    return ChannelPlanDraft(
        plan_key=key[:255],
        channel=channel,
        plan_type=plan_type,
        title=title[:255],
        summary=summary,
        target_specialty=specialty,
        target_geography=geography,
        target_icp=icp,
        priority=priority,
        confidence=round(min(max(confidence, 0.0), 1.0), 4),
        source_metrics=metrics,
        seed_input_refs=seeds,
    )


def _title(prefix: str, specialty: str | None, geography: str | None) -> str:
    if specialty and geography:
        return f"{prefix} for {specialty} in {geography}"
    if specialty:
        return f"{prefix} for {specialty}"
    if geography:
        return f"{prefix} for {geography}"
    return prefix


def _topic_label(specialty: str | None, geography: str | None) -> str | None:
    if specialty and geography:
        return f"{specialty} medical billing in {geography}"
    if specialty:
        return f"{specialty} medical billing"
    if geography:
        return f"medical billing in {geography}"
    return None


def _keyword_concepts(
    specialty: str | None, geography: str | None, seed: str | None
) -> list[str]:
    concepts: list[str] = []
    if seed:
        concepts.append(seed)
        concepts.append(f"{seed} medical billing")
    if specialty and geography:
        concepts.append(f"{specialty} medical billing {geography}")
        concepts.append(f"{specialty} revenue cycle {geography}")
    elif specialty:
        concepts.append(f"{specialty} medical billing")
        concepts.append(f"{specialty} revenue cycle")
    elif geography:
        concepts.append(f"medical billing {geography}")
    seen: list[str] = []
    for item in concepts:
        if item not in seen:
            seen.append(item)
    return seen


def _icp_label(cohort: SpecialtyCohort) -> str | None:
    if not cohort.score_bands:
        return None
    parts = [f"{band}={count}" for band, count in sorted(cohort.score_bands.items()) if count]
    if not parts:
        return None
    return "stored_score_bands:" + ",".join(parts)


def _confidence(sample: int, *, base: float) -> float:
    if sample <= 0:
        return base
    return round(min(base + min(sample, 20) * 0.01, 0.95), 4)


def _slug(value: str | None) -> str:
    if not value:
        return "unset"
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "unset"


def _collect_snapshot(db: Session) -> ChannelPlanningSnapshot:
    return ChannelPlanningSnapshot(
        organization_count=_count_rows(db, Organization),
        lead_count=_count_rows(db, Lead),
        referral_intent_count=_count_rows(
            db, ReplyClassification, ReplyClassification.intent == ReplyIntent.REFERRAL.value
        ),
        specialty_geography=_specialty_geography(db),
    )


def _specialty_geography(db: Session) -> tuple[SpecialtyCohort, ...]:
    org_rows = db.execute(
        select(Organization.specialty, Organization.state, func.count()).group_by(
            Organization.specialty, Organization.state
        )
    ).all()
    org_counts: dict[tuple[str, str], int] = {}
    for specialty, state, count in org_rows:
        org_counts[_cohort_key(specialty, state)] = int(count)

    lead_rows = db.execute(
        select(
            Organization.specialty,
            Organization.state,
            Lead.stage,
            func.count(),
        )
        .join(Lead, Lead.organization_id == Organization.id)
        .group_by(Organization.specialty, Organization.state, Lead.stage)
    ).all()
    lead_counts: dict[tuple[str, str], dict[str, int]] = {}
    for specialty, state, stage, count in lead_rows:
        key = _cohort_key(specialty, state)
        bucket = lead_counts.setdefault(key, {"leads": 0, "conversion_leads": 0})
        bucket["leads"] += int(count)
        if stage in CONVERSION_STAGES:
            bucket["conversion_leads"] += int(count)

    score_rows = db.execute(
        select(Organization.specialty, Organization.state, LeadScore.rationale, func.count())
        .join(Lead, Lead.organization_id == Organization.id)
        .join(LeadScore, LeadScore.lead_id == Lead.id)
        .group_by(Organization.specialty, Organization.state, LeadScore.rationale)
    ).all()
    score_bands: dict[tuple[str, str], dict[str, int]] = {}
    for specialty, state, rationale, count in score_rows:
        key = _cohort_key(specialty, state)
        band = _band_from_rationale(rationale)
        if band is None:
            continue
        bands = score_bands.setdefault(key, {})
        bands[band] = bands.get(band, 0) + int(count)

    keys = sorted(set(org_counts) | set(lead_counts))
    results: list[SpecialtyCohort] = []
    for specialty, state in keys:
        leads = lead_counts.get((specialty, state), {})
        lead_total = leads.get("leads", 0)
        conversion_leads = leads.get("conversion_leads", 0)
        results.append(
            SpecialtyCohort(
                specialty=specialty,
                state=state,
                organizations=org_counts.get((specialty, state), 0),
                leads=lead_total,
                conversion_leads=conversion_leads,
                conversion_rate=round(conversion_leads / lead_total, 4) if lead_total else 0.0,
                score_bands=score_bands.get((specialty, state), {}),
            )
        )
    return tuple(results)


def _cohort_key(specialty: object, state: object) -> tuple[str, str]:
    specialty_label = "unset" if not specialty else _safe_token(str(specialty)) or "unset"
    if not state:
        state_label = "unset"
    else:
        state_label = _safe_geography(str(state)) or "unset"
    return specialty_label, state_label


def _band_from_rationale(rationale: object) -> str | None:
    if not isinstance(rationale, dict):
        return None
    raw = rationale.get("band")
    if isinstance(raw, str) and raw:
        return raw
    return None


def _sanitized_snapshot(
    snapshot: ChannelPlanningSnapshot, seeds: ChannelPlanSeeds
) -> dict[str, object]:
    payload: dict[str, object] = {
        "model_version": CHANNEL_PLANNING_MODEL_VERSION,
        "organization_count": snapshot.organization_count,
        "lead_count": snapshot.lead_count,
        "referral_intent_count": snapshot.referral_intent_count,
        "specialty_geography": [cohort.as_metrics() for cohort in snapshot.specialty_geography],
        "seeds": seeds.as_refs(),
    }
    sanitized = _json_safe(payload)
    if not isinstance(sanitized, dict):
        raise TypeError("channel planning snapshot must be an object")
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


def _count_rows(db: Session, model: type[Any], *clauses: Any) -> int:
    stmt = select(func.count()).select_from(model)
    if clauses:
        stmt = stmt.where(*clauses)
    return int(db.scalar(stmt) or 0)
