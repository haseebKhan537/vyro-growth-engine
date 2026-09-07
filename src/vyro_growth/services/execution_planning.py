"""Dry-run execution plans for operator-approved review artifacts.

Phase 17 converts recorded approvals into structured, auditable plans. It never
sends email, enrolls campaigns, generates sendable replies, books meetings,
creates video-meet links, places calls, publishes content, launches ads, spends
money, deploys, applies optimizer recommendations, or changes live settings.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from vyro_growth.config import Settings, any_live_provider_enabled, live_provider_flags
from vyro_growth.domain import (
    ExecutionPlanRunStatus,
    ExecutionPlanType,
    ExecutionReadinessStatus,
    ReviewArtifactType,
    ReviewDecisionStatus,
)
from vyro_growth.models import Activity, ExecutionPlan, ExecutionPlanRun
from vyro_growth.services.operator_halt import HaltStatus, read_operator_halt
from vyro_growth.services.review_queue import (
    ReviewItem,
    ReviewQueueError,
    ReviewQueueService,
    sanitize_operator_text,
)

logger = structlog.get_logger(__name__)

EXECUTION_PLANNING_ACTOR = "execution_planning"
EXECUTION_PLANNING_MODEL_VERSION = "execution-planning-v1"
ALWAYS_BLOCKED_CODE = "execution_disabled_in_this_phase"


class ExecutionPlanningError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class _PlanSpec:
    plan_type: ExecutionPlanType
    proposed_action: str
    prerequisites: tuple[str, ...]
    safety_notes: tuple[str, ...]
    required_owner_approvals: tuple[str, ...]
    type_blockers: tuple[tuple[str, str], ...]


PLAN_SPECS: dict[ReviewArtifactType, _PlanSpec] = {
    ReviewArtifactType.PERSONALIZATION_DRAFT: _PlanSpec(
        plan_type=ExecutionPlanType.PERSONALIZATION_DRAFT,
        proposed_action="Prepare later owner-approved outreach from this dry-run draft",
        prerequisites=(
            "Artifact remains operator-approved",
            "Owner separately approves any future live send",
            "OUTBOUND_ENABLED stays false until the owner approves enablement",
            "Persistent operator halt stays in place until the owner lifts it",
            "Draft copy is not treated as a sendable message in this phase",
        ),
        safety_notes=(
            "No email is sent from this plan",
            "Full personalization copy is withheld",
            "Missing facts remain missing; this plan invents none",
        ),
        required_owner_approvals=(
            "Owner approval before any live outreach send",
            "Owner approval before enabling OUTBOUND_ENABLED",
        ),
        type_blockers=(
            ("no_email_sent", "This phase does not send email"),
            ("full_copy_withheld", "Draft copy is not loaded or executed"),
        ),
    ),
    ReviewArtifactType.OUTREACH_ENROLLMENT_PLAN: _PlanSpec(
        plan_type=ExecutionPlanType.OUTREACH_ENROLLMENT,
        proposed_action="Prepare later owner-approved campaign enrollment",
        prerequisites=(
            "Artifact remains operator-approved",
            "Owner separately approves any future live enrollment",
            "Suppression checks must run immediately before any future contact",
            "Campaign-provider live remains disabled until the owner approves it",
        ),
        safety_notes=(
            "No live campaign enrollment is performed",
            "No email is sent from this plan",
        ),
        required_owner_approvals=(
            "Owner approval before live campaign enrollment",
            "Owner approval before enabling OUTBOUND_ENABLED",
        ),
        type_blockers=(
            ("not_enrolled_live", "This phase does not enroll a live campaign"),
            ("no_email_sent", "This phase does not send email"),
        ),
    ),
    ReviewArtifactType.REPLY_FOLLOW_UP_PLAN: _PlanSpec(
        plan_type=ExecutionPlanType.REPLY_FOLLOW_UP,
        proposed_action="Prepare later owner-approved follow-up handling",
        prerequisites=(
            "Artifact remains operator-approved",
            "Owner separately approves any future sendable reply",
            "Inbound message body stays withheld from this plan",
        ),
        safety_notes=(
            "No autonomous reply is generated or sent",
            "Message bodies are not loaded or executed",
        ),
        required_owner_approvals=(
            "Owner approval before generating or sending a reply",
            "Owner approval before enabling OUTBOUND_ENABLED",
        ),
        type_blockers=(
            ("no_autonomous_reply", "This phase does not generate a sendable reply"),
            ("message_body_withheld", "Inbound copy is not loaded or executed"),
        ),
    ),
    ReviewArtifactType.BOOKING_PLAN: _PlanSpec(
        plan_type=ExecutionPlanType.BOOKING,
        proposed_action="Prepare later owner-approved calendar booking",
        prerequisites=(
            "Artifact remains operator-approved",
            "Owner separately approves any future calendar event or video-meet link",
            "Calendar live integration remains disabled until the owner approves it",
        ),
        safety_notes=(
            "No calendar event is created",
            "No video-meet link is created",
        ),
        required_owner_approvals=(
            "Owner approval before creating a calendar event or video-meet link",
            "Owner approval before enabling OUTBOUND_ENABLED",
        ),
        type_blockers=(
            ("no_calendar_event", "This phase does not create a calendar event"),
            ("no_meet_link", "This phase does not create a video-meet link"),
        ),
    ),
    ReviewArtifactType.VOICE_QUALIFICATION_PLAN: _PlanSpec(
        plan_type=ExecutionPlanType.VOICE_QUALIFICATION,
        proposed_action="Prepare later owner-approved consent-based voice qualification",
        prerequisites=(
            "Artifact remains operator-approved",
            "Stored consent proof must still be valid before any future call",
            "Owner separately approves any future live call",
            "Voice live remains disabled until the owner approves it",
        ),
        safety_notes=(
            "No phone call is placed",
            "Phone numbers and suspected PHI are withheld",
        ),
        required_owner_approvals=(
            "Owner approval before placing a consent-based call",
            "Owner approval before enabling OUTBOUND_ENABLED",
        ),
        type_blockers=(
            ("no_call_placed", "This phase does not place a phone call"),
            ("consent_required", "A later live call still requires stored consent"),
        ),
    ),
    ReviewArtifactType.OPTIMIZER_RECOMMENDATION: _PlanSpec(
        plan_type=ExecutionPlanType.OPTIMIZER_APPLY,
        proposed_action="Prepare later owner-approved optimizer apply",
        prerequisites=(
            "Artifact remains operator-approved",
            "Owner separately approves applying the recommendation",
            "Scoring, campaign, and provider settings stay unchanged in this phase",
        ),
        safety_notes=(
            "The recommendation is not applied",
            "No campaign, scoring, or provider setting is changed",
        ),
        required_owner_approvals=("Owner approval before applying an optimizer recommendation",),
        type_blockers=(("not_applied", "This phase does not apply optimizer recommendations"),),
    ),
    ReviewArtifactType.ACQUISITION_CHANNEL_PLAN: _PlanSpec(
        plan_type=ExecutionPlanType.ACQUISITION_CHANNEL_LAUNCH,
        proposed_action="Prepare later owner-approved acquisition channel launch",
        prerequisites=(
            "Artifact remains operator-approved",
            "Owner separately approves any future launch, publish, or spend",
            "No ads, SEO, or analytics provider is called in this phase",
        ),
        safety_notes=(
            "No campaign is launched",
            "No page is published",
            "No money is spent",
        ),
        required_owner_approvals=(
            "Owner approval before launching an acquisition channel",
            "Owner approval before publishing pages or spending",
        ),
        type_blockers=(
            ("not_launched", "This phase does not launch a channel plan"),
            ("no_spend", "This phase does not spend money"),
            ("pages_not_published", "This phase does not publish pages"),
        ),
    ),
    ReviewArtifactType.CONTENT_BRIEF: _PlanSpec(
        plan_type=ExecutionPlanType.CONTENT_PUBLISH,
        proposed_action="Prepare later owner-approved content publish",
        prerequisites=(
            "Artifact remains operator-approved",
            "Owner separately approves any future publish or ad launch",
            "No ads, analytics, or search APIs are called",
        ),
        safety_notes=(
            "No landing page or article is published",
            "No ads are launched and no money is spent",
        ),
        required_owner_approvals=(
            "Owner approval before publishing a landing page or article",
            "Owner approval before launching ads or spending",
        ),
        type_blockers=(
            ("not_published", "This phase does not publish content"),
            ("no_ads_launched", "This phase does not launch ads"),
            ("no_spend", "This phase does not spend money"),
        ),
    ),
    # contact_discovery_call is human-in-the-loop only and is excluded from approved plans.
}


@dataclass(frozen=True)
class ExecutionPlanView:
    id: UUID
    source_review_decision_id: UUID
    source_artifact_type: str
    source_artifact_id: UUID
    lead_id: UUID | None
    organization_id: UUID | None
    plan_type: str
    proposed_action: str
    readiness_status: str
    dry_run_only: bool
    no_execution: bool
    executed: bool
    execution_attempted: bool
    outbound_attempted: bool
    live_call_attempted: bool
    recommendation_applied: bool
    spend_attempted: bool
    campaign_launched: bool
    pages_published: bool
    ads_launched: bool
    owner_approval_required: bool
    owner_approved: bool
    generated_at: datetime
    idempotency_key: str
    prerequisites: tuple[dict[str, object], ...]
    blockers: tuple[dict[str, object], ...]
    safety_notes: tuple[str, ...]
    required_owner_approvals: tuple[str, ...]


@dataclass(frozen=True)
class ExecutionPlanRunResult:
    execution_plan_run_id: UUID
    status: ExecutionPlanRunStatus
    model_version: str
    snapshot_fingerprint: str
    plan_count: int
    reused_existing: bool
    reused_count: int
    ignored_non_approved_count: int
    executed_count: int
    dry_run_only: bool
    no_execution: bool
    execution_attempted: bool
    outbound_attempted: bool
    live_call_attempted: bool
    recommendation_applied: bool
    spend_attempted: bool
    campaign_launched: bool
    pages_published: bool
    ads_launched: bool
    generated_at: datetime
    operator_halt_before: str
    operator_halt_after: str
    plans: tuple[ExecutionPlanView, ...]


@dataclass(frozen=True)
class ExecutionPlanFilters:
    artifact_type: str | None = None
    artifact_id: UUID | None = None


class ExecutionPlanningService:
    """Build dry-run execution plans from approved review decisions only."""

    def generate(
        self,
        db: Session,
        settings: Settings,
        *,
        filters: ExecutionPlanFilters | None = None,
        commit: bool = True,
    ) -> ExecutionPlanRunResult:
        halt_before = read_operator_halt(db)
        generated_at = datetime.now(tz=UTC)
        selected = filters or ExecutionPlanFilters()
        approved, ignored = _approved_items(db, settings, selected)
        payload = _sanitized_snapshot(approved, ignored, selected, settings, halt_before)
        fingerprint = _fingerprint(payload)
        existing = db.scalar(
            select(ExecutionPlanRun).where(ExecutionPlanRun.snapshot_fingerprint == fingerprint)
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
                "execution_plan_run_reused",
                execution_plan_run_id=str(existing.id),
                plan_count=existing.plan_count,
                snapshot_fingerprint=fingerprint,
                executed_count=0,
                outbound_attempted=False,
            )
            return result

        drafts = [_build_plan(item, settings, halt_before, generated_at) for item in approved]
        run = ExecutionPlanRun(
            status=ExecutionPlanRunStatus.COMPLETED.value,
            model_version=EXECUTION_PLANNING_MODEL_VERSION,
            snapshot_fingerprint=fingerprint,
            plan_count=len(drafts),
            reused_count=0,
            ignored_non_approved_count=ignored,
            executed_count=0,
            dry_run_only=True,
            no_execution=True,
            execution_attempted=False,
            outbound_attempted=False,
            live_call_attempted=False,
            recommendation_applied=False,
            spend_attempted=False,
            campaign_launched=False,
            pages_published=False,
            ads_launched=False,
            input_params={
                "dry_run_only": True,
                "no_execution": True,
                "auto_execute": False,
                "artifact_type": selected.artifact_type,
                "artifact_id": str(selected.artifact_id) if selected.artifact_id else None,
            },
            snapshot_json=payload,
            started_at=generated_at,
            finished_at=generated_at,
        )
        db.add(run)
        db.flush()
        for draft in drafts:
            db.add(_plan_row(run.id, draft))
        db.add(
            Activity(
                lead_id=None,
                actor=EXECUTION_PLANNING_ACTOR,
                action="execution_plans_generated",
                details={
                    "execution_plan_run_id": str(run.id),
                    "plan_count": len(drafts),
                    "ignored_non_approved_count": ignored,
                    "dry_run_only": True,
                    "no_execution": True,
                    "executed_count": 0,
                    "execution_attempted": False,
                    "outbound_attempted": False,
                    "live_call_attempted": False,
                    "recommendation_applied": False,
                    "spend_attempted": False,
                    "campaign_launched": False,
                    "pages_published": False,
                    "ads_launched": False,
                },
            )
        )
        db.flush()
        halt_after = read_operator_halt(db)
        if halt_after is not halt_before:
            raise RuntimeError("execution planning must not change operator halt status")
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
            "execution_plan_run_completed",
            execution_plan_run_id=str(run.id),
            plan_count=len(drafts),
            snapshot_fingerprint=fingerprint,
            executed_count=0,
            outbound_attempted=False,
        )
        return result

    def latest(self, db: Session) -> ExecutionPlanRunResult | None:
        run = db.scalars(
            select(ExecutionPlanRun).order_by(ExecutionPlanRun.created_at.desc())
        ).first()
        if run is None:
            return None
        halt = read_operator_halt(db)
        return self._view(db, run, halt_before=halt, halt_after=halt, reused=True)

    def _view(
        self,
        db: Session,
        run: ExecutionPlanRun,
        *,
        halt_before: HaltStatus,
        halt_after: HaltStatus,
        reused: bool,
    ) -> ExecutionPlanRunResult:
        rows = list(
            db.scalars(
                select(ExecutionPlan)
                .where(ExecutionPlan.execution_plan_run_id == run.id)
                .order_by(ExecutionPlan.source_artifact_type, ExecutionPlan.source_artifact_id)
            )
        )
        return ExecutionPlanRunResult(
            execution_plan_run_id=run.id,
            status=ExecutionPlanRunStatus(run.status),
            model_version=run.model_version,
            snapshot_fingerprint=run.snapshot_fingerprint,
            plan_count=run.plan_count,
            reused_existing=reused,
            reused_count=run.reused_count if reused else 0,
            ignored_non_approved_count=run.ignored_non_approved_count,
            executed_count=0,
            dry_run_only=True,
            no_execution=True,
            execution_attempted=False,
            outbound_attempted=False,
            live_call_attempted=False,
            recommendation_applied=False,
            spend_attempted=False,
            campaign_launched=False,
            pages_published=False,
            ads_launched=False,
            generated_at=run.finished_at or run.created_at,
            operator_halt_before=halt_before.value,
            operator_halt_after=halt_after.value,
            plans=tuple(_plan_view(row) for row in rows),
        )


def _approved_items(
    db: Session,
    settings: Settings,
    filters: ExecutionPlanFilters,
) -> tuple[tuple[ReviewItem, ...], int]:
    try:
        queue = ReviewQueueService().list_queue(
            db,
            settings,
            include_decided=True,
            artifact_type=filters.artifact_type,
        )
    except ReviewQueueError as exc:
        raise ExecutionPlanningError(exc.code, exc.message) from exc
    items = queue.items
    if filters.artifact_id is not None:
        items = tuple(item for item in items if item.artifact_id == filters.artifact_id)
    approved = tuple(
        item
        for item in items
        if item.status == ReviewDecisionStatus.APPROVED.value
        and item.decision is not None
        and item.artifact_type != ReviewArtifactType.CONTACT_DISCOVERY_CALL.value
    )
    return approved, len(items) - len(approved)


@dataclass(frozen=True)
class _DraftPlan:
    source_review_decision_id: UUID
    source_artifact_type: str
    source_artifact_id: UUID
    lead_id: UUID | None
    organization_id: UUID | None
    plan_type: str
    proposed_action: str
    readiness_status: str
    generated_at: datetime
    idempotency_key: str
    prerequisites: tuple[dict[str, object], ...]
    blockers: tuple[dict[str, object], ...]
    safety_notes: tuple[str, ...]
    required_owner_approvals: tuple[str, ...]
    audit_json: dict[str, object]


def _build_plan(
    item: ReviewItem,
    settings: Settings,
    halt: HaltStatus,
    generated_at: datetime,
) -> _DraftPlan:
    artifact_type = ReviewArtifactType(item.artifact_type)
    spec = PLAN_SPECS[artifact_type]
    assert item.decision is not None
    blockers = _blockers(spec, settings, halt)
    readiness = ExecutionReadinessStatus.BLOCKED
    decision_id = item.decision.decision_id
    payload = {
        "model_version": EXECUTION_PLANNING_MODEL_VERSION,
        "source_review_decision_id": str(decision_id),
        "source_artifact_type": item.artifact_type,
        "source_artifact_id": str(item.artifact_id),
        "plan_type": spec.plan_type.value,
        "safety": _safety_snapshot(settings, halt),
    }
    return _DraftPlan(
        source_review_decision_id=decision_id,
        source_artifact_type=item.artifact_type,
        source_artifact_id=item.artifact_id,
        lead_id=item.lead_id,
        organization_id=item.organization_id,
        plan_type=spec.plan_type.value,
        proposed_action=spec.proposed_action,
        readiness_status=readiness.value,
        generated_at=generated_at,
        idempotency_key=_fingerprint(payload),
        prerequisites=_prerequisites(spec, halt, settings),
        blockers=blockers,
        safety_notes=spec.safety_notes,
        required_owner_approvals=spec.required_owner_approvals,
        audit_json={
            "artifact_title": item.title,
            "artifact_summary": item.summary,
            "reviewer": item.decision.reviewer,
            "source": item.decision.source,
            "dry_run_only": True,
            "no_execution": True,
            "executed": False,
            "execution_attempted": False,
            "outbound_attempted": False,
            "owner_approval_required": True,
            "owner_approved": False,
        },
    )


def _prerequisites(
    spec: _PlanSpec, halt: HaltStatus, settings: Settings
) -> tuple[dict[str, object], ...]:
    halt_lifted = halt is HaltStatus.CLEARED
    items = [
        {
            "code": "artifact_operator_approved",
            "label": spec.prerequisites[0],
            "met": True,
        },
        {
            "code": "owner_approval_for_live_action",
            "label": "Separate owner approval for the live action",
            "met": False,
        },
        {
            "code": "outbound_enablement_owner_approved",
            "label": "OUTBOUND_ENABLED remains false until the owner approves enablement",
            "met": not settings.outbound_enabled,
        },
        {
            "code": "operator_halt_policy",
            "label": "Persistent operator halt remains in place until the owner lifts it",
            "met": not halt_lifted,
        },
    ]
    extra = spec.prerequisites[1:]
    for index, label in enumerate(extra):
        items.append({"code": f"prerequisite_{index + 1}", "label": label, "met": False})
    return tuple(items)


def _blockers(
    spec: _PlanSpec, settings: Settings, halt: HaltStatus
) -> tuple[dict[str, object], ...]:
    items: list[dict[str, object]] = [
        {
            "code": ALWAYS_BLOCKED_CODE,
            "label": "Phase 17 records a dry-run plan only and does not execute",
        },
        {
            "code": "owner_approval_required",
            "label": "A separate owner approval is required before any future live action",
        },
    ]
    if not settings.outbound_enabled:
        items.append(
            {
                "code": "outbound_disabled",
                "label": "OUTBOUND_ENABLED is false; live outbound remains blocked",
            }
        )
    if halt is HaltStatus.HALTED:
        items.append(
            {
                "code": "operator_halt_active",
                "label": "Persistent operator halt is active",
            }
        )
    elif halt is HaltStatus.UNAVAILABLE:
        items.append(
            {
                "code": "operator_halt_unavailable",
                "label": "Persistent operator halt is missing or unreadable (fail-closed)",
            }
        )
    if not any_live_provider_enabled(settings):
        items.append(
            {
                "code": "live_providers_disabled",
                "label": "Live provider flags remain disabled",
            }
        )
    for code, label in spec.type_blockers:
        items.append({"code": code, "label": label})
    return tuple(items)


def _safety_snapshot(settings: Settings, halt: HaltStatus) -> dict[str, object]:
    return {
        "outbound_enabled": settings.outbound_enabled,
        "operator_halt_status": halt.value,
        "live_providers": live_provider_flags(settings),
        "dry_run_only": True,
        "no_execution": True,
    }


def _sanitized_snapshot(
    approved: Sequence[ReviewItem],
    ignored: int,
    filters: ExecutionPlanFilters,
    settings: Settings,
    halt: HaltStatus,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "model_version": EXECUTION_PLANNING_MODEL_VERSION,
        "filters": {
            "artifact_type": filters.artifact_type,
            "artifact_id": str(filters.artifact_id) if filters.artifact_id else None,
        },
        "approved": [
            {
                "decision_id": str(item.decision.decision_id) if item.decision else None,
                "artifact_type": item.artifact_type,
                "artifact_id": str(item.artifact_id),
                "status": item.status,
            }
            for item in approved
        ],
        "ignored_non_approved_count": ignored,
        "safety": _safety_snapshot(settings, halt),
    }
    sanitized = _json_safe(payload)
    if not isinstance(sanitized, dict):
        raise TypeError("execution planning snapshot must be an object")
    return {str(key): value for key, value in sanitized.items()}


def _plan_row(run_id: UUID, draft: _DraftPlan) -> ExecutionPlan:
    return ExecutionPlan(
        execution_plan_run_id=run_id,
        source_review_decision_id=draft.source_review_decision_id,
        source_artifact_type=draft.source_artifact_type,
        source_artifact_id=draft.source_artifact_id,
        lead_id=draft.lead_id,
        organization_id=draft.organization_id,
        plan_type=draft.plan_type,
        proposed_action=draft.proposed_action,
        readiness_status=draft.readiness_status,
        dry_run_only=True,
        no_execution=True,
        executed=False,
        execution_attempted=False,
        outbound_attempted=False,
        live_call_attempted=False,
        recommendation_applied=False,
        spend_attempted=False,
        campaign_launched=False,
        pages_published=False,
        ads_launched=False,
        owner_approval_required=True,
        owner_approved=False,
        generated_at=draft.generated_at,
        idempotency_key=draft.idempotency_key,
        prerequisites_json=list(draft.prerequisites),
        blockers_json=list(draft.blockers),
        safety_notes_json=list(draft.safety_notes),
        required_owner_approvals_json=list(draft.required_owner_approvals),
        audit_json=draft.audit_json,
    )


def _plan_view(row: ExecutionPlan) -> ExecutionPlanView:
    return ExecutionPlanView(
        id=row.id,
        source_review_decision_id=row.source_review_decision_id,
        source_artifact_type=row.source_artifact_type,
        source_artifact_id=row.source_artifact_id,
        lead_id=row.lead_id,
        organization_id=row.organization_id,
        plan_type=row.plan_type,
        proposed_action=row.proposed_action,
        readiness_status=row.readiness_status,
        dry_run_only=True,
        no_execution=True,
        executed=False,
        execution_attempted=False,
        outbound_attempted=False,
        live_call_attempted=False,
        recommendation_applied=False,
        spend_attempted=False,
        campaign_launched=False,
        pages_published=False,
        ads_launched=False,
        owner_approval_required=True,
        owner_approved=False,
        generated_at=row.generated_at,
        idempotency_key=row.idempotency_key,
        prerequisites=_object_tuple(row.prerequisites_json),
        blockers=_object_tuple(row.blockers_json),
        safety_notes=_string_tuple(row.safety_notes_json),
        required_owner_approvals=_string_tuple(row.required_owner_approvals_json),
    )


def _object_tuple(value: object) -> tuple[dict[str, object], ...]:
    if not isinstance(value, list):
        return ()
    items: list[dict[str, object]] = []
    for entry in value:
        if isinstance(entry, dict):
            items.append({str(key): item for key, item in entry.items()})
    return tuple(items)


def _string_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    items: list[str] = []
    for entry in value:
        if isinstance(entry, str):
            cleaned = sanitize_operator_text(entry) or entry
            if cleaned != "[REDACTED_UNSAFE_TEXT]":
                items.append(cleaned)
    return tuple(items)


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


def _fingerprint(payload: Mapping[str, object]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
