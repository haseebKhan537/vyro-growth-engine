"""Live-readiness preflight and owner approval packets.

Phase 18 inspects dry-run execution plans and safe local/config metadata.
Phase 23 records an owner/operator decision against a stored packet. Neither
path sends email, enrolls campaigns, generates sendable replies, books
meetings, creates video-meet links, places calls, publishes content, launches
ads, spends money, deploys, applies optimizer recommendations, or changes
live settings. Secret values are never returned. Recording a decision never
executes the packet.
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

from vyro_growth.config import (
    Settings,
    any_live_provider_enabled,
    credential_presence_flags,
    live_provider_flags,
)
from vyro_growth.domain import (
    ApprovalPacketRunStatus,
    ExecutionPlanType,
    FindingSeverity,
    PreflightStatus,
    ReviewDecisionStatus,
)
from vyro_growth.models import (
    Activity,
    ApprovalPacketRun,
    ExecutionPlan,
    OwnerApprovalPacket,
    OwnerApprovalPacketDecision,
)
from vyro_growth.services.operator_halt import HaltStatus, read_operator_halt
from vyro_growth.services.review_queue import MAX_NOTES_LENGTH, sanitize_operator_text

logger = structlog.get_logger(__name__)

APPROVAL_PACKET_ACTOR = "approval_packets"
APPROVAL_PACKET_MODEL_VERSION = "approval-packets-v1"
APPROVAL_PACKET_DECISION_ACTION = "owner_approval_packet_decision_recorded"
ALWAYS_BLOCKED_CODE = "execution_disabled_in_this_phase"
SUPPORTED_PLAN_FAMILIES: frozenset[str] = frozenset(item.value for item in ExecutionPlanType)

CREDENTIAL_LABELS: dict[str, str] = {
    "generative_ai_api_key": "Generative-AI API key is configured",
    "campaign_provider_api_key": "Campaign-provider API key is configured",
    "calendar_api_key": "Calendar API key is configured",
    "voice_api_key": "Voice-provider API key is configured",
}

FAMILY_CREDENTIALS: dict[str, tuple[str, ...]] = {
    ExecutionPlanType.PERSONALIZATION_DRAFT.value: ("generative_ai_api_key",),
    ExecutionPlanType.OUTREACH_ENROLLMENT.value: ("campaign_provider_api_key",),
    ExecutionPlanType.REPLY_FOLLOW_UP.value: ("generative_ai_api_key",),
    ExecutionPlanType.BOOKING.value: ("calendar_api_key",),
    ExecutionPlanType.VOICE_QUALIFICATION.value: ("voice_api_key",),
    ExecutionPlanType.OPTIMIZER_APPLY.value: (),
    ExecutionPlanType.ACQUISITION_CHANNEL_LAUNCH.value: (),
    ExecutionPlanType.CONTENT_PUBLISH.value: (),
}

FAMILY_OWNER_DECISIONS: dict[str, tuple[str, ...]] = {
    ExecutionPlanType.PERSONALIZATION_DRAFT.value: (
        "Owner approval before any live outreach send",
        "Owner approval before enabling OUTBOUND_ENABLED",
    ),
    ExecutionPlanType.OUTREACH_ENROLLMENT.value: (
        "Owner approval before live campaign enrollment",
        "Owner approval before enabling OUTBOUND_ENABLED",
    ),
    ExecutionPlanType.REPLY_FOLLOW_UP.value: (
        "Owner approval before generating or sending a reply",
        "Owner approval before enabling OUTBOUND_ENABLED",
    ),
    ExecutionPlanType.BOOKING.value: (
        "Owner approval before creating a calendar event or video-meet link",
        "Owner approval before enabling OUTBOUND_ENABLED",
    ),
    ExecutionPlanType.VOICE_QUALIFICATION.value: (
        "Owner approval before placing a consent-based call",
        "Owner approval before enabling OUTBOUND_ENABLED",
    ),
    ExecutionPlanType.OPTIMIZER_APPLY.value: (
        "Owner approval before applying an optimizer recommendation",
    ),
    ExecutionPlanType.ACQUISITION_CHANNEL_LAUNCH.value: (
        "Owner approval before launching an acquisition channel",
        "Owner approval before publishing pages or spending",
    ),
    ExecutionPlanType.CONTENT_PUBLISH.value: (
        "Owner approval before publishing a landing page or article",
        "Owner approval before launching ads or spending",
    ),
}


class ApprovalPacketError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class ApprovalPacketDecisionView:
    decision_id: UUID
    decision: str
    reviewer: str
    source: str
    reviewer_notes: str | None
    decided_at: datetime


@dataclass(frozen=True)
class ApprovalPacketView:
    id: UUID
    source_execution_plan_id: UUID
    source_execution_plan_run_id: UUID
    source_artifact_type: str
    source_artifact_id: UUID
    plan_family: str
    proposed_action: str
    preflight_status: str
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
    preflight_checklist: tuple[dict[str, object], ...]
    missing_prerequisites: tuple[dict[str, object], ...]
    findings: tuple[dict[str, object], ...]
    required_owner_decisions: tuple[str, ...]
    decision: ApprovalPacketDecisionView | None = None


@dataclass(frozen=True)
class ApprovalPacketDecisionResult:
    decision_id: UUID
    packet_id: UUID
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
    spend_attempted: bool
    campaign_launched: bool
    pages_published: bool
    ads_launched: bool
    owner_approved: bool
    operator_halt_before: str
    operator_halt_after: str


@dataclass(frozen=True)
class ApprovalPacketRunResult:
    approval_packet_run_id: UUID
    status: ApprovalPacketRunStatus
    model_version: str
    snapshot_fingerprint: str
    packet_count: int
    reused_existing: bool
    reused_count: int
    missing_plan_count: int
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
    packets: tuple[ApprovalPacketView, ...]


@dataclass(frozen=True)
class ApprovalPacketFilters:
    plan_type: str | None = None
    execution_plan_id: UUID | None = None


class ApprovalPacketService:
    """Build sanitized owner approval packets from dry-run execution plans."""

    def generate(
        self,
        db: Session,
        settings: Settings,
        *,
        filters: ApprovalPacketFilters | None = None,
        commit: bool = True,
    ) -> ApprovalPacketRunResult:
        halt_before = read_operator_halt(db)
        generated_at = datetime.now(tz=UTC)
        selected = filters or ApprovalPacketFilters()
        _validate_filters(selected)
        plans = _load_plans(db, selected)
        payload = _sanitized_snapshot(plans, selected, settings, halt_before)
        fingerprint = _fingerprint(payload)
        existing = db.scalar(
            select(ApprovalPacketRun).where(ApprovalPacketRun.snapshot_fingerprint == fingerprint)
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
                "approval_packet_run_reused",
                approval_packet_run_id=str(existing.id),
                packet_count=existing.packet_count,
                snapshot_fingerprint=fingerprint,
                executed_count=0,
                outbound_attempted=False,
            )
            return result

        drafts = [_build_packet(plan, settings, halt_before, generated_at) for plan in plans]
        run = ApprovalPacketRun(
            status=ApprovalPacketRunStatus.COMPLETED.value,
            model_version=APPROVAL_PACKET_MODEL_VERSION,
            snapshot_fingerprint=fingerprint,
            packet_count=len(drafts),
            reused_count=0,
            missing_plan_count=0 if plans else 1 if selected.execution_plan_id else 0,
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
                "plan_type": selected.plan_type,
                "execution_plan_id": (
                    str(selected.execution_plan_id) if selected.execution_plan_id else None
                ),
            },
            snapshot_json=payload,
            started_at=generated_at,
            finished_at=generated_at,
        )
        db.add(run)
        db.flush()
        for draft in drafts:
            db.add(_packet_row(run.id, draft))
        db.add(
            Activity(
                lead_id=None,
                actor=APPROVAL_PACKET_ACTOR,
                action="approval_packets_generated",
                details={
                    "approval_packet_run_id": str(run.id),
                    "packet_count": len(drafts),
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
            raise RuntimeError("approval packet generation must not change operator halt status")
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
            "approval_packet_run_completed",
            approval_packet_run_id=str(run.id),
            packet_count=len(drafts),
            snapshot_fingerprint=fingerprint,
            executed_count=0,
            outbound_attempted=False,
        )
        return result

    def latest(self, db: Session) -> ApprovalPacketRunResult | None:
        run = db.scalars(
            select(ApprovalPacketRun).order_by(ApprovalPacketRun.created_at.desc())
        ).first()
        if run is None:
            return None
        halt = read_operator_halt(db)
        return self._view(db, run, halt_before=halt, halt_after=halt, reused=True)

    def get_packet(self, db: Session, packet_id: UUID) -> ApprovalPacketView | None:
        """Return one stored owner approval packet without generating a new run.

        Read-only. Does not execute the underlying plan or change halt state.
        """

        row = db.get(OwnerApprovalPacket, packet_id)
        if row is None:
            return None
        decision = db.scalar(
            select(OwnerApprovalPacketDecision).where(
                OwnerApprovalPacketDecision.owner_approval_packet_id == packet_id
            )
        )
        return _packet_view(row, decision)

    def record_decision(
        self,
        db: Session,
        *,
        packet_id: UUID,
        decision: str,
        reviewer: str | None = None,
        source: str = "operator_ui",
        reviewer_notes: str | None = None,
        commit: bool = True,
    ) -> ApprovalPacketDecisionResult:
        """Persist an owner/operator decision record for one packet.

        Decision-record only. Does not execute the packet, mutate live
        owner-approved state, or change operator halt.
        """

        halt_before = read_operator_halt(db)
        packet = db.get(OwnerApprovalPacket, packet_id)
        if packet is None:
            raise ApprovalPacketError("packet_not_found", "Approval packet not found")
        parsed_decision = _parse_decision(decision)
        notes = sanitize_operator_text(_clip_notes(reviewer_notes))
        reviewer_name = sanitize_operator_text(reviewer) or "operator"
        source_name = sanitize_operator_text(source) or "operator_ui"
        decided_at = datetime.now(tz=UTC)
        existing = db.scalar(
            select(OwnerApprovalPacketDecision).where(
                OwnerApprovalPacketDecision.owner_approval_packet_id == packet_id
            )
        )
        previous = existing.decision if existing is not None else None
        audit = _decision_audit(
            packet,
            parsed_decision,
            reviewer_name,
            source_name,
            previous=previous,
        )
        if existing is None:
            row = OwnerApprovalPacketDecision(
                owner_approval_packet_id=packet_id,
                decision=parsed_decision.value,
                previous_decision=None,
                reviewer=reviewer_name,
                source=source_name,
                reviewer_notes=notes,
                decided_at=decided_at,
                executed=False,
                execution_attempted=False,
                outbound_attempted=False,
                live_call_attempted=False,
                recommendation_applied=False,
                spend_attempted=False,
                campaign_launched=False,
                pages_published=False,
                ads_launched=False,
                owner_approved=False,
                audit_json=audit,
            )
            db.add(row)
        else:
            existing.previous_decision = previous
            existing.decision = parsed_decision.value
            existing.reviewer = reviewer_name
            existing.source = source_name
            existing.reviewer_notes = notes
            existing.decided_at = decided_at
            existing.executed = False
            existing.execution_attempted = False
            existing.outbound_attempted = False
            existing.live_call_attempted = False
            existing.recommendation_applied = False
            existing.spend_attempted = False
            existing.campaign_launched = False
            existing.pages_published = False
            existing.ads_launched = False
            existing.owner_approved = False
            existing.audit_json = audit
            row = existing
        db.add(
            Activity(
                lead_id=None,
                actor=APPROVAL_PACKET_ACTOR,
                action=APPROVAL_PACKET_DECISION_ACTION,
                details={
                    "owner_approval_packet_id": str(packet_id),
                    "decision": parsed_decision.value,
                    "previous_decision": previous,
                    "reviewer": reviewer_name,
                    "source": source_name,
                    "executed": False,
                    "execution_attempted": False,
                    "outbound_attempted": False,
                    "live_call_attempted": False,
                    "recommendation_applied": False,
                    "spend_attempted": False,
                    "campaign_launched": False,
                    "pages_published": False,
                    "ads_launched": False,
                    "owner_approved": False,
                },
            )
        )
        db.flush()
        halt_after = read_operator_halt(db)
        if halt_after is not halt_before:
            raise RuntimeError("approval packet decision must not change operator halt status")
        if commit:
            db.commit()
            db.refresh(row)
        logger.info(
            "owner_approval_packet_decision_recorded",
            owner_approval_packet_id=str(packet_id),
            decision=parsed_decision.value,
            executed=False,
            owner_approved=False,
            outbound_attempted=False,
        )
        return ApprovalPacketDecisionResult(
            decision_id=row.id,
            packet_id=packet_id,
            decision=row.decision,
            reviewer=row.reviewer,
            source=row.source,
            reviewer_notes=row.reviewer_notes,
            decided_at=row.decided_at,
            executed=False,
            execution_attempted=False,
            outbound_attempted=False,
            live_call_attempted=False,
            recommendation_applied=False,
            spend_attempted=False,
            campaign_launched=False,
            pages_published=False,
            ads_launched=False,
            owner_approved=False,
            operator_halt_before=halt_before.value,
            operator_halt_after=halt_after.value,
        )

    def _view(
        self,
        db: Session,
        run: ApprovalPacketRun,
        *,
        halt_before: HaltStatus,
        halt_after: HaltStatus,
        reused: bool,
    ) -> ApprovalPacketRunResult:
        rows = list(
            db.scalars(
                select(OwnerApprovalPacket)
                .where(OwnerApprovalPacket.approval_packet_run_id == run.id)
                .order_by(
                    OwnerApprovalPacket.plan_family,
                    OwnerApprovalPacket.source_artifact_id,
                )
            )
        )
        decisions = _decision_map(db, [row.id for row in rows])
        return ApprovalPacketRunResult(
            approval_packet_run_id=run.id,
            status=ApprovalPacketRunStatus(run.status),
            model_version=run.model_version,
            snapshot_fingerprint=run.snapshot_fingerprint,
            packet_count=run.packet_count,
            reused_existing=reused,
            reused_count=run.reused_count if reused else 0,
            missing_plan_count=run.missing_plan_count,
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
            packets=tuple(_packet_view(row, decisions.get(row.id)) for row in rows),
        )


def _parse_decision(value: str) -> ReviewDecisionStatus:
    try:
        return ReviewDecisionStatus(value.strip())
    except ValueError as exc:
        raise ApprovalPacketError(
            "invalid_decision",
            "Decision must be approved, rejected, or needs_changes",
        ) from exc


def _clip_notes(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    return cleaned[:MAX_NOTES_LENGTH]


def _decision_map(
    db: Session,
    packet_ids: Sequence[UUID],
) -> dict[UUID, OwnerApprovalPacketDecision]:
    if not packet_ids:
        return {}
    rows = db.scalars(
        select(OwnerApprovalPacketDecision).where(
            OwnerApprovalPacketDecision.owner_approval_packet_id.in_(packet_ids)
        )
    ).all()
    return {row.owner_approval_packet_id: row for row in rows}


def _decision_view(row: OwnerApprovalPacketDecision) -> ApprovalPacketDecisionView:
    return ApprovalPacketDecisionView(
        decision_id=row.id,
        decision=row.decision,
        reviewer=row.reviewer,
        source=row.source,
        reviewer_notes=row.reviewer_notes,
        decided_at=row.decided_at,
    )


def _decision_audit(
    packet: OwnerApprovalPacket,
    decision: ReviewDecisionStatus,
    reviewer: str,
    source: str,
    *,
    previous: str | None = None,
) -> dict[str, object]:
    return {
        "owner_approval_packet_id": str(packet.id),
        "plan_family": packet.plan_family,
        "decision": decision.value,
        "previous_decision": previous,
        "reviewer": reviewer,
        "source": source,
        "dry_run_only": True,
        "no_execution": True,
        "executed": False,
        "execution_attempted": False,
        "outbound_attempted": False,
        "live_call_attempted": False,
        "recommendation_applied": False,
        "spend_attempted": False,
        "campaign_launched": False,
        "pages_published": False,
        "ads_launched": False,
        "owner_approved": False,
        "decision_record_only": True,
        "secrets_exposed": False,
    }


def _validate_filters(filters: ApprovalPacketFilters) -> None:
    if filters.plan_type is None or not filters.plan_type.strip():
        return
    if filters.plan_type.strip() not in SUPPORTED_PLAN_FAMILIES:
        raise ApprovalPacketError("unknown_plan_type", "Unknown execution plan family")


def _load_plans(db: Session, filters: ApprovalPacketFilters) -> tuple[ExecutionPlan, ...]:
    stmt = select(ExecutionPlan).order_by(
        ExecutionPlan.plan_type, ExecutionPlan.source_artifact_id
    )
    if filters.plan_type:
        stmt = stmt.where(ExecutionPlan.plan_type == filters.plan_type.strip())
    if filters.execution_plan_id is not None:
        stmt = stmt.where(ExecutionPlan.id == filters.execution_plan_id)
    rows = list(db.scalars(stmt))
    return tuple(row for row in rows if row.plan_type in SUPPORTED_PLAN_FAMILIES)


@dataclass(frozen=True)
class _DraftPacket:
    source_execution_plan_id: UUID
    source_execution_plan_run_id: UUID
    source_artifact_type: str
    source_artifact_id: UUID
    plan_family: str
    proposed_action: str
    preflight_status: str
    generated_at: datetime
    idempotency_key: str
    preflight_checklist: tuple[dict[str, object], ...]
    missing_prerequisites: tuple[dict[str, object], ...]
    findings: tuple[dict[str, object], ...]
    required_owner_decisions: tuple[str, ...]
    audit_json: dict[str, object]


def _build_packet(
    plan: ExecutionPlan,
    settings: Settings,
    halt: HaltStatus,
    generated_at: datetime,
) -> _DraftPacket:
    proposed = sanitize_operator_text(plan.proposed_action) or "Prepare later owner-approved action"
    if proposed == "[REDACTED_UNSAFE_TEXT]":
        proposed = "Prepare later owner-approved action"
    checklist = _preflight_checklist(plan, settings, halt)
    missing = tuple(item for item in checklist if item.get("met") is False)
    findings = _findings(plan, settings, halt, missing)
    decisions = _owner_decisions(plan)
    payload = {
        "model_version": APPROVAL_PACKET_MODEL_VERSION,
        "source_execution_plan_id": str(plan.id),
        "source_execution_plan_run_id": str(plan.execution_plan_run_id),
        "source_artifact_type": plan.source_artifact_type,
        "source_artifact_id": str(plan.source_artifact_id),
        "plan_family": plan.plan_type,
        "safety": _safety_snapshot(settings, halt),
    }
    return _DraftPacket(
        source_execution_plan_id=plan.id,
        source_execution_plan_run_id=plan.execution_plan_run_id,
        source_artifact_type=plan.source_artifact_type,
        source_artifact_id=plan.source_artifact_id,
        plan_family=plan.plan_type,
        proposed_action=proposed,
        preflight_status=PreflightStatus.BLOCKED.value,
        generated_at=generated_at,
        idempotency_key=_fingerprint(payload),
        preflight_checklist=checklist,
        missing_prerequisites=missing,
        findings=findings,
        required_owner_decisions=decisions,
        audit_json={
            "dry_run_only": True,
            "no_execution": True,
            "executed": False,
            "execution_attempted": False,
            "outbound_attempted": False,
            "owner_approval_required": True,
            "owner_approved": False,
            "secrets_exposed": False,
        },
    )


def _preflight_checklist(
    plan: ExecutionPlan,
    settings: Settings,
    halt: HaltStatus,
) -> tuple[dict[str, object], ...]:
    credentials = credential_presence_flags(settings)
    items: list[dict[str, object]] = [
        {
            "code": "execution_plan_present",
            "label": "Source dry-run execution plan is present",
            "met": True,
        },
        {
            "code": "execution_plan_dry_run",
            "label": "Source execution plan remains dry-run / no-execution",
            "met": bool(plan.dry_run_only and plan.no_execution),
        },
        {
            "code": "execution_plan_not_executed",
            "label": "Source execution plan has not been executed",
            "met": not bool(plan.executed or plan.execution_attempted),
        },
        {
            "code": "owner_live_action_approval",
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
            "met": halt is not HaltStatus.CLEARED,
        },
        {
            "code": "live_provider_flags_disabled",
            "label": "Live provider flags remain disabled",
            "met": not any_live_provider_enabled(settings),
        },
        {
            "code": "internal_api_key_presence",
            "label": "INTERNAL_API_KEY is configured",
            "met": credentials["internal_api_key"],
            "present": credentials["internal_api_key"],
        },
    ]
    for name, enabled in live_provider_flags(settings).items():
        items.append(
            {
                "code": f"live_flag_{name}_disabled",
                "label": f"Live flag {name} remains disabled",
                "met": not enabled,
            }
        )
    for code in FAMILY_CREDENTIALS.get(plan.plan_type, ()):
        present = credentials.get(code, False)
        items.append(
            {
                "code": f"{code}_configured",
                "label": CREDENTIAL_LABELS.get(code, "Required credential is configured"),
                "met": present,
                "present": present,
            }
        )
    for prerequisite in _plan_prerequisites(plan):
        items.append(prerequisite)
    return tuple(items)


def _plan_prerequisites(plan: ExecutionPlan) -> tuple[dict[str, object], ...]:
    raw = plan.prerequisites_json
    if not isinstance(raw, list):
        return ()
    items: list[dict[str, object]] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        code = entry.get("code")
        label = entry.get("label")
        if not isinstance(code, str) or not isinstance(label, str):
            continue
        cleaned = sanitize_operator_text(label) or label
        if cleaned == "[REDACTED_UNSAFE_TEXT]":
            continue
        items.append(
            {
                "code": f"plan_{code}",
                "label": cleaned,
                "met": bool(entry.get("met")),
            }
        )
    return tuple(items)


def _findings(
    plan: ExecutionPlan,
    settings: Settings,
    halt: HaltStatus,
    missing: Sequence[dict[str, object]],
) -> tuple[dict[str, object], ...]:
    items: list[dict[str, object]] = [
        {
            "severity": FindingSeverity.BLOCKED.value,
            "code": ALWAYS_BLOCKED_CODE,
            "message": "Phase 18 records an approval packet only and does not execute",
        },
        {
            "severity": FindingSeverity.BLOCKED.value,
            "code": "owner_decision_required",
            "message": "A separate owner decision is required before any future live action",
        },
    ]
    if not settings.outbound_enabled:
        items.append(
            {
                "severity": FindingSeverity.BLOCKED.value,
                "code": "outbound_disabled",
                "message": "OUTBOUND_ENABLED is false; live outbound remains blocked",
            }
        )
    else:
        items.append(
            {
                "severity": FindingSeverity.BLOCKED.value,
                "code": "outbound_enabled",
                "message": "OUTBOUND_ENABLED is true. Do not treat this as dry-run-only.",
            }
        )
    if halt is HaltStatus.HALTED:
        items.append(
            {
                "severity": FindingSeverity.INFO.value,
                "code": "operator_halt_active",
                "message": "Persistent operator halt is active",
            }
        )
    elif halt is HaltStatus.UNAVAILABLE:
        items.append(
            {
                "severity": FindingSeverity.WARNING.value,
                "code": "operator_halt_unavailable",
                "message": "Persistent operator halt is missing or unreadable (fail-closed)",
            }
        )
    if not any_live_provider_enabled(settings):
        items.append(
            {
                "severity": FindingSeverity.INFO.value,
                "code": "live_providers_disabled",
                "message": "Live provider flags remain disabled",
            }
        )
    else:
        items.append(
            {
                "severity": FindingSeverity.BLOCKED.value,
                "code": "live_providers_enabled",
                "message": "One or more live provider flags are enabled",
            }
        )
    credential_missing = [
        item
        for item in missing
        if isinstance(item.get("code"), str)
        and str(item["code"]).endswith("_configured")
        and item.get("present") is False
    ]
    if credential_missing:
        items.append(
            {
                "severity": FindingSeverity.WARNING.value,
                "code": "required_credential_absent",
                "message": (
                    "A later live action would still need a configured credential. "
                    "The credential value is not stored in this packet."
                ),
            }
        )
    items.append(
        {
            "severity": FindingSeverity.INFO.value,
            "code": "plan_family_preflight",
            "message": f"Preflight inspected plan family {plan.plan_type} from local config only",
        }
    )
    return tuple(items)


def _owner_decisions(plan: ExecutionPlan) -> tuple[str, ...]:
    from_plan = _string_tuple(plan.required_owner_approvals_json)
    extras = FAMILY_OWNER_DECISIONS.get(plan.plan_type, ())
    combined = [
        "Owner approval of this live-readiness packet before any future live action",
        *from_plan,
        *extras,
    ]
    seen: set[str] = set()
    ordered: list[str] = []
    for item in combined:
        if item in seen:
            continue
        seen.add(item)
        ordered.append(item)
    return tuple(ordered)


def _safety_snapshot(settings: Settings, halt: HaltStatus) -> dict[str, object]:
    return {
        "outbound_enabled": settings.outbound_enabled,
        "operator_halt_status": halt.value,
        "live_providers": live_provider_flags(settings),
        "credentials_configured": credential_presence_flags(settings),
        "dry_run_only": True,
        "no_execution": True,
        "secrets_exposed": False,
    }


def _sanitized_snapshot(
    plans: Sequence[ExecutionPlan],
    filters: ApprovalPacketFilters,
    settings: Settings,
    halt: HaltStatus,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "model_version": APPROVAL_PACKET_MODEL_VERSION,
        "filters": {
            "plan_type": filters.plan_type,
            "execution_plan_id": (
                str(filters.execution_plan_id) if filters.execution_plan_id else None
            ),
        },
        "plans": [
            {
                "execution_plan_id": str(plan.id),
                "execution_plan_run_id": str(plan.execution_plan_run_id),
                "plan_type": plan.plan_type,
                "source_artifact_type": plan.source_artifact_type,
                "source_artifact_id": str(plan.source_artifact_id),
                "dry_run_only": True,
                "no_execution": True,
                "executed": False,
            }
            for plan in plans
        ],
        "safety": _safety_snapshot(settings, halt),
    }
    sanitized = _json_safe(payload)
    if not isinstance(sanitized, dict):
        raise TypeError("approval packet snapshot must be an object")
    return {str(key): value for key, value in sanitized.items()}


def _packet_row(run_id: UUID, draft: _DraftPacket) -> OwnerApprovalPacket:
    return OwnerApprovalPacket(
        approval_packet_run_id=run_id,
        source_execution_plan_id=draft.source_execution_plan_id,
        source_execution_plan_run_id=draft.source_execution_plan_run_id,
        source_artifact_type=draft.source_artifact_type,
        source_artifact_id=draft.source_artifact_id,
        plan_family=draft.plan_family,
        proposed_action=draft.proposed_action,
        preflight_status=draft.preflight_status,
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
        preflight_checklist_json=list(draft.preflight_checklist),
        missing_prerequisites_json=list(draft.missing_prerequisites),
        findings_json=list(draft.findings),
        required_owner_decisions_json=list(draft.required_owner_decisions),
        audit_json=draft.audit_json,
    )


def _packet_view(
    row: OwnerApprovalPacket,
    decision_row: OwnerApprovalPacketDecision | None = None,
) -> ApprovalPacketView:
    return ApprovalPacketView(
        id=row.id,
        source_execution_plan_id=row.source_execution_plan_id,
        source_execution_plan_run_id=row.source_execution_plan_run_id,
        source_artifact_type=row.source_artifact_type,
        source_artifact_id=row.source_artifact_id,
        plan_family=row.plan_family,
        proposed_action=row.proposed_action,
        preflight_status=row.preflight_status,
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
        preflight_checklist=_object_tuple(row.preflight_checklist_json),
        missing_prerequisites=_object_tuple(row.missing_prerequisites_json),
        findings=_object_tuple(row.findings_json),
        required_owner_decisions=_string_tuple(row.required_owner_decisions_json),
        decision=_decision_view(decision_row) if decision_row is not None else None,
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
