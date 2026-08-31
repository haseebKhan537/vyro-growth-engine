"""Review-only landing page and SEO content briefs.

Phase 16 turns stored aggregate ICP signals, pending acquisition channel
plans, and explicit safe operator seeds into structured briefs. It never
publishes pages, launches ads, spends money, contacts prospects, or calls
SEO/search/AI providers.
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

from vyro_growth.config import Settings
from vyro_growth.domain import (
    AcquisitionChannelPlanStatus,
    AcquisitionChannelType,
    ContentBriefApprovalStatus,
    ContentBriefPriority,
    ContentBriefRunStatus,
    ContentBriefType,
)
from vyro_growth.models import (
    AcquisitionChannelPlan,
    Activity,
    ContentBrief,
    ContentBriefRun,
    Lead,
    Organization,
)
from vyro_growth.services.operator_halt import HaltStatus, read_operator_halt

logger = structlog.get_logger(__name__)

CONTENT_BRIEF_ACTOR = "content_brief"
CONTENT_BRIEF_MODEL_VERSION = "content-brief-v1"
MAX_TEXT_LENGTH = 240
MAX_TITLE_LENGTH = 160
MAX_LABEL_LENGTH = 80
MIN_SIGNAL_SAMPLE = 1

EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.I)
PHONE_RE = re.compile(r"(?:\+?1[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?)?\d{3}[-.\s]?\d{4}")
SECRET_RE = re.compile(
    r"\b(?:sk-|rk-|pk_|xox[abp]-|api[_-]?key)[A-Za-z0-9_\-]{8,}",
    re.I,
)
LABEL_RE = re.compile(r"[^A-Za-z0-9 /&+-]+")
SLUG_RE = re.compile(r"[^a-z0-9]+")
PHI_PHRASES = (
    "patient name",
    "patient diagnosis",
    "patient portal",
    "medical record",
    "date of birth",
    "social security",
    "protected health",
    "prescription",
    "diagnosed with",
    "my patient",
    "our patient",
    "the patient",
    "insurance member",
    "member id",
    "hipaa",
    "diabetes",
)
UNSAFE_FIELD_TOKENS = (
    "practice_summary",
    "opening_line",
    "why_vyro_relevant",
    "outreach_angle",
    "evidence_snippet",
    "message_body",
    "permitted_phone",
    "sender_email",
)
UNVERIFIABLE_CLAIM_RE = re.compile(
    r"(?i)\b("
    r"save(?:s|d|ings)?|"
    r"(?:\d+\s*%)|"
    r"revenue\s+(?:improv(?:e|ement)|increase|growth)|"
    r"increase\s+revenue|"
    r"collect\s+more|"
    r"(?:\d+\+?\s+)?clients?|"
    r"case\s+stud(?:y|ies)|"
    r"testimonial|"
    r"years?\s+of\s+experience|"
    r"founded\s+in|"
    r"certif(?:ied|ication)s?|"
    r"hipaa\s+certified|"
    r"provider\s+counts?|"
    r"(?:#\s*)?1\s+(?:billing|medical)|"
    r"leading\s+(?:billing|rcm)|"
    r"best\s+(?:billing|rcm)"
    r")\b"
)
DEFAULT_COMPLIANCE_NOTES = (
    "Review-only brief. Do not publish this page or article.",
    "Do not launch ads, spend money, or contact prospects from this brief.",
    (
        "Do not claim client counts, savings, compliance certifications, "
        "years of experience, case studies, testimonials, provider counts, "
        "or revenue improvement."
    ),
    "Do not write patient-facing medical advice.",
    "Missing prospect facts stay missing. Do not invent practice details.",
)
CHANNEL_BRIEF_TYPES: dict[AcquisitionChannelType, ContentBriefType] = {
    AcquisitionChannelType.GOOGLE_ADS: ContentBriefType.GOOGLE_ADS_LANDING_PAGE,
    AcquisitionChannelType.SEO: ContentBriefType.SEO_ARTICLE,
    AcquisitionChannelType.REFERRAL_PARTNER: ContentBriefType.REFERRAL_PARTNER_PAGE,
    AcquisitionChannelType.INBOUND_FORM: ContentBriefType.SPECIALTY_LANDING_PAGE,
    AcquisitionChannelType.RETARGETING: ContentBriefType.GOOGLE_ADS_LANDING_PAGE,
}


class ContentBriefError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class ContentBriefSeed:
    brief_type: ContentBriefType | None = None
    specialty: str | None = None
    geography: str | None = None
    icp_label: str | None = None
    topic: str | None = None
    channel_plan_id: UUID | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "brief_type": self.brief_type.value if self.brief_type is not None else None,
            "specialty": self.specialty,
            "geography": self.geography,
            "icp_label": self.icp_label,
            "topic": self.topic,
            "channel_plan_id": str(self.channel_plan_id) if self.channel_plan_id else None,
        }


@dataclass(frozen=True)
class ContentBriefView:
    id: UUID
    brief_key: str
    brief_type: str
    source_channel_plan_id: UUID | None
    specialty: str | None
    geography: str | None
    icp_label: str | None
    priority: str
    confidence: float
    title: str
    summary: str
    outline_sections: tuple[str, ...]
    recommended_cta: str
    compliance_notes: tuple[str, ...]
    source_references: dict[str, object]
    generated_at: datetime
    approval_status: str
    published: bool
    publish_attempted: bool
    dry_run_only: bool


@dataclass(frozen=True)
class ContentBriefRunResult:
    content_brief_run_id: UUID
    status: ContentBriefRunStatus
    model_version: str
    snapshot_fingerprint: str
    brief_count: int
    reused_existing: bool
    published_count: int
    dry_run_only: bool
    published: bool
    publish_attempted: bool
    outbound_attempted: bool
    live_call_attempted: bool
    ads_launched: bool
    spend_attempted: bool
    generated_at: datetime
    operator_halt_before: str
    operator_halt_after: str
    briefs: tuple[ContentBriefView, ...]


@dataclass(frozen=True)
class ChannelPlanView:
    id: UUID
    plan_key: str
    channel_type: str
    specialty: str | None
    geography: str | None
    icp_label: str | None
    title: str
    summary: str
    status: str
    dry_run_only: bool
    launched: bool
    spend_attempted: bool
    ads_live: bool
    reused_existing: bool


@dataclass(frozen=True)
class _SanitizedSeed:
    brief_type: ContentBriefType | None
    specialty: str | None
    geography: str | None
    icp_label: str | None
    topic: str | None
    channel_plan_id: UUID | None
    skipped: bool
    claim_omitted: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "brief_type": self.brief_type.value if self.brief_type is not None else None,
            "specialty": self.specialty,
            "geography": self.geography,
            "icp_label": self.icp_label,
            "topic": self.topic,
            "channel_plan_id": str(self.channel_plan_id) if self.channel_plan_id else None,
            "skipped": self.skipped,
            "claim_omitted": self.claim_omitted,
        }


@dataclass(frozen=True)
class _SpecialtySignal:
    specialty: str
    leads: int
    states: tuple[str, ...]

    def as_metrics(self) -> dict[str, object]:
        return {"specialty": self.specialty, "leads": self.leads, "states": list(self.states)}


@dataclass(frozen=True)
class _GeographySignal:
    geography: str
    leads: int
    specialties: tuple[str, ...]

    def as_metrics(self) -> dict[str, object]:
        return {
            "geography": self.geography,
            "leads": self.leads,
            "specialties": list(self.specialties),
        }


@dataclass(frozen=True)
class _BriefDraft:
    brief_key: str
    brief_type: ContentBriefType
    source_channel_plan_id: UUID | None
    specialty: str | None
    geography: str | None
    icp_label: str | None
    priority: ContentBriefPriority
    confidence: float
    title: str
    summary: str
    outline_sections: tuple[str, ...]
    recommended_cta: str
    compliance_notes: tuple[str, ...]
    source_references: dict[str, object]


class ContentBriefService:
    """Produce operator-review content briefs from stored signals and seeds."""

    def generate(
        self,
        db: Session,
        settings: Settings,
        *,
        seeds: tuple[ContentBriefSeed, ...] = (),
        commit: bool = True,
    ) -> ContentBriefRunResult:
        del settings
        halt_before = read_operator_halt(db)
        generated_at = datetime.now(tz=UTC)
        sanitized_seeds = tuple(_sanitize_seed(seed) for seed in seeds)
        plans = _pending_channel_plans(db)
        specialties = _specialty_signals(db)
        geographies = _geography_signals(db)
        snapshot = _sanitized_snapshot(plans, specialties, geographies, sanitized_seeds)
        fingerprint = _fingerprint(snapshot)
        existing = db.scalar(
            select(ContentBriefRun).where(ContentBriefRun.snapshot_fingerprint == fingerprint)
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
                "content_brief_run_reused",
                content_brief_run_id=str(existing.id),
                brief_count=existing.brief_count,
                snapshot_fingerprint=fingerprint,
                published=False,
                outbound_attempted=False,
            )
            return result

        drafts = _build_briefs(plans, specialties, geographies, sanitized_seeds)
        run = ContentBriefRun(
            status=ContentBriefRunStatus.COMPLETED.value,
            model_version=CONTENT_BRIEF_MODEL_VERSION,
            snapshot_fingerprint=fingerprint,
            brief_count=len(drafts),
            reused_count=0,
            published_count=0,
            dry_run_only=True,
            published=False,
            publish_attempted=False,
            outbound_attempted=False,
            live_call_attempted=False,
            ads_launched=False,
            spend_attempted=False,
            input_params={"dry_run_only": True, "auto_publish": False},
            snapshot_json=snapshot,
            started_at=generated_at,
            finished_at=generated_at,
        )
        db.add(run)
        db.flush()
        for draft in drafts:
            db.add(
                ContentBrief(
                    content_brief_run_id=run.id,
                    brief_key=draft.brief_key,
                    brief_type=draft.brief_type.value,
                    source_channel_plan_id=draft.source_channel_plan_id,
                    specialty=draft.specialty,
                    geography=draft.geography,
                    icp_label=draft.icp_label,
                    priority=draft.priority.value,
                    confidence=draft.confidence,
                    title=draft.title,
                    summary=draft.summary,
                    outline_sections=list(draft.outline_sections),
                    recommended_cta=draft.recommended_cta,
                    compliance_notes=list(draft.compliance_notes),
                    source_references=draft.source_references,
                    generated_at=generated_at,
                    approval_status=ContentBriefApprovalStatus.PENDING_OPERATOR_REVIEW.value,
                    published=False,
                    publish_attempted=False,
                    dry_run_only=True,
                )
            )
        db.add(
            Activity(
                lead_id=None,
                actor=CONTENT_BRIEF_ACTOR,
                action="content_briefs_generated",
                details={
                    "content_brief_run_id": str(run.id),
                    "brief_count": len(drafts),
                    "brief_types": [draft.brief_type.value for draft in drafts],
                    "published_count": 0,
                    "dry_run_only": True,
                    "published": False,
                    "publish_attempted": False,
                    "outbound_attempted": False,
                    "ads_launched": False,
                    "spend_attempted": False,
                },
            )
        )
        db.flush()
        halt_after = read_operator_halt(db)
        if halt_after is not halt_before:
            raise RuntimeError("content brief service must not change operator halt status")
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
            "content_brief_run_completed",
            content_brief_run_id=str(run.id),
            brief_count=len(drafts),
            snapshot_fingerprint=fingerprint,
            published=False,
            outbound_attempted=False,
        )
        return result

    def latest(self, db: Session) -> ContentBriefRunResult | None:
        run = db.scalars(select(ContentBriefRun).order_by(ContentBriefRun.created_at.desc())).first()
        if run is None:
            return None
        halt = read_operator_halt(db)
        return self._view(db, run, halt_before=halt, halt_after=halt, reused=True)

    def seed_channel_plan(
        self,
        db: Session,
        *,
        channel_type: str,
        specialty: str | None = None,
        geography: str | None = None,
        icp_label: str | None = None,
        title: str | None = None,
        commit: bool = True,
    ) -> ChannelPlanView:
        halt_before = read_operator_halt(db)
        parsed_type = _parse_channel_type(channel_type)
        safe_specialty = sanitize_label(specialty)
        safe_geography = sanitize_geography(geography)
        safe_icp = sanitize_label(icp_label)
        if _is_unsafe_text(specialty) or _is_unsafe_text(geography) or _is_unsafe_text(icp_label):
            raise ContentBriefError(
                "unsafe_channel_plan_seed",
                "Channel plan seed contained unsafe or patient-facing text",
            )
        plan_key = _channel_plan_key(parsed_type, safe_specialty, safe_geography, safe_icp)
        existing = db.scalar(
            select(AcquisitionChannelPlan).where(AcquisitionChannelPlan.plan_key == plan_key)
        )
        if existing is not None:
            return _channel_plan_view(existing, reused=True)
        safe_title = sanitize_content_text(title) or _channel_plan_title(
            parsed_type, safe_specialty, safe_geography
        )
        summary = (
            "Review-only acquisition channel plan. No ads are launched, no spend is "
            "attempted, and no pages are published."
        )
        row = AcquisitionChannelPlan(
            plan_key=plan_key,
            channel_type=parsed_type.value,
            specialty=safe_specialty,
            geography=safe_geography,
            icp_label=safe_icp,
            title=safe_title,
            summary=summary,
            source_metrics_json={"seeded_by": "operator", "dry_run_only": True},
            status=AcquisitionChannelPlanStatus.PENDING_OPERATOR_REVIEW.value,
            dry_run_only=True,
            launched=False,
            spend_attempted=False,
            ads_live=False,
        )
        db.add(row)
        db.add(
            Activity(
                lead_id=None,
                actor=CONTENT_BRIEF_ACTOR,
                action="acquisition_channel_plan_seeded",
                details={
                    "channel_type": parsed_type.value,
                    "specialty": safe_specialty,
                    "geography": safe_geography,
                    "launched": False,
                    "spend_attempted": False,
                    "ads_live": False,
                    "dry_run_only": True,
                },
            )
        )
        db.flush()
        halt_after = read_operator_halt(db)
        if halt_after is not halt_before:
            raise RuntimeError("channel plan seeding must not change operator halt status")
        if commit:
            db.commit()
            db.refresh(row)
        return _channel_plan_view(row, reused=False)

    def _view(
        self,
        db: Session,
        run: ContentBriefRun,
        *,
        halt_before: HaltStatus,
        halt_after: HaltStatus,
        reused: bool,
    ) -> ContentBriefRunResult:
        rows = list(
            db.scalars(
                select(ContentBrief)
                .where(ContentBrief.content_brief_run_id == run.id)
                .order_by(ContentBrief.brief_type, ContentBrief.brief_key)
            )
        )
        return ContentBriefRunResult(
            content_brief_run_id=run.id,
            status=ContentBriefRunStatus(run.status),
            model_version=run.model_version,
            snapshot_fingerprint=run.snapshot_fingerprint,
            brief_count=run.brief_count,
            reused_existing=reused,
            published_count=run.published_count,
            dry_run_only=run.dry_run_only,
            published=run.published,
            publish_attempted=run.publish_attempted,
            outbound_attempted=run.outbound_attempted,
            live_call_attempted=run.live_call_attempted,
            ads_launched=run.ads_launched,
            spend_attempted=run.spend_attempted,
            generated_at=run.finished_at or run.created_at,
            operator_halt_before=halt_before.value,
            operator_halt_after=halt_after.value,
            briefs=tuple(_brief_view(row) for row in rows),
        )


def sanitize_content_text(value: str | None) -> str | None:
    if value is None:
        return None
    text = " ".join(value.split()).strip()
    if not text:
        return None
    if _is_unsafe_text(text):
        return "[REDACTED_UNSAFE_TEXT]"
    cleaned = EMAIL_RE.sub("[REDACTED_EMAIL]", text)
    cleaned = PHONE_RE.sub("[REDACTED_PHONE]", cleaned)
    cleaned = SECRET_RE.sub("[REDACTED_SECRET]", cleaned)
    cleaned = UNVERIFIABLE_CLAIM_RE.sub("[UNVERIFIED_CLAIM_OMITTED]", cleaned)
    if len(cleaned) > MAX_TEXT_LENGTH:
        cleaned = cleaned[:MAX_TEXT_LENGTH].rstrip()
    return cleaned


def sanitize_label(value: str | None) -> str | None:
    if value is None:
        return None
    if _is_unsafe_text(value) or UNVERIFIABLE_CLAIM_RE.search(value):
        return None
    text = " ".join(value.split()).strip()
    if not text:
        return None
    cleaned = LABEL_RE.sub("", text).strip()
    if not cleaned:
        return None
    return cleaned[:MAX_LABEL_LENGTH]


def sanitize_geography(value: str | None) -> str | None:
    label = sanitize_label(value)
    if label is None:
        return None
    if len(label) == 2 and label.isalpha():
        return label.upper()
    return label


def _is_unsafe_text(value: str | None) -> bool:
    if value is None:
        return False
    lowered = value.lower()
    if any(token in lowered for token in UNSAFE_FIELD_TOKENS):
        return True
    if any(phrase in lowered for phrase in PHI_PHRASES):
        return True
    return bool(re.search(r"\bpatients?\b", lowered))


def _sanitize_seed(seed: ContentBriefSeed) -> _SanitizedSeed:
    raw_topic = seed.topic or ""
    claim_omitted = bool(UNVERIFIABLE_CLAIM_RE.search(raw_topic))
    topic = sanitize_content_text(seed.topic)
    if topic == "[REDACTED_UNSAFE_TEXT]":
        return _SanitizedSeed(
            brief_type=seed.brief_type,
            specialty=None,
            geography=None,
            icp_label=None,
            topic=None,
            channel_plan_id=seed.channel_plan_id,
            skipped=True,
            claim_omitted=True,
        )
    specialty = sanitize_label(seed.specialty)
    geography = sanitize_geography(seed.geography)
    icp_label = sanitize_label(seed.icp_label)
    skipped = _is_unsafe_text(seed.specialty) or _is_unsafe_text(seed.geography)
    return _SanitizedSeed(
        brief_type=seed.brief_type,
        specialty=None if skipped else specialty,
        geography=None if skipped else geography,
        icp_label=None if skipped else icp_label,
        topic=None if skipped else topic,
        channel_plan_id=seed.channel_plan_id,
        skipped=skipped,
        claim_omitted=claim_omitted,
    )


def _pending_channel_plans(db: Session) -> tuple[AcquisitionChannelPlan, ...]:
    rows = db.scalars(
        select(AcquisitionChannelPlan)
        .where(
            AcquisitionChannelPlan.status
            == AcquisitionChannelPlanStatus.PENDING_OPERATOR_REVIEW.value,
            AcquisitionChannelPlan.launched.is_(False),
            AcquisitionChannelPlan.spend_attempted.is_(False),
            AcquisitionChannelPlan.ads_live.is_(False),
        )
        .order_by(AcquisitionChannelPlan.channel_type, AcquisitionChannelPlan.plan_key)
    ).all()
    return tuple(rows)


def _specialty_signals(db: Session) -> tuple[_SpecialtySignal, ...]:
    rows = db.execute(
        select(Organization.specialty, Organization.state, func.count())
        .join(Lead, Lead.organization_id == Organization.id)
        .where(Organization.specialty.is_not(None), Organization.specialty != "")
        .group_by(Organization.specialty, Organization.state)
    ).all()
    grouped: dict[str, dict[str, object]] = {}
    for specialty, state, count in rows:
        label = sanitize_label(str(specialty))
        if label is None:
            continue
        bucket = grouped.setdefault(label, {"leads": 0, "states": set()})
        bucket["leads"] = int(bucket["leads"]) + int(count)
        geo = sanitize_geography(str(state) if state else None)
        if geo:
            states = bucket["states"]
            if isinstance(states, set):
                states.add(geo)
    results: list[_SpecialtySignal] = []
    for specialty, counts in sorted(grouped.items()):
        leads = int(counts["leads"])
        if leads < MIN_SIGNAL_SAMPLE:
            continue
        states = counts["states"]
        state_tuple = tuple(sorted(states)) if isinstance(states, set) else ()
        results.append(_SpecialtySignal(specialty=specialty, leads=leads, states=state_tuple))
    return tuple(results)


def _geography_signals(db: Session) -> tuple[_GeographySignal, ...]:
    rows = db.execute(
        select(Organization.state, Organization.specialty, func.count())
        .join(Lead, Lead.organization_id == Organization.id)
        .where(Organization.state.is_not(None), Organization.state != "")
        .group_by(Organization.state, Organization.specialty)
    ).all()
    grouped: dict[str, dict[str, object]] = {}
    for state, specialty, count in rows:
        geography = sanitize_geography(str(state))
        if geography is None:
            continue
        bucket = grouped.setdefault(geography, {"leads": 0, "specialties": set()})
        bucket["leads"] = int(bucket["leads"]) + int(count)
        label = sanitize_label(str(specialty) if specialty else None)
        if label:
            specialties = bucket["specialties"]
            if isinstance(specialties, set):
                specialties.add(label)
    results: list[_GeographySignal] = []
    for geography, counts in sorted(grouped.items()):
        leads = int(counts["leads"])
        if leads < MIN_SIGNAL_SAMPLE:
            continue
        specialties = counts["specialties"]
        specialty_tuple = tuple(sorted(specialties)) if isinstance(specialties, set) else ()
        results.append(
            _GeographySignal(geography=geography, leads=leads, specialties=specialty_tuple)
        )
    return tuple(results)


def _build_briefs(
    plans: tuple[AcquisitionChannelPlan, ...],
    specialties: tuple[_SpecialtySignal, ...],
    geographies: tuple[_GeographySignal, ...],
    seeds: tuple[_SanitizedSeed, ...],
) -> tuple[_BriefDraft, ...]:
    drafts: dict[str, _BriefDraft] = {}
    for signal in specialties:
        draft = _specialty_brief(signal)
        drafts[draft.brief_key] = draft
    for signal in geographies:
        draft = _geography_brief(signal)
        drafts[draft.brief_key] = draft
    for plan in plans:
        draft = _channel_plan_brief(plan)
        drafts[draft.brief_key] = draft
        if plan.specialty and f"specialty_landing_page:{_slug(plan.specialty)}" not in drafts:
            drafts.update(_optional_specialty_from_plan(plan))
        if plan.geography and f"geography_landing_page:{_slug(plan.geography)}" not in drafts:
            drafts.update(_optional_geography_from_plan(plan))
    for seed in seeds:
        if seed.skipped:
            continue
        draft = _seed_brief(seed, plans)
        if draft is not None:
            drafts[draft.brief_key] = draft
    return tuple(sorted(drafts.values(), key=lambda item: (item.brief_type.value, item.brief_key)))


def _specialty_brief(signal: _SpecialtySignal) -> _BriefDraft:
    geography = signal.states[0] if len(signal.states) == 1 else None
    return _landing_brief(
        brief_type=ContentBriefType.SPECIALTY_LANDING_PAGE,
        brief_key=f"specialty_landing_page:{_slug(signal.specialty)}",
        specialty=signal.specialty,
        geography=geography,
        confidence=_confidence(signal.leads, base=0.6),
        priority=ContentBriefPriority.MEDIUM if signal.leads >= 3 else ContentBriefPriority.LOW,
        source_kind="stored_specialty_aggregate",
        source_references={"metrics": signal.as_metrics()},
    )


def _geography_brief(signal: _GeographySignal) -> _BriefDraft:
    specialty = signal.specialties[0] if len(signal.specialties) == 1 else None
    return _landing_brief(
        brief_type=ContentBriefType.GEOGRAPHY_LANDING_PAGE,
        brief_key=f"geography_landing_page:{_slug(signal.geography)}",
        specialty=specialty,
        geography=signal.geography,
        confidence=_confidence(signal.leads, base=0.58),
        priority=ContentBriefPriority.MEDIUM if signal.leads >= 3 else ContentBriefPriority.LOW,
        source_kind="stored_geography_aggregate",
        source_references={"metrics": signal.as_metrics()},
    )


def _channel_plan_brief(plan: AcquisitionChannelPlan) -> _BriefDraft:
    channel = AcquisitionChannelType(plan.channel_type)
    brief_type = CHANNEL_BRIEF_TYPES[channel]
    return _landing_brief(
        brief_type=brief_type,
        brief_key=f"{brief_type.value}:plan:{plan.id}",
        specialty=plan.specialty,
        geography=plan.geography,
        icp_label=plan.icp_label,
        confidence=0.7,
        priority=ContentBriefPriority.MEDIUM,
        source_kind="pending_channel_plan",
        source_channel_plan_id=plan.id,
        source_references={
            "channel_plan_id": str(plan.id),
            "channel_type": plan.channel_type,
            "plan_key": plan.plan_key,
        },
    )


def _optional_specialty_from_plan(plan: AcquisitionChannelPlan) -> dict[str, _BriefDraft]:
    specialty = plan.specialty
    if not specialty:
        return {}
    draft = _landing_brief(
        brief_type=ContentBriefType.SPECIALTY_LANDING_PAGE,
        brief_key=f"specialty_landing_page:{_slug(specialty)}",
        specialty=specialty,
        geography=plan.geography,
        icp_label=plan.icp_label,
        confidence=0.62,
        priority=ContentBriefPriority.LOW,
        source_kind="pending_channel_plan",
        source_channel_plan_id=plan.id,
        source_references={"channel_plan_id": str(plan.id), "channel_type": plan.channel_type},
    )
    return {draft.brief_key: draft}


def _optional_geography_from_plan(plan: AcquisitionChannelPlan) -> dict[str, _BriefDraft]:
    geography = plan.geography
    if not geography:
        return {}
    draft = _landing_brief(
        brief_type=ContentBriefType.GEOGRAPHY_LANDING_PAGE,
        brief_key=f"geography_landing_page:{_slug(geography)}",
        specialty=plan.specialty,
        geography=geography,
        icp_label=plan.icp_label,
        confidence=0.62,
        priority=ContentBriefPriority.LOW,
        source_kind="pending_channel_plan",
        source_channel_plan_id=plan.id,
        source_references={"channel_plan_id": str(plan.id), "channel_type": plan.channel_type},
    )
    return {draft.brief_key: draft}


def _seed_brief(
    seed: _SanitizedSeed,
    plans: tuple[AcquisitionChannelPlan, ...],
) -> _BriefDraft | None:
    brief_type = seed.brief_type or _infer_seed_type(seed)
    if brief_type is None:
        return None
    plan = _plan_for_seed(seed, plans)
    slug_source = seed.topic or seed.specialty or seed.geography or "operator-seed"
    return _landing_brief(
        brief_type=brief_type,
        brief_key=f"{brief_type.value}:seed:{_slug(slug_source)}",
        specialty=seed.specialty or (plan.specialty if plan is not None else None),
        geography=seed.geography or (plan.geography if plan is not None else None),
        icp_label=seed.icp_label or (plan.icp_label if plan is not None else None),
        confidence=0.55,
        priority=ContentBriefPriority.LOW,
        source_kind="operator_seed",
        source_channel_plan_id=plan.id if plan is not None else seed.channel_plan_id,
        source_references={
            "seed": seed.as_dict(),
            "channel_plan_id": str(plan.id) if plan is not None else None,
        },
        extra_notes=("Operator seed omitted an unverifiable claim." if seed.claim_omitted else None),
        topic=seed.topic,
    )


def _infer_seed_type(seed: _SanitizedSeed) -> ContentBriefType | None:
    if seed.topic:
        return ContentBriefType.SEO_ARTICLE
    if seed.specialty:
        return ContentBriefType.SPECIALTY_LANDING_PAGE
    if seed.geography:
        return ContentBriefType.GEOGRAPHY_LANDING_PAGE
    return None


def _plan_for_seed(
    seed: _SanitizedSeed,
    plans: tuple[AcquisitionChannelPlan, ...],
) -> AcquisitionChannelPlan | None:
    if seed.channel_plan_id is None:
        return None
    for plan in plans:
        if plan.id == seed.channel_plan_id:
            return plan
    return None


def _landing_brief(
    *,
    brief_type: ContentBriefType,
    brief_key: str,
    specialty: str | None,
    geography: str | None,
    icp_label: str | None = None,
    confidence: float,
    priority: ContentBriefPriority,
    source_kind: str,
    source_references: dict[str, object],
    source_channel_plan_id: UUID | None = None,
    extra_notes: str | None = None,
    topic: str | None = None,
) -> _BriefDraft:
    audience = _audience_label(specialty, geography, icp_label)
    title = _brief_title(brief_type, audience, topic)
    summary = _brief_summary(brief_type, audience, source_kind)
    notes = list(DEFAULT_COMPLIANCE_NOTES)
    if extra_notes:
        notes.append(extra_notes)
    return _BriefDraft(
        brief_key=brief_key,
        brief_type=brief_type,
        source_channel_plan_id=source_channel_plan_id,
        specialty=specialty,
        geography=geography,
        icp_label=icp_label,
        priority=priority,
        confidence=round(min(max(confidence, 0.0), 1.0), 4),
        title=title,
        summary=summary,
        outline_sections=_outline_sections(brief_type, audience, topic),
        recommended_cta=_cta(brief_type),
        compliance_notes=tuple(notes),
        source_references={**source_references, "source_kind": source_kind},
    )


def _audience_label(
    specialty: str | None,
    geography: str | None,
    icp_label: str | None,
) -> str:
    parts = [part for part in (specialty, geography, icp_label) if part]
    if not parts:
        return "US medical practice decision-makers"
    return " / ".join(parts)


def _brief_title(brief_type: ContentBriefType, audience: str, topic: str | None) -> str:
    if brief_type is ContentBriefType.SEO_ARTICLE:
        focus = topic or audience
        title = f"SEO article outline: {focus}"
    elif brief_type is ContentBriefType.GOOGLE_ADS_LANDING_PAGE:
        title = f"Google Ads landing page concept: {audience}"
    elif brief_type is ContentBriefType.REFERRAL_PARTNER_PAGE:
        title = f"Referral partner page concept: {audience}"
    elif brief_type is ContentBriefType.GEOGRAPHY_LANDING_PAGE:
        title = f"Geography landing page brief: {audience}"
    else:
        title = f"Specialty landing page brief: {audience}"
    return title[:MAX_TITLE_LENGTH]


def _brief_summary(brief_type: ContentBriefType, audience: str, source_kind: str) -> str:
    kind = brief_type.value.replace("_", " ")
    return (
        f"Review-only {kind} outline for {audience}. Source: {source_kind.replace('_', ' ')}. "
        "No page is published and no ads are launched."
    )


def _outline_sections(
    brief_type: ContentBriefType,
    audience: str,
    topic: str | None,
) -> tuple[str, ...]:
    topic_note = f" Topic seed: {topic}." if topic else ""
    shared = (
        f"Audience: {audience}. Patient-facing medical advice is out of scope.",
        (
            "Problem framing: ask about billing operations questions this audience "
            "may have. Do not claim savings or client results."
        ),
        (
            "What to explain: describe Vyro as a medical billing company using only "
            "operator-verified facts. Leave unknown facts unknown."
        ),
        (
            "Proof policy: omit case studies, testimonials, certifications, years of "
            "experience, provider counts, and revenue improvement claims."
        ),
        "Next step: keep this brief pending operator review. Do not publish.",
    )
    if brief_type is ContentBriefType.SEO_ARTICLE:
        return (
            shared[0],
            f"Working topic: keep the article educational and B2B-only.{topic_note}",
            shared[1],
            shared[2],
            shared[3],
            "Do not generate full article copy in this phase.",
            shared[4],
        )
    if brief_type is ContentBriefType.GOOGLE_ADS_LANDING_PAGE:
        return (
            shared[0],
            "Ads concept only: do not create a Google Ads campaign or set a budget.",
            shared[1],
            shared[2],
            shared[3],
            shared[4],
        )
    if brief_type is ContentBriefType.REFERRAL_PARTNER_PAGE:
        return (
            shared[0],
            "Partner framing: describe a possible referral conversation, not a live program.",
            shared[1],
            shared[2],
            shared[3],
            shared[4],
        )
    return shared


def _cta(brief_type: ContentBriefType) -> str:
    if brief_type is ContentBriefType.REFERRAL_PARTNER_PAGE:
        return "Invite a partner conversation about referring practices."
    if brief_type is ContentBriefType.SEO_ARTICLE:
        return "Invite an operator-approved inquiry after the article is reviewed."
    return "Invite a practice decision-maker to request a conversation about billing operations."


def _confidence(sample: int, *, base: float) -> float:
    if sample <= 0:
        return base
    return round(min(base + min(sample, 20) * 0.01, 0.85), 4)


def _brief_view(row: ContentBrief) -> ContentBriefView:
    sections = row.outline_sections if isinstance(row.outline_sections, list) else []
    notes = row.compliance_notes if isinstance(row.compliance_notes, list) else []
    references = row.source_references if isinstance(row.source_references, dict) else {}
    return ContentBriefView(
        id=row.id,
        brief_key=row.brief_key,
        brief_type=row.brief_type,
        source_channel_plan_id=row.source_channel_plan_id,
        specialty=row.specialty,
        geography=row.geography,
        icp_label=row.icp_label,
        priority=row.priority,
        confidence=row.confidence,
        title=row.title,
        summary=row.summary,
        outline_sections=tuple(str(item) for item in sections),
        recommended_cta=row.recommended_cta,
        compliance_notes=tuple(str(item) for item in notes),
        source_references=dict(references),
        generated_at=row.generated_at,
        approval_status=row.approval_status,
        published=row.published,
        publish_attempted=row.publish_attempted,
        dry_run_only=row.dry_run_only,
    )


def _channel_plan_view(row: AcquisitionChannelPlan, *, reused: bool) -> ChannelPlanView:
    return ChannelPlanView(
        id=row.id,
        plan_key=row.plan_key,
        channel_type=row.channel_type,
        specialty=row.specialty,
        geography=row.geography,
        icp_label=row.icp_label,
        title=row.title,
        summary=row.summary,
        status=row.status,
        dry_run_only=row.dry_run_only,
        launched=row.launched,
        spend_attempted=row.spend_attempted,
        ads_live=row.ads_live,
        reused_existing=reused,
    )


def _parse_channel_type(value: str) -> AcquisitionChannelType:
    try:
        return AcquisitionChannelType(value.strip())
    except ValueError as exc:
        raise ContentBriefError("unknown_channel_type", "Unknown acquisition channel type") from exc


def _channel_plan_key(
    channel_type: AcquisitionChannelType,
    specialty: str | None,
    geography: str | None,
    icp_label: str | None,
) -> str:
    return "|".join(
        (
            channel_type.value,
            _slug(specialty or "unset"),
            _slug(geography or "unset"),
            _slug(icp_label or "unset"),
        )
    )


def _channel_plan_title(
    channel_type: AcquisitionChannelType,
    specialty: str | None,
    geography: str | None,
) -> str:
    audience = _audience_label(specialty, geography, None)
    return f"Pending {channel_type.value.replace('_', ' ')} plan: {audience}"[:MAX_TITLE_LENGTH]


def _slug(value: str) -> str:
    slug = SLUG_RE.sub("-", value.lower()).strip("-")
    return slug[:80] or "unset"


def _sanitized_snapshot(
    plans: tuple[AcquisitionChannelPlan, ...],
    specialties: tuple[_SpecialtySignal, ...],
    geographies: tuple[_GeographySignal, ...],
    seeds: tuple[_SanitizedSeed, ...],
) -> dict[str, object]:
    payload = {
        "channel_plans": [
            {
                "id": str(plan.id),
                "plan_key": plan.plan_key,
                "channel_type": plan.channel_type,
                "specialty": plan.specialty,
                "geography": plan.geography,
                "icp_label": plan.icp_label,
            }
            for plan in plans
        ],
        "specialties": [signal.as_metrics() for signal in specialties],
        "geographies": [signal.as_metrics() for signal in geographies],
        "seeds": [seed.as_dict() for seed in seeds],
        "dry_run_only": True,
        "auto_publish": False,
    }
    sanitized = _json_safe(payload)
    if not isinstance(sanitized, dict):
        raise TypeError("content brief snapshot must be an object")
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
