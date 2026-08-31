"""Read-only approved action readiness queue.

Phase 24 combines stored review decisions, dry-run execution plans, owner
approval packets, and packet decision records. It never generates new
pipeline artifacts and never executes an approved item or packet.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Never
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from vyro_growth.config import Settings
from vyro_growth.domain import (
    ActionDecisionStatus,
    ActionReadinessBlockerStatus,
    ActionReadinessStatus,
    ExecutionPlanType,
    PreflightStatus,
    ReviewDecisionStatus,
)
from vyro_growth.models import (
    ExecutionPlan,
    OperatorReviewDecision,
    OwnerApprovalPacket,
    OwnerApprovalPacketDecision,
)
from vyro_growth.observability import sanitize_operator_text
from vyro_growth.services.operator_halt import HaltStatus, read_operator_halt

logger = structlog.get_logger(__name__)

ALWAYS_BLOCKED_CODE = "execution_disabled_in_this_phase"
LIVE_OWNER_ACTION_CODE = "live_action_requires_explicit_owner_action"
LIVE_OWNER_APPROVED_UNSET_CODE = "live_owner_approved_unset"
OUTBOUND_DISABLED_CODE = "outbound_disabled"
OPERATOR_HALT_CODE = "operator_halt_active"
MISSING_REVIEW_CODE = "missing_review_decision"
MISSING_PACKET_DECISION_CODE = "missing_owner_packet_decision"
MISSING_PACKET_CODE = "missing_approval_packet"
MISSING_PLAN_CODE = "missing_execution_plan"
PREFLIGHT_BLOCKED_CODE = "preflight_blocked"
REVIEW_NOT_APPROVED_CODE = "review_decision_not_approved"
PACKET_NOT_APPROVED_CODE = "packet_decision_not_approved"
FALLBACK_LABEL = "Sanitized dry-run action"
CODE_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
PLAN_FAMILIES: frozenset[str] = frozenset(item.value for item in ExecutionPlanType)
READINESS_STATUSES: frozenset[str] = frozenset(item.value for item in ActionReadinessStatus)
BLOCKER_STATUSES: frozenset[str] = frozenset(item.value for item in ActionReadinessBlockerStatus)
DECISION_STATUSES: frozenset[str] = frozenset(item.value for item in ActionDecisionStatus)


@dataclass(frozen=True)
class ActionReadinessCandidate:
    candidate_id: UUID
    artifact_type: str
    artifact_id: UUID
    plan_family: str
    sanitized_label: str
    review_decision_status: str
    packet_decision_status: str
    preflight_status: str
    readiness_status: str
    blocker_status: str
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
    owner_approved: bool
    live_action: bool
    explicit_live_owner_action_required: bool
    generated_at: datetime
    execution_plan_id: UUID | None
    approval_packet_id: UUID | None
    review_decision_id: UUID | None
    packet_decision_id: UUID | None
    blocker_codes: tuple[str, ...]
    missing_approval_codes: tuple[str, ...]
    missing_prerequisite_codes: tuple[str, ...]


@dataclass(frozen=True)
class ActionReadinessResult:
    generated_at: datetime
    candidate_count: int
    by_readiness_status: dict[str, int]
    by_plan_family: dict[str, int]
    by_blocker_status: dict[str, int]
    by_decision_status: dict[str, int]
    dry_run_only: bool
    no_execution: bool
    executed_count: int
    execution_attempted: bool
    outbound_attempted: bool
    live_call_attempted: bool
    recommendation_applied: bool
    spend_attempted: bool
    campaign_launched: bool
    pages_published: bool
    ads_launched: bool
    live_action: bool
    read_only: bool
    explicit_live_owner_action_required: bool
    operator_halt_status: str
    operator_halt_before: str
    operator_halt_after: str
    candidates: tuple[ActionReadinessCandidate, ...]


@dataclass(frozen=True)
class ActionReadinessFilters:
    plan_family: str | None = None
    readiness_status: str | None = None
    blocker_status: str | None = None
    decision_status: str | None = None


class ActionReadinessService:
    """Join stored review, plan, and packet records into a read-only queue."""

    def list_queue(
        self,
        db: Session,
        settings: Settings,
        *,
        filters: ActionReadinessFilters | None = None,
    ) -> ActionReadinessResult:
        halt_before = read_operator_halt(db)
        selected = _parse_filters(filters)
        generated_at = datetime.now(tz=UTC)
        candidates = _collect_candidates(db, settings, halt_before)
        visible = tuple(
            item for item in candidates if _matches_filters(item, selected)
        )
        halt_after = read_operator_halt(db)
        if halt_after is not halt_before:
            raise RuntimeError("action readiness listing must not change operator halt status")
        result = ActionReadinessResult(
            generated_at=generated_at,
            candidate_count=len(visible),
            by_readiness_status=_count_by(visible, lambda item: item.readiness_status),
            by_plan_family=_count_by(visible, lambda item: item.plan_family),
            by_blocker_status=_count_by(visible, lambda item: item.blocker_status),
            by_decision_status=_count_by(visible, lambda item: item.review_decision_status),
            dry_run_only=True,
            no_execution=True,
            executed_count=0,
            execution_attempted=False,
            outbound_attempted=False,
            live_call_attempted=False,
            recommendation_applied=False,
            spend_attempted=False,
            campaign_launched=False,
            pages_published=False,
            ads_launched=False,
            live_action=False,
            read_only=True,
            explicit_live_owner_action_required=True,
            operator_halt_status=halt_after.value,
            operator_halt_before=halt_before.value,
            operator_halt_after=halt_after.value,
            candidates=visible,
        )
        logger.info(
            "action_readiness_listed",
            candidate_count=result.candidate_count,
            read_only=True,
            executed_count=0,
            outbound_attempted=False,
            live_action=False,
        )
        return result

    def get_candidate(
        self,
        db: Session,
        settings: Settings,
        candidate_id: UUID,
    ) -> ActionReadinessCandidate | None:
        result = self.list_queue(db, settings)
        for item in result.candidates:
            if item.candidate_id == candidate_id:
                return item
        return None


def _parse_filters(filters: ActionReadinessFilters | None) -> ActionReadinessFilters:
    selected = filters or ActionReadinessFilters()
    return ActionReadinessFilters(
        plan_family=_allowed_or_none(selected.plan_family, PLAN_FAMILIES),
        readiness_status=_allowed_or_none(selected.readiness_status, READINESS_STATUSES),
        blocker_status=_allowed_or_none(selected.blocker_status, BLOCKER_STATUSES),
        decision_status=_allowed_or_none(selected.decision_status, DECISION_STATUSES),
    )


def _allowed_or_none(value: str | None, allowed: frozenset[str]) -> str | None:
    if value is None or not value.strip():
        return None
    cleaned = value.strip()
    if cleaned in allowed:
        return cleaned
    return None


def _matches_filters(item: ActionReadinessCandidate, filters: ActionReadinessFilters) -> bool:
    if filters.plan_family is not None and item.plan_family != filters.plan_family:
        return False
    if (
        filters.readiness_status is not None
        and item.readiness_status != filters.readiness_status
    ):
        return False
    if filters.blocker_status is not None and item.blocker_status != filters.blocker_status:
        return False
    if (
        filters.decision_status is not None
        and item.review_decision_status != filters.decision_status
    ):
        return False
    return True


def _collect_candidates(
    db: Session,
    settings: Settings,
    halt: HaltStatus,
) -> tuple[ActionReadinessCandidate, ...]:
    plans = _latest_plans(db)
    packets = _latest_packets(db)
    decisions = _review_decision_map(db)
    packet_decisions = _packet_decision_map(db, tuple(item.id for item in packets.values()))
    used_packet_ids: set[UUID] = set()
    candidates: list[ActionReadinessCandidate] = []
    for key, plan in plans.items():
        packet = _packet_for_plan(plan, packets)
        if packet is not None:
            used_packet_ids.add(packet.id)
        candidates.append(
            _to_candidate(
                settings,
                halt,
                plan=plan,
                packet=packet,
                review=decisions.get(key),
                packet_decision=(
                    packet_decisions.get(packet.id) if packet is not None else None
                ),
            )
        )
    for key, packet in packets.items():
        if packet.id in used_packet_ids:
            continue
        candidates.append(
            _to_candidate(
                settings,
                halt,
                plan=None,
                packet=packet,
                review=decisions.get(key),
                packet_decision=packet_decisions.get(packet.id),
            )
        )
    candidates.sort(
        key=lambda item: (
            item.plan_family,
            item.artifact_type,
            str(item.artifact_id),
        )
    )
    return tuple(candidates)


def _latest_plans(db: Session) -> dict[tuple[str, UUID], ExecutionPlan]:
    rows = db.scalars(
        select(ExecutionPlan).order_by(ExecutionPlan.generated_at.desc(), ExecutionPlan.id.desc())
    ).all()
    latest: dict[tuple[str, UUID], ExecutionPlan] = {}
    for row in rows:
        key = (row.source_artifact_type, row.source_artifact_id)
        if key not in latest:
            latest[key] = row
    return latest


def _latest_packets(db: Session) -> dict[tuple[str, UUID], OwnerApprovalPacket]:
    rows = db.scalars(
        select(OwnerApprovalPacket).order_by(
            OwnerApprovalPacket.generated_at.desc(),
            OwnerApprovalPacket.id.desc(),
        )
    ).all()
    latest: dict[tuple[str, UUID], OwnerApprovalPacket] = {}
    for row in rows:
        key = (row.source_artifact_type, row.source_artifact_id)
        if key not in latest:
            latest[key] = row
    return latest


def _packet_for_plan(
    plan: ExecutionPlan,
    packets: Mapping[tuple[str, UUID], OwnerApprovalPacket],
) -> OwnerApprovalPacket | None:
    key = (plan.source_artifact_type, plan.source_artifact_id)
    packet = packets.get(key)
    if packet is not None and packet.source_execution_plan_id == plan.id:
        return packet
    if packet is not None:
        return packet
    for item in packets.values():
        if item.source_execution_plan_id == plan.id:
            return item
    return None


def _review_decision_map(
    db: Session,
) -> dict[tuple[str, UUID], OperatorReviewDecision]:
    rows = db.scalars(select(OperatorReviewDecision)).all()
    return {(row.artifact_type, row.artifact_id): row for row in rows}


def _packet_decision_map(
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


def _to_candidate(
    settings: Settings,
    halt: HaltStatus,
    *,
    plan: ExecutionPlan | None,
    packet: OwnerApprovalPacket | None,
    review: OperatorReviewDecision | None,
    packet_decision: OwnerApprovalPacketDecision | None,
) -> ActionReadinessCandidate:
    artifact_type = _safe_code(
        (plan.source_artifact_type if plan is not None else None)
        or (packet.source_artifact_type if packet is not None else None)
        or "unknown"
    ) or "unknown"
    artifact_id = (
        plan.source_artifact_id
        if plan is not None
        else packet.source_artifact_id if packet is not None else UUID(int=0)
    )
    plan_family = _safe_code(
        (plan.plan_type if plan is not None else None)
        or (packet.plan_family if packet is not None else None)
        or ExecutionPlanType.PERSONALIZATION_DRAFT.value
    ) or ExecutionPlanType.PERSONALIZATION_DRAFT.value
    candidate_id = plan.id if plan is not None else packet.id if packet is not None else artifact_id
    review_status = _decision_status(review.decision if review is not None else None)
    packet_status = _decision_status(
        packet_decision.decision if packet_decision is not None else None
    )
    preflight = _preflight_status(packet.preflight_status if packet is not None else None)
    readiness = _readiness_status(
        review_status=review_status,
        packet_status=packet_status,
        preflight=preflight,
        halt=halt,
    )
    blocker_codes, missing_approval, missing_prereq = _blocker_sets(
        settings,
        halt,
        plan=plan,
        packet=packet,
        review_status=review_status,
        packet_status=packet_status,
        preflight=preflight,
    )
    blocker_status = (
        ActionReadinessBlockerStatus.PHASE_SAFETY_ONLY.value
        if readiness is ActionReadinessStatus.READY_PENDING_EXPLICIT_LIVE_OWNER_ACTION
        else ActionReadinessBlockerStatus.BLOCKED.value
    )
    generated_at = _generated_at(plan, packet, review, packet_decision)
    return ActionReadinessCandidate(
        candidate_id=candidate_id,
        artifact_type=artifact_type,
        artifact_id=artifact_id,
        plan_family=plan_family,
        sanitized_label=_sanitized_label(plan, packet),
        review_decision_status=review_status.value,
        packet_decision_status=packet_status.value,
        preflight_status=preflight,
        readiness_status=readiness.value,
        blocker_status=blocker_status,
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
        owner_approved=False,
        live_action=False,
        explicit_live_owner_action_required=True,
        generated_at=generated_at,
        execution_plan_id=plan.id if plan is not None else None,
        approval_packet_id=packet.id if packet is not None else None,
        review_decision_id=review.id if review is not None else None,
        packet_decision_id=packet_decision.id if packet_decision is not None else None,
        blocker_codes=blocker_codes,
        missing_approval_codes=missing_approval,
        missing_prerequisite_codes=missing_prereq,
    )


def _readiness_status(
    *,
    review_status: ActionDecisionStatus,
    packet_status: ActionDecisionStatus,
    preflight: str,
    halt: HaltStatus,
) -> ActionReadinessStatus:
    if review_status is ActionDecisionStatus.MISSING:
        return ActionReadinessStatus.MISSING_REVIEW_DECISION
    if review_status is not ActionDecisionStatus.APPROVED:
        return ActionReadinessStatus.BLOCKED
    if packet_status is ActionDecisionStatus.MISSING:
        return ActionReadinessStatus.MISSING_OWNER_PACKET_DECISION
    if packet_status is not ActionDecisionStatus.APPROVED:
        return ActionReadinessStatus.BLOCKED
    if preflight != PreflightStatus.AWAITING_OWNER_DECISION.value:
        return ActionReadinessStatus.PREFLIGHT_BLOCKED
    if halt is HaltStatus.HALTED or halt is HaltStatus.UNAVAILABLE:
        return ActionReadinessStatus.APPROVED_BUT_HALTED
    if halt is HaltStatus.CLEARED:
        return ActionReadinessStatus.READY_PENDING_EXPLICIT_LIVE_OWNER_ACTION
    return _unreachable_halt(halt)


def _blocker_sets(
    settings: Settings,
    halt: HaltStatus,
    *,
    plan: ExecutionPlan | None,
    packet: OwnerApprovalPacket | None,
    review_status: ActionDecisionStatus,
    packet_status: ActionDecisionStatus,
    preflight: str,
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    blockers: list[str] = [
        ALWAYS_BLOCKED_CODE,
        LIVE_OWNER_ACTION_CODE,
        LIVE_OWNER_APPROVED_UNSET_CODE,
    ]
    missing_approval: list[str] = []
    if not settings.outbound_enabled:
        blockers.append(OUTBOUND_DISABLED_CODE)
    if halt is HaltStatus.HALTED or halt is HaltStatus.UNAVAILABLE:
        blockers.append(OPERATOR_HALT_CODE)
    if plan is None:
        blockers.append(MISSING_PLAN_CODE)
        missing_approval.append(MISSING_PLAN_CODE)
    if packet is None:
        blockers.append(MISSING_PACKET_CODE)
        missing_approval.append(MISSING_PACKET_CODE)
    if review_status is ActionDecisionStatus.MISSING:
        blockers.append(MISSING_REVIEW_CODE)
        missing_approval.append(MISSING_REVIEW_CODE)
    elif review_status is not ActionDecisionStatus.APPROVED:
        blockers.append(REVIEW_NOT_APPROVED_CODE)
        missing_approval.append(REVIEW_NOT_APPROVED_CODE)
    if packet_status is ActionDecisionStatus.MISSING:
        blockers.append(MISSING_PACKET_DECISION_CODE)
        missing_approval.append(MISSING_PACKET_DECISION_CODE)
    elif packet_status is not ActionDecisionStatus.APPROVED:
        blockers.append(PACKET_NOT_APPROVED_CODE)
        missing_approval.append(PACKET_NOT_APPROVED_CODE)
    if preflight == PreflightStatus.BLOCKED.value:
        blockers.append(PREFLIGHT_BLOCKED_CODE)
    if plan is not None:
        blockers.extend(_codes_from_objects(plan.blockers_json))
    if packet is not None:
        blockers.extend(_blocked_finding_codes(packet.findings_json))
    missing_prereq = _unmet_codes(
        packet.missing_prerequisites_json if packet is not None else None
    )
    if packet is not None:
        missing_prereq = _merge_codes(
            missing_prereq,
            _unmet_codes(packet.preflight_checklist_json),
        )
    if plan is not None:
        missing_prereq = _merge_codes(missing_prereq, _unmet_codes(plan.prerequisites_json))
    return _unique_codes(blockers), _unique_codes(missing_approval), missing_prereq


def _decision_status(value: str | None) -> ActionDecisionStatus:
    if value is None or not value.strip():
        return ActionDecisionStatus.MISSING
    cleaned = value.strip()
    match cleaned:
        case ReviewDecisionStatus.APPROVED.value:
            return ActionDecisionStatus.APPROVED
        case ReviewDecisionStatus.REJECTED.value:
            return ActionDecisionStatus.REJECTED
        case ReviewDecisionStatus.NEEDS_CHANGES.value:
            return ActionDecisionStatus.NEEDS_CHANGES
        case _:
            return ActionDecisionStatus.MISSING


def _preflight_status(value: str | None) -> str:
    if value is None or not value.strip():
        return "missing"
    cleaned = value.strip()
    try:
        return PreflightStatus(cleaned).value
    except ValueError:
        return "missing"


def _sanitized_label(plan: ExecutionPlan | None, packet: OwnerApprovalPacket | None) -> str:
    raw = None
    if packet is not None:
        raw = packet.proposed_action
    elif plan is not None:
        raw = plan.proposed_action
    cleaned = sanitize_operator_text(raw) if raw else None
    if cleaned is None or cleaned == "" or cleaned.startswith("[REDACTED"):
        return FALLBACK_LABEL
    return cleaned


def _generated_at(
    plan: ExecutionPlan | None,
    packet: OwnerApprovalPacket | None,
    review: OperatorReviewDecision | None,
    packet_decision: OwnerApprovalPacketDecision | None,
) -> datetime:
    stamps = [
        item
        for item in (
            packet.generated_at if packet is not None else None,
            plan.generated_at if plan is not None else None,
            packet_decision.decided_at if packet_decision is not None else None,
            review.decided_at if review is not None else None,
        )
        if item is not None
    ]
    if stamps:
        return max(stamps)
    return datetime.now(tz=UTC)


def _codes_from_objects(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    codes: list[str] = []
    for item in value:
        if isinstance(item, Mapping):
            code = _safe_code(item.get("code"))
            if code is not None:
                codes.append(code)
        elif isinstance(item, str):
            code = _safe_code(item)
            if code is not None:
                codes.append(code)
    return tuple(codes)


def _blocked_finding_codes(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    codes: list[str] = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        severity = str(item.get("severity") or "").strip().lower()
        if severity not in {"blocked", "warning"}:
            continue
        code = _safe_code(item.get("code"))
        if code is not None:
            codes.append(code)
    return tuple(codes)


def _unmet_codes(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    codes: list[str] = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        met = item.get("met")
        if met is True:
            continue
        code = _safe_code(item.get("code"))
        if code is not None:
            codes.append(code)
    return tuple(codes)


def _safe_code(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip().lower().replace("-", "_").replace(" ", "_")
    if not CODE_RE.fullmatch(text):
        return None
    return text


def _unique_codes(values: Sequence[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in values:
        if item in seen:
            continue
        seen.add(item)
        ordered.append(item)
    return tuple(ordered)


def _merge_codes(left: Sequence[str], right: Sequence[str]) -> tuple[str, ...]:
    return _unique_codes([*left, *right])


def _count_by(
    items: Sequence[ActionReadinessCandidate],
    key: Callable[[ActionReadinessCandidate], str],
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        value = str(key(item))
        counts[value] = counts.get(value, 0) + 1
    return counts


def _unreachable_halt(value: HaltStatus) -> Never:
    raise RuntimeError(f"unhandled operator halt status: {value!r}")
