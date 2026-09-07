"""Operator review queue: list pending dry-run artifacts and record decisions.

Phase 14 is a control-plane foundation only. Listing and recording a decision
never sends email, enrolls campaigns, books meetings, places calls, generates
sendable autonomous replies, applies optimizer recommendations, or publishes content.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from vyro_growth.config import Settings
from vyro_growth.domain import (
    BookingPlanStatus,
    ContactDiscoveryCallStatus,
    ContentBriefApprovalStatus,
    EnrollmentStatus,
    PersonalizationReadiness,
    RecommendationApprovalStatus,
    ReplyClassificationOutcome,
    ReplyIntent,
    ReviewArtifactType,
    ReviewDecisionStatus,
    ReviewItemStatus,
    VoicePlanStatus,
)
from vyro_growth.models import (
    Activity,
    BookingPlan,
    CampaignEnrollment,
    ChannelPlan,
    ContactDiscoveryCall,
    ContentBrief,
    OperatorReviewDecision,
    OptimizerRecommendation,
    PersonalizationDraft,
    ReplyClassification,
    VoiceQualificationPlan,
)
from vyro_growth.services.operator_halt import HaltStatus, read_operator_halt

logger = structlog.get_logger(__name__)

REVIEW_QUEUE_ACTOR = "review_queue"
MAX_NOTES_LENGTH = 500
FOLLOW_UP_INTENTS = frozenset(
    {
        ReplyIntent.INTERESTED.value,
        ReplyIntent.MEETING_REQUEST.value,
        ReplyIntent.NEEDS_MORE_INFO.value,
        ReplyIntent.REFERRAL.value,
    }
)
EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.I)
PHONE_RE = re.compile(r"(?:\+?1[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?)?\d{3}[-.\s]?\d{4}")
SECRET_RE = re.compile(
    r"\b(?:sk-|rk-|pk_|xox[abp]-|api[_-]?key)[A-Za-z0-9_\-]{8,}",
    re.I,
)
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


class ReviewQueueError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class ReviewDecisionView:
    decision_id: UUID
    decision: str
    reviewer: str
    source: str
    reviewer_notes: str | None
    decided_at: datetime


@dataclass(frozen=True)
class ReviewItem:
    artifact_type: str
    artifact_id: UUID
    lead_id: UUID | None
    organization_id: UUID | None
    title: str
    summary: str
    status: str
    created_at: datetime
    risk_labels: tuple[str, ...]
    executable_later: bool
    executed: bool
    decision: ReviewDecisionView | None


@dataclass(frozen=True)
class ReviewQueueResult:
    generated_at: datetime
    pending_count: int
    decided_count: int
    by_artifact_type: dict[str, int]
    by_decision: dict[str, int]
    executed_count: int
    outbound_attempted: bool
    live_call_attempted: bool
    recommendation_applied: bool
    operator_halt_status: str
    items: tuple[ReviewItem, ...]


@dataclass(frozen=True)
class ReviewDecisionResult:
    decision_id: UUID
    artifact_type: str
    artifact_id: UUID
    decision: str
    reviewer: str
    source: str
    reviewer_notes: str | None
    decided_at: datetime
    executed: bool
    execution_attempted: bool
    outbound_attempted: bool
    live_call_attempted: bool
    recommendation_applied: bool
    operator_halt_before: str
    operator_halt_after: str


@dataclass(frozen=True)
class _Candidate:
    artifact_type: ReviewArtifactType
    artifact_id: UUID
    lead_id: UUID | None
    organization_id: UUID | None
    title: str
    summary: str
    created_at: datetime
    extra_labels: tuple[str, ...]
    executable_later: bool = True
    fallback_status: str | None = None


class ReviewQueueService:
    """Normalize pending dry-run artifacts and persist operator decisions."""

    def list_queue(
        self,
        db: Session,
        settings: Settings,
        *,
        include_decided: bool = False,
        artifact_type: str | None = None,
    ) -> ReviewQueueResult:
        halt = read_operator_halt(db)
        selected_type = _parse_optional_artifact_type(artifact_type)
        decisions = _decision_map(db)
        candidates = _collect_candidates(db)
        items = [
            _to_item(
                candidate,
                decisions.get((candidate.artifact_type.value, candidate.artifact_id)),
                halt,
                outbound_enabled=settings.outbound_enabled,
            )
            for candidate in candidates
            if selected_type is None or candidate.artifact_type is selected_type
        ]
        pending_status = ReviewItemStatus.PENDING_OPERATOR_REVIEW.value
        pending = [item for item in items if item.status == pending_status]
        decided = [item for item in items if item.status != pending_status]
        visible_items = items if include_decided else pending
        visible = tuple(sorted(visible_items, key=_item_sort_key))
        by_type = _count_by(visible, key=lambda item: item.artifact_type)
        by_decision = _count_by(
            decided,
            key=lambda item: item.decision.decision if item.decision is not None else "unknown",
        )
        result = ReviewQueueResult(
            generated_at=datetime.now(tz=UTC),
            pending_count=len(pending),
            decided_count=len(decided),
            by_artifact_type=by_type,
            by_decision=by_decision,
            executed_count=0,
            outbound_attempted=False,
            live_call_attempted=False,
            recommendation_applied=False,
            operator_halt_status=halt.value,
            items=visible,
        )
        logger.info(
            "review_queue_listed",
            pending_count=result.pending_count,
            decided_count=result.decided_count,
            include_decided=include_decided,
            outbound_attempted=False,
            executed_count=0,
        )
        return result

    def get_item(
        self,
        db: Session,
        settings: Settings,
        *,
        artifact_type: str,
        artifact_id: UUID,
    ) -> ReviewItem | None:
        """Return one sanitized review item, including decided artifacts.

        Read-only. Does not record a decision or execute the artifact.
        """

        try:
            result = self.list_queue(
                db,
                settings,
                include_decided=True,
                artifact_type=artifact_type,
            )
        except ReviewQueueError:
            return None
        for item in result.items:
            if item.artifact_id == artifact_id:
                return item
        return None

    def record_decision(
        self,
        db: Session,
        *,
        artifact_type: str,
        artifact_id: UUID,
        decision: str,
        reviewer: str | None = None,
        source: str = "cli",
        reviewer_notes: str | None = None,
        commit: bool = True,
    ) -> ReviewDecisionResult:
        halt_before = read_operator_halt(db)
        parsed_type = _parse_artifact_type(artifact_type)
        parsed_decision = _parse_decision(decision)
        candidate = _require_reviewable_candidate(db, parsed_type, artifact_id)
        notes = sanitize_operator_text(reviewer_notes)
        reviewer_name = sanitize_operator_text(reviewer) or "operator"
        source_name = sanitize_operator_text(source) or "cli"
        decided_at = datetime.now(tz=UTC)
        existing = db.scalar(
            select(OperatorReviewDecision).where(
                OperatorReviewDecision.artifact_type == parsed_type.value,
                OperatorReviewDecision.artifact_id == artifact_id,
            )
        )
        previous = existing.decision if existing is not None else None
        if existing is None:
            row = OperatorReviewDecision(
                artifact_type=parsed_type.value,
                artifact_id=artifact_id,
                decision=parsed_decision.value,
                previous_decision=None,
                reviewer=reviewer_name,
                source=source_name,
                reviewer_notes=notes,
                decided_at=decided_at,
                item_status=parsed_decision.value,
                executed=False,
                execution_attempted=False,
                outbound_attempted=False,
                live_call_attempted=False,
                recommendation_applied=False,
                audit_json=_decision_audit(
                    parsed_type,
                    candidate,
                    parsed_decision,
                    reviewer_name,
                    source_name,
                ),
            )
            db.add(row)
        else:
            existing.previous_decision = previous
            existing.decision = parsed_decision.value
            existing.reviewer = reviewer_name
            existing.source = source_name
            existing.reviewer_notes = notes
            existing.decided_at = decided_at
            existing.item_status = parsed_decision.value
            existing.executed = False
            existing.execution_attempted = False
            existing.outbound_attempted = False
            existing.live_call_attempted = False
            existing.recommendation_applied = False
            existing.audit_json = _decision_audit(
                parsed_type,
                candidate,
                parsed_decision,
                reviewer_name,
                source_name,
                previous=previous,
            )
            row = existing
        db.add(
            Activity(
                lead_id=candidate.lead_id,
                actor=REVIEW_QUEUE_ACTOR,
                action="operator_review_decision_recorded",
                details={
                    "artifact_type": parsed_type.value,
                    "artifact_id": str(artifact_id),
                    "decision": parsed_decision.value,
                    "previous_decision": previous,
                    "reviewer": reviewer_name,
                    "source": source_name,
                    "executed": False,
                    "execution_attempted": False,
                    "outbound_attempted": False,
                    "live_call_attempted": False,
                    "recommendation_applied": False,
                },
            )
        )
        db.flush()
        halt_after = read_operator_halt(db)
        if halt_after is not halt_before:
            raise RuntimeError("review queue must not change operator halt status")
        if commit:
            db.commit()
            db.refresh(row)
        logger.info(
            "operator_review_decision_recorded",
            artifact_type=parsed_type.value,
            artifact_id=str(artifact_id),
            decision=parsed_decision.value,
            executed=False,
            outbound_attempted=False,
        )
        return ReviewDecisionResult(
            decision_id=row.id,
            artifact_type=parsed_type.value,
            artifact_id=artifact_id,
            decision=parsed_decision.value,
            reviewer=reviewer_name,
            source=source_name,
            reviewer_notes=notes,
            decided_at=row.decided_at,
            executed=False,
            execution_attempted=False,
            outbound_attempted=False,
            live_call_attempted=False,
            recommendation_applied=False,
            operator_halt_before=halt_before.value,
            operator_halt_after=halt_after.value,
        )


def sanitize_operator_text(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    lowered = text.lower()
    if any(token in lowered for token in UNSAFE_FIELD_TOKENS):
        return "[REDACTED_UNSAFE_TEXT]"
    if any(phrase in lowered for phrase in PHI_PHRASES):
        return "[REDACTED_UNSAFE_TEXT]"
    if re.search(r"\bpatients?\b", lowered):
        return "[REDACTED_UNSAFE_TEXT]"
    cleaned = EMAIL_RE.sub("[REDACTED_EMAIL]", text)
    cleaned = PHONE_RE.sub("[REDACTED_PHONE]", cleaned)
    cleaned = SECRET_RE.sub("[REDACTED_SECRET]", cleaned)
    if len(cleaned) > MAX_NOTES_LENGTH:
        cleaned = cleaned[:MAX_NOTES_LENGTH]
    return cleaned


def _parse_optional_artifact_type(value: str | None) -> ReviewArtifactType | None:
    if value is None or not value.strip():
        return None
    return _parse_artifact_type(value)


def _parse_artifact_type(value: str) -> ReviewArtifactType:
    try:
        return ReviewArtifactType(value.strip())
    except ValueError as exc:
        raise ReviewQueueError("unknown_artifact_type", "Unknown review artifact type") from exc


def _parse_decision(value: str) -> ReviewDecisionStatus:
    try:
        return ReviewDecisionStatus(value.strip())
    except ValueError as exc:
        raise ReviewQueueError(
            "invalid_decision",
            "Decision must be approved, rejected, or needs_changes",
        ) from exc


def _collect_candidates(db: Session) -> list[_Candidate]:
    return [
        *_personalization_candidates(db),
        *_outreach_candidates(db),
        *_reply_candidates(db),
        *_booking_candidates(db),
        *_voice_candidates(db),
        *_optimizer_candidates(db),
        *_channel_plan_candidates(db),
        *_content_brief_candidates(db),
        *_contact_discovery_call_candidates(db),
    ]


def _personalization_candidates(db: Session) -> list[_Candidate]:
    rows = db.scalars(
        select(PersonalizationDraft).where(
            PersonalizationDraft.readiness_status == PersonalizationReadiness.READY.value
        )
    ).all()
    return [
        _Candidate(
            artifact_type=ReviewArtifactType.PERSONALIZATION_DRAFT,
            artifact_id=row.id,
            lead_id=row.lead_id,
            organization_id=row.organization_id,
            title="Personalization draft ready for operator review",
            summary="Evidence-grounded dry-run draft. Full copy is withheld from this queue.",
            created_at=_created_at(row),
            extra_labels=("dry_run_draft", "no_email_sent", "full_copy_withheld"),
        )
        for row in rows
    ]


def _outreach_candidates(db: Session) -> list[_Candidate]:
    rows = db.scalars(
        select(CampaignEnrollment).where(
            CampaignEnrollment.status == EnrollmentStatus.PLANNED.value
        )
    ).all()
    return [
        _Candidate(
            artifact_type=ReviewArtifactType.OUTREACH_ENROLLMENT_PLAN,
            artifact_id=row.id,
            lead_id=row.lead_id,
            organization_id=row.organization_id,
            title="Dry-run outreach enrollment plan",
            summary="Planned campaign enrollment only. No live campaign enrollment or email send.",
            created_at=_created_at(row),
            extra_labels=("dry_run_plan", "not_enrolled_live", "no_email_sent"),
        )
        for row in rows
    ]


def _reply_candidates(db: Session) -> list[_Candidate]:
    rows = db.scalars(
        select(ReplyClassification).where(
            ReplyClassification.outcome == ReplyClassificationOutcome.CLASSIFIED.value,
            ReplyClassification.intent.in_(FOLLOW_UP_INTENTS),
        )
    ).all()
    items: list[_Candidate] = []
    for row in rows:
        intent = row.intent
        items.append(
            _Candidate(
                artifact_type=ReviewArtifactType.REPLY_FOLLOW_UP_PLAN,
                artifact_id=row.id,
                lead_id=row.lead_id,
                organization_id=None,
                title=f"Reply follow-up plan ({intent})",
                summary="Classified inbound reply. No autonomous reply was generated or sent.",
                created_at=_created_at(row),
                extra_labels=(
                    "classification_only",
                    "no_autonomous_reply",
                    "message_body_withheld",
                ),
            )
        )
    return items


def _booking_candidates(db: Session) -> list[_Candidate]:
    rows = db.scalars(
        select(BookingPlan).where(BookingPlan.status == BookingPlanStatus.PLANNED.value)
    ).all()
    return [
        _Candidate(
            artifact_type=ReviewArtifactType.BOOKING_PLAN,
            artifact_id=row.id,
            lead_id=row.lead_id,
            organization_id=row.organization_id,
            title="Dry-run booking plan",
            summary="Proposed meeting slots only. No calendar event or Meet link was created.",
            created_at=_created_at(row),
            extra_labels=("dry_run_plan", "no_calendar_event", "no_meet_link"),
        )
        for row in rows
    ]


def _voice_candidates(db: Session) -> list[_Candidate]:
    rows = db.scalars(
        select(VoiceQualificationPlan).where(
            VoiceQualificationPlan.status == VoicePlanStatus.PLANNED.value
        )
    ).all()
    return [
        _Candidate(
            artifact_type=ReviewArtifactType.VOICE_QUALIFICATION_PLAN,
            artifact_id=row.id,
            lead_id=row.lead_id,
            organization_id=row.organization_id,
            title="Dry-run voice qualification plan",
            summary="Consent-based voice plan only. No phone call was placed.",
            created_at=_created_at(row),
            extra_labels=("dry_run_plan", "no_call_placed", "consent_required"),
        )
        for row in rows
    ]


def _optimizer_candidates(db: Session) -> list[_Candidate]:
    rows = db.scalars(
        select(OptimizerRecommendation).where(
            OptimizerRecommendation.approval_status
            == RecommendationApprovalStatus.PENDING_OPERATOR_REVIEW.value,
            OptimizerRecommendation.applied.is_(False),
        )
    ).all()
    items: list[_Candidate] = []
    for row in rows:
        fallback = f"Growth optimizer recommendation ({row.category})"
        title = sanitize_operator_text(row.title) or fallback
        if title == "[REDACTED_UNSAFE_TEXT]":
            title = fallback
        items.append(
            _Candidate(
                artifact_type=ReviewArtifactType.OPTIMIZER_RECOMMENDATION,
                artifact_id=row.id,
                lead_id=None,
                organization_id=None,
                title=title,
                summary="Dry-run growth recommendation. Approval does not apply the change.",
                created_at=_as_utc(row.generated_at),
                extra_labels=("dry_run_recommendation", "not_applied"),
            )
        )
    return items


def _channel_plan_candidates(db: Session) -> list[_Candidate]:
    rows = db.scalars(
        select(ChannelPlan).where(
            ChannelPlan.approval_status
            == RecommendationApprovalStatus.PENDING_OPERATOR_REVIEW.value,
            ChannelPlan.launched.is_(False),
        )
    ).all()
    items: list[_Candidate] = []
    for row in rows:
        fallback = f"Acquisition channel plan ({row.channel})"
        title = sanitize_operator_text(row.title) or fallback
        if title == "[REDACTED_UNSAFE_TEXT]":
            title = fallback
        items.append(
            _Candidate(
                artifact_type=ReviewArtifactType.ACQUISITION_CHANNEL_PLAN,
                artifact_id=row.id,
                lead_id=None,
                organization_id=None,
                title=title,
                summary=(
                    "Dry-run acquisition channel plan. Approval does not launch, "
                    "publish, spend, or contact anyone."
                ),
                created_at=_as_utc(row.generated_at),
                extra_labels=("dry_run_plan", "no_spend", "not_launched", "pages_not_published"),
            )
        )
    return items


def _content_brief_candidates(db: Session) -> list[_Candidate]:
    rows = db.scalars(
        select(ContentBrief).where(
            ContentBrief.approval_status
            == ContentBriefApprovalStatus.PENDING_OPERATOR_REVIEW.value,
            ContentBrief.published.is_(False),
            ContentBrief.publish_attempted.is_(False),
        )
    ).all()
    items: list[_Candidate] = []
    for row in rows:
        fallback = f"Content brief ({row.brief_type})"
        title = sanitize_operator_text(row.title) or fallback
        if title == "[REDACTED_UNSAFE_TEXT]":
            title = fallback
        items.append(
            _Candidate(
                artifact_type=ReviewArtifactType.CONTENT_BRIEF,
                artifact_id=row.id,
                lead_id=None,
                organization_id=None,
                title=title,
                summary="Review-only landing page or SEO brief. Approval does not publish.",
                created_at=_as_utc(row.generated_at),
                extra_labels=("dry_run_brief", "not_published", "no_ads_launched"),
            )
        )
    return items


def _contact_discovery_call_candidates(db: Session) -> list[_Candidate]:
    rows = db.scalars(select(ContactDiscoveryCall)).all()
    items: list[_Candidate] = []
    for row in rows:
        queued = row.status == ContactDiscoveryCallStatus.QUEUED.value
        fallback = None if queued else row.status
        items.append(
            _Candidate(
                artifact_type=ReviewArtifactType.CONTACT_DISCOVERY_CALL,
                artifact_id=row.id,
                lead_id=row.lead_id,
                organization_id=row.organization_id,
                title="Human phone-verification task",
                summary=(
                    "Human-in-the-loop contact discovery. No call was placed, "
                    "autodialed, or routed through VoiceProvider."
                ),
                created_at=_created_at(row),
                extra_labels=(
                    "human_in_the_loop",
                    "no_call_placed",
                    "no_ai_voice",
                    "no_autodial",
                    "not_executable",
                    f"phone_verification_{row.status}",
                ),
                executable_later=False,
                fallback_status=fallback,
            )
        )
    return items


def _require_reviewable_candidate(
    db: Session,
    artifact_type: ReviewArtifactType,
    artifact_id: UUID,
) -> _Candidate:
    lookup = {
        (item.artifact_type, item.artifact_id): item for item in _collect_candidates(db)
    }
    found = lookup.get((artifact_type, artifact_id))
    if found is not None:
        return found
    if _artifact_exists(db, artifact_type, artifact_id):
        raise ReviewQueueError(
            "artifact_not_reviewable",
            "Artifact exists but is not pending operator review",
        )
    raise ReviewQueueError("artifact_not_found", "Review artifact was not found")


def _artifact_exists(db: Session, artifact_type: ReviewArtifactType, artifact_id: UUID) -> bool:
    model = {
        ReviewArtifactType.PERSONALIZATION_DRAFT: PersonalizationDraft,
        ReviewArtifactType.OUTREACH_ENROLLMENT_PLAN: CampaignEnrollment,
        ReviewArtifactType.REPLY_FOLLOW_UP_PLAN: ReplyClassification,
        ReviewArtifactType.BOOKING_PLAN: BookingPlan,
        ReviewArtifactType.VOICE_QUALIFICATION_PLAN: VoiceQualificationPlan,
        ReviewArtifactType.OPTIMIZER_RECOMMENDATION: OptimizerRecommendation,
        ReviewArtifactType.ACQUISITION_CHANNEL_PLAN: ChannelPlan,
        ReviewArtifactType.CONTENT_BRIEF: ContentBrief,
        ReviewArtifactType.CONTACT_DISCOVERY_CALL: ContactDiscoveryCall,
    }[artifact_type]
    return db.get(model, artifact_id) is not None


def _decision_map(db: Session) -> dict[tuple[str, UUID], OperatorReviewDecision]:
    rows = db.scalars(select(OperatorReviewDecision)).all()
    return {(row.artifact_type, row.artifact_id): row for row in rows}


def _to_item(
    candidate: _Candidate,
    decision_row: OperatorReviewDecision | None,
    halt: HaltStatus,
    *,
    outbound_enabled: bool,
) -> ReviewItem:
    decision = None
    status = ReviewItemStatus.PENDING_OPERATOR_REVIEW.value
    if decision_row is not None:
        status = decision_row.decision
        decision = ReviewDecisionView(
            decision_id=decision_row.id,
            decision=decision_row.decision,
            reviewer=decision_row.reviewer,
            source=decision_row.source,
            reviewer_notes=decision_row.reviewer_notes,
            decided_at=decision_row.decided_at,
        )
    elif candidate.fallback_status:
        status = candidate.fallback_status
    executable_later = candidate.executable_later and status in {
        ReviewItemStatus.PENDING_OPERATOR_REVIEW.value,
        ReviewDecisionStatus.APPROVED.value,
    }
    labels = (
        "decision_record_only",
        "not_executed",
        *_safety_labels(halt, outbound_enabled=outbound_enabled),
        *candidate.extra_labels,
    )
    return ReviewItem(
        artifact_type=candidate.artifact_type.value,
        artifact_id=candidate.artifact_id,
        lead_id=candidate.lead_id,
        organization_id=candidate.organization_id,
        title=candidate.title,
        summary=candidate.summary,
        status=status,
        created_at=candidate.created_at,
        risk_labels=labels,
        executable_later=executable_later,
        executed=False,
        decision=decision,
    )


def _safety_labels(halt: HaltStatus, *, outbound_enabled: bool) -> tuple[str, ...]:
    labels = ["outbound_disabled"] if not outbound_enabled else ["outbound_enabled_flag"]
    if halt is HaltStatus.HALTED:
        labels.append("operator_halt_active")
    elif halt is HaltStatus.UNAVAILABLE:
        labels.append("operator_halt_unavailable")
    return tuple(labels)


def _as_utc(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(tz=UTC)
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def _created_at(row: Any) -> datetime:
    created = getattr(row, "created_at", None)
    return _as_utc(created if isinstance(created, datetime) else None)


def _item_sort_key(item: ReviewItem) -> tuple[datetime, str, str]:
    return (item.created_at, item.artifact_type, str(item.artifact_id))


def _count_by(items: Sequence[ReviewItem], *, key: Callable[[ReviewItem], str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        label = key(item)
        counts[label] = counts.get(label, 0) + 1
    return counts


def _decision_audit(
    artifact_type: ReviewArtifactType,
    candidate: _Candidate,
    decision: ReviewDecisionStatus,
    reviewer: str,
    source: str,
    *,
    previous: str | None = None,
) -> dict[str, object]:
    return {
        "artifact_type": artifact_type.value,
        "decision": decision.value,
        "previous_decision": previous,
        "reviewer": reviewer,
        "source": source,
        "executed": False,
        "execution_attempted": False,
        "outbound_attempted": False,
        "live_call_attempted": False,
        "recommendation_applied": False,
        "lead_id": str(candidate.lead_id) if candidate.lead_id is not None else None,
        "organization_id": (
            str(candidate.organization_id) if candidate.organization_id is not None else None
        ),
    }
