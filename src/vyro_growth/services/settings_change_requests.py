"""Record-only live settings change request queue.

Phase 28 persists proposed setting names and desired booleans/statuses so the
owner can review what would need to change before live acquisition. It never
applies settings, lifts halt, executes packets, calls providers, or stores
secret values.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Never
from uuid import UUID

import structlog
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from vyro_growth.config import Settings
from vyro_growth.domain import (
    FindingCode,
    NextActionCode,
    SecretName,
    SettingsChangeDecisionStatus,
    SettingsChangeDesiredStatus,
    SettingsChangeRequestStatus,
    SettingsChangeRequestType,
)
from vyro_growth.models import (
    Activity,
    LiveSettingsChangeRequest,
    LiveSettingsChangeRequestDecision,
)
from vyro_growth.observability import sanitize_mapping, sanitize_operator_text
from vyro_growth.services.operator_halt import HaltStatus, read_operator_halt

logger = structlog.get_logger(__name__)

ACTOR = "settings_change_request"
CODE_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
SETTING_NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]{1,63}$")
IDEMPOTENCY_KEY_RE = re.compile(r"^[A-Za-z0-9:._-]{8,128}$")
LIVE_PROVIDER_FLAG_SETTINGS: frozenset[str] = frozenset(
    {
        "OPENAI_PERSONALIZATION_ENABLED",
        "SMARTLEAD_LIVE_ENABLED",
        "OPENAI_REPLY_CLASSIFICATION_ENABLED",
        "GOOGLE_CALENDAR_LIVE_ENABLED",
        "VOICE_LIVE_ENABLED",
        "DECISION_MAKER_LIVE_ENABLED",
        "EMAIL_VERIFICATION_LIVE_ENABLED",
    }
)
FLAG_SETTINGS: frozenset[str] = frozenset(
    {
        "OUTBOUND_ENABLED",
        *LIVE_PROVIDER_FLAG_SETTINGS,
        "OUTBOUND_HALTED",
        "OPERATOR_HALT",
    }
)
CREDENTIAL_SETTINGS: frozenset[str] = frozenset(item.value for item in SecretName)
ALLOWED_SETTINGS: frozenset[str] = FLAG_SETTINGS | CREDENTIAL_SETTINGS
HALT_SETTINGS: frozenset[str] = frozenset({"OPERATOR_HALT", "OUTBOUND_HALTED"})


class SettingsChangeRequestError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class SettingsChangeDecisionView:
    decision_id: UUID
    decision: str
    reviewer: str
    source: str
    reviewer_notes: str | None
    decided_at: datetime
    executed: bool
    settings_applied: bool
    owner_approved: bool
    halt_changed: bool
    live_action: bool
    no_execution: bool


@dataclass(frozen=True)
class SettingsChangeRequestView:
    request_id: UUID
    request_type: str
    status: str
    owner_decision_status: str
    idempotency_key: str
    requested_setting_names: tuple[str, ...]
    desired_boolean: bool | None
    desired_status: str | None
    finding_code: str | None
    next_action_code: str | None
    source: str
    reviewer_notes: str | None
    requested_at: datetime
    record_only: bool
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
    settings_applied: bool
    halt_changed: bool
    live_action: bool
    reused: bool
    operator_halt_status: str
    operator_halt_before: str
    operator_halt_after: str
    decision: SettingsChangeDecisionView | None


@dataclass(frozen=True)
class SettingsChangeRequestList:
    generated_at: datetime
    request_count: int
    pending_count: int
    decided_count: int
    by_request_type: dict[str, int]
    by_status: dict[str, int]
    by_decision_status: dict[str, int]
    record_only: bool
    no_execution: bool
    executed: int
    live_action: bool
    outbound_attempted: bool
    owner_approved: bool
    settings_applied: bool
    halt_changed: bool
    operator_halt_status: str
    operator_halt_before: str
    operator_halt_after: str
    requests: tuple[SettingsChangeRequestView, ...]


@dataclass(frozen=True)
class SettingsChangeProposeResult:
    created_count: int
    reused_count: int
    request_count: int
    record_only: bool
    no_execution: bool
    executed: int
    live_action: bool
    outbound_attempted: bool
    owner_approved: bool
    settings_applied: bool
    halt_changed: bool
    operator_halt_status: str
    operator_halt_before: str
    operator_halt_after: str
    requests: tuple[SettingsChangeRequestView, ...]


@dataclass(frozen=True)
class SettingsChangeProposal:
    request_type: str
    requested_setting_names: tuple[str, ...]
    desired_boolean: bool | None
    desired_status: str | None
    finding_code: str | None
    next_action_code: str | None
    record_only: bool = True
    no_execution: bool = True
    settings_applied: bool = False


class SettingsChangeRequestService:
    """Persist and list record-only live settings change requests."""

    def create(
        self,
        db: Session,
        settings: Settings,
        *,
        request_type: str,
        requested_setting_names: Sequence[str],
        desired_boolean: bool | None = None,
        desired_status: str | None = None,
        finding_code: str | None = None,
        next_action_code: str | None = None,
        idempotency_key: str | None = None,
        source: str = "cli",
        reviewer_notes: str | None = None,
        commit: bool = True,
    ) -> SettingsChangeRequestView:
        halt_before = read_operator_halt(db)
        parsed_type = _parse_request_type(request_type)
        setting_names = _parse_setting_names(requested_setting_names)
        desired_bool, desired_stat = _validate_desired_state(
            parsed_type,
            setting_names,
            desired_boolean=desired_boolean,
            desired_status=desired_status,
        )
        finding = _optional_code(finding_code, "finding_code")
        next_action = _optional_code(next_action_code, "next_action_code")
        notes = _sanitize_notes(reviewer_notes)
        source_name = sanitize_operator_text(source) or "cli"
        key = _idempotency_key(
            supplied=idempotency_key,
            request_type=parsed_type,
            setting_names=setting_names,
            desired_boolean=desired_bool,
            desired_status=desired_stat,
            finding_code=finding,
            next_action_code=next_action,
        )
        existing = db.scalar(
            select(LiveSettingsChangeRequest).where(
                LiveSettingsChangeRequest.idempotency_key == key
            )
        )
        if existing is not None:
            halt_after = _require_halt_unchanged(db, halt_before)
            logger.info(
                "settings_change_request_reused",
                request_id=str(existing.id),
                request_type=existing.request_type,
                reused=True,
                executed=False,
                settings_applied=False,
                live_action=False,
            )
            return _to_view(existing, halt_before, halt_after, reused=True)
        requested_at = datetime.now(tz=UTC)
        row = LiveSettingsChangeRequest(
            request_type=parsed_type.value,
            status=SettingsChangeRequestStatus.PENDING.value,
            owner_decision_status=SettingsChangeDecisionStatus.PENDING.value,
            idempotency_key=key,
            requested_setting_names=list(setting_names),
            desired_boolean=desired_bool,
            desired_status=desired_stat,
            finding_code=finding,
            next_action_code=next_action,
            source=source_name,
            reviewer_notes=notes,
            requested_at=requested_at,
            record_only=True,
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
            settings_applied=False,
            halt_changed=False,
            live_action=False,
            audit_json=_request_audit(
                parsed_type,
                setting_names,
                desired_bool,
                desired_stat,
                finding,
                next_action,
                source_name,
                settings,
                halt_before,
            ),
        )
        db.add(row)
        db.flush()
        db.add(
            Activity(
                lead_id=None,
                actor=ACTOR,
                action="live_settings_change_request_recorded",
                details={
                    "request_id": str(row.id),
                    "request_type": parsed_type.value,
                    "requested_setting_names": list(setting_names),
                    "desired_boolean": desired_bool,
                    "desired_status": desired_stat,
                    "finding_code": finding,
                    "next_action_code": next_action,
                    "idempotency_key": key,
                    "executed": False,
                    "settings_applied": False,
                    "owner_approved": False,
                    "halt_changed": False,
                    "live_action": False,
                    "no_execution": True,
                    "record_only": True,
                },
            )
        )
        db.flush()
        halt_after = _require_halt_unchanged(db, halt_before)
        if commit:
            db.commit()
            db.refresh(row)
        logger.info(
            "settings_change_request_created",
            request_id=str(row.id),
            request_type=parsed_type.value,
            reused=False,
            executed=False,
            settings_applied=False,
            live_action=False,
        )
        return _to_view(row, halt_before, halt_after, reused=False)

    def list_requests(
        self,
        db: Session,
        settings: Settings,
        *,
        status: str | None = None,
        request_type: str | None = None,
        owner_decision_status: str | None = None,
    ) -> SettingsChangeRequestList:
        del settings
        halt_before = read_operator_halt(db)
        stmt = select(LiveSettingsChangeRequest).order_by(
            LiveSettingsChangeRequest.requested_at.desc(),
            LiveSettingsChangeRequest.id.desc(),
        )
        parsed_status = _optional_status(status)
        parsed_type = _optional_request_type(request_type)
        parsed_decision = _optional_decision_status(owner_decision_status)
        if parsed_status is not None:
            stmt = stmt.where(LiveSettingsChangeRequest.status == parsed_status.value)
        if parsed_type is not None:
            stmt = stmt.where(LiveSettingsChangeRequest.request_type == parsed_type.value)
        if parsed_decision is not None:
            stmt = stmt.where(
                LiveSettingsChangeRequest.owner_decision_status == parsed_decision.value
            )
        rows = tuple(db.scalars(stmt).all())
        halt_after = _require_halt_unchanged(db, halt_before)
        views = tuple(_to_view(row, halt_before, halt_after, reused=False) for row in rows)
        pending = sum(
            1 for item in views if item.status == SettingsChangeRequestStatus.PENDING.value
        )
        result = SettingsChangeRequestList(
            generated_at=datetime.now(tz=UTC),
            request_count=len(views),
            pending_count=pending,
            decided_count=len(views) - pending,
            by_request_type=_count_by(views, lambda item: item.request_type),
            by_status=_count_by(views, lambda item: item.status),
            by_decision_status=_count_by(views, lambda item: item.owner_decision_status),
            record_only=True,
            no_execution=True,
            executed=0,
            live_action=False,
            outbound_attempted=False,
            owner_approved=False,
            settings_applied=False,
            halt_changed=False,
            operator_halt_status=halt_after.value,
            operator_halt_before=halt_before.value,
            operator_halt_after=halt_after.value,
            requests=views,
        )
        logger.info(
            "settings_change_requests_listed",
            request_count=result.request_count,
            pending_count=result.pending_count,
            executed=0,
            settings_applied=False,
            live_action=False,
        )
        return result

    def get_request(
        self,
        db: Session,
        settings: Settings,
        request_id: UUID,
    ) -> SettingsChangeRequestView | None:
        halt_before = read_operator_halt(db)
        row = db.get(LiveSettingsChangeRequest, request_id)
        halt_after = _require_halt_unchanged(db, halt_before)
        if row is None:
            return None
        del settings
        return _to_view(row, halt_before, halt_after, reused=False)

    def record_decision(
        self,
        db: Session,
        settings: Settings,
        *,
        request_id: UUID,
        decision: str,
        reviewer: str | None = None,
        source: str = "cli",
        reviewer_notes: str | None = None,
        commit: bool = True,
    ) -> SettingsChangeRequestView:
        del settings
        halt_before = read_operator_halt(db)
        row = db.get(LiveSettingsChangeRequest, request_id)
        if row is None:
            raise SettingsChangeRequestError("not_found", "Settings change request was not found")
        parsed = _parse_decision(decision)
        notes = _sanitize_notes(reviewer_notes)
        reviewer_name = sanitize_operator_text(reviewer) or "operator"
        source_name = sanitize_operator_text(source) or "cli"
        decided_at = datetime.now(tz=UTC)
        existing = row.decision_record
        previous = existing.decision if existing is not None else None
        if existing is None:
            existing = LiveSettingsChangeRequestDecision(
                live_settings_change_request_id=row.id,
                decision=parsed.value,
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
                settings_applied=False,
                halt_changed=False,
                live_action=False,
                audit_json=_decision_audit(row, parsed, reviewer_name, source_name, None),
            )
            db.add(existing)
        else:
            existing.previous_decision = previous
            existing.decision = parsed.value
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
            existing.settings_applied = False
            existing.halt_changed = False
            existing.live_action = False
            existing.audit_json = _decision_audit(
                row, parsed, reviewer_name, source_name, previous
            )
        row.status = SettingsChangeRequestStatus.DECISION_RECORDED.value
        row.owner_decision_status = parsed.value
        row.executed = False
        row.execution_attempted = False
        row.outbound_attempted = False
        row.live_call_attempted = False
        row.recommendation_applied = False
        row.spend_attempted = False
        row.campaign_launched = False
        row.pages_published = False
        row.ads_launched = False
        row.owner_approved = False
        row.settings_applied = False
        row.halt_changed = False
        row.live_action = False
        db.add(
            Activity(
                lead_id=None,
                actor=ACTOR,
                action="live_settings_change_decision_recorded",
                details={
                    "request_id": str(row.id),
                    "decision": parsed.value,
                    "previous_decision": previous,
                    "reviewer": reviewer_name,
                    "source": source_name,
                    "executed": False,
                    "settings_applied": False,
                    "owner_approved": False,
                    "halt_changed": False,
                    "live_action": False,
                    "no_execution": True,
                    "record_only": True,
                },
            )
        )
        db.flush()
        halt_after = _require_halt_unchanged(db, halt_before)
        if commit:
            db.commit()
            db.refresh(row)
        logger.info(
            "settings_change_decision_recorded",
            request_id=str(row.id),
            decision=parsed.value,
            executed=False,
            settings_applied=False,
            owner_approved=False,
            live_action=False,
        )
        return _to_view(row, halt_before, halt_after, reused=False)

    def propose_from_seeds(
        self,
        db: Session,
        settings: Settings,
        proposals: Sequence[SettingsChangeProposal],
        *,
        source: str = "launch_readiness",
        commit: bool = True,
    ) -> SettingsChangeProposeResult:
        halt_before = read_operator_halt(db)
        created = 0
        reused = 0
        views: list[SettingsChangeRequestView] = []
        for proposal in proposals:
            view = self.create(
                db,
                settings,
                request_type=proposal.request_type,
                requested_setting_names=proposal.requested_setting_names,
                desired_boolean=proposal.desired_boolean,
                desired_status=proposal.desired_status,
                finding_code=proposal.finding_code,
                next_action_code=proposal.next_action_code,
                source=source,
                commit=False,
            )
            if view.reused:
                reused += 1
            else:
                created += 1
            views.append(view)
        halt_after = _require_halt_unchanged(db, halt_before)
        if commit:
            db.commit()
        result = SettingsChangeProposeResult(
            created_count=created,
            reused_count=reused,
            request_count=len(views),
            record_only=True,
            no_execution=True,
            executed=0,
            live_action=False,
            outbound_attempted=False,
            owner_approved=False,
            settings_applied=False,
            halt_changed=False,
            operator_halt_status=halt_after.value,
            operator_halt_before=halt_before.value,
            operator_halt_after=halt_after.value,
            requests=tuple(views),
        )
        logger.info(
            "settings_change_requests_proposed",
            created_count=created,
            reused_count=reused,
            executed=0,
            settings_applied=False,
            live_action=False,
        )
        return result


def pending_settings_change_request_count(db: Session) -> int:
    return int(
        db.scalar(
            select(func.count())
            .select_from(LiveSettingsChangeRequest)
            .where(
                LiveSettingsChangeRequest.status == SettingsChangeRequestStatus.PENDING.value
            )
        )
        or 0
    )


def format_settings_change_list(
    result: SettingsChangeRequestList,
    *,
    as_json: bool = False,
) -> str:
    payload = sanitize_mapping(list_payload(result))
    if as_json:
        return json.dumps(payload, sort_keys=True)
    lines = [
        "Settings change requests:",
        f"count={payload['request_count']}",
        f"pending={payload['pending_count']}",
        f"decided={payload['decided_count']}",
        f"record_only={_bool_text(payload['record_only'])}",
        f"no_execution={_bool_text(payload['no_execution'])}",
        f"executed={payload['executed']}",
        f"live_action={_bool_text(payload['live_action'])}",
        f"settings_applied={_bool_text(payload['settings_applied'])}",
        f"halt_changed={_bool_text(payload['halt_changed'])}",
        f"owner_approved={_bool_text(payload['owner_approved'])}",
        (
            "Operator halt: "
            f"status={payload['operator_halt_status']} "
            f"before={payload['operator_halt_before']} "
            f"after={payload['operator_halt_after']}"
        ),
    ]
    for item in result.requests:
        lines.append(_format_request_line(item))
    return "\n".join(lines)


def format_settings_change_request(
    item: SettingsChangeRequestView,
    *,
    as_json: bool = False,
) -> str:
    payload = sanitize_mapping(request_payload(item))
    if as_json:
        return json.dumps(payload, sort_keys=True)
    lines = [
        "Settings change request:",
        _format_request_line(item),
    ]
    if item.decision is not None:
        lines.append(
            "Decision: "
            f"id={item.decision.decision_id} "
            f"decision={item.decision.decision} "
            f"reviewer={item.decision.reviewer} "
            f"executed={_bool_text(item.decision.executed)} "
            f"settings_applied={_bool_text(item.decision.settings_applied)} "
            f"owner_approved={_bool_text(item.decision.owner_approved)} "
            f"live_action={_bool_text(item.decision.live_action)}"
        )
    return "\n".join(lines)


def format_settings_change_propose(
    result: SettingsChangeProposeResult,
    *,
    as_json: bool = False,
) -> str:
    payload = sanitize_mapping(propose_payload(result))
    if as_json:
        return json.dumps(payload, sort_keys=True)
    lines = [
        "Proposed settings change requests:",
        f"created={payload['created_count']}",
        f"reused={payload['reused_count']}",
        f"count={payload['request_count']}",
        f"record_only={_bool_text(payload['record_only'])}",
        f"no_execution={_bool_text(payload['no_execution'])}",
        f"executed={payload['executed']}",
        f"settings_applied={_bool_text(payload['settings_applied'])}",
        f"live_action={_bool_text(payload['live_action'])}",
        f"halt_changed={_bool_text(payload['halt_changed'])}",
    ]
    for item in result.requests:
        lines.append(_format_request_line(item))
    return "\n".join(lines)


def list_payload(result: SettingsChangeRequestList) -> dict[str, Any]:
    return {
        "generated_at": result.generated_at.isoformat(),
        "request_count": result.request_count,
        "pending_count": result.pending_count,
        "decided_count": result.decided_count,
        "by_request_type": dict(result.by_request_type),
        "by_status": dict(result.by_status),
        "by_decision_status": dict(result.by_decision_status),
        "record_only": True,
        "no_execution": True,
        "executed": 0,
        "live_action": False,
        "outbound_attempted": False,
        "owner_approved": False,
        "settings_applied": False,
        "halt_changed": False,
        "operator_halt_status": result.operator_halt_status,
        "operator_halt_before": result.operator_halt_before,
        "operator_halt_after": result.operator_halt_after,
        "requests": [request_payload(item) for item in result.requests],
    }


def propose_payload(result: SettingsChangeProposeResult) -> dict[str, Any]:
    return {
        "created_count": result.created_count,
        "reused_count": result.reused_count,
        "request_count": result.request_count,
        "record_only": True,
        "no_execution": True,
        "executed": 0,
        "live_action": False,
        "outbound_attempted": False,
        "owner_approved": False,
        "settings_applied": False,
        "halt_changed": False,
        "operator_halt_status": result.operator_halt_status,
        "operator_halt_before": result.operator_halt_before,
        "operator_halt_after": result.operator_halt_after,
        "requests": [request_payload(item) for item in result.requests],
    }


def request_payload(item: SettingsChangeRequestView) -> dict[str, Any]:
    return {
        "request_id": str(item.request_id),
        "request_type": item.request_type,
        "status": item.status,
        "owner_decision_status": item.owner_decision_status,
        "idempotency_key": item.idempotency_key,
        "requested_setting_names": list(item.requested_setting_names),
        "desired_boolean": item.desired_boolean,
        "desired_status": item.desired_status,
        "finding_code": item.finding_code,
        "next_action_code": item.next_action_code,
        "source": item.source,
        "reviewer_notes": item.reviewer_notes,
        "requested_at": item.requested_at.isoformat(),
        "record_only": True,
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
        "settings_applied": False,
        "halt_changed": False,
        "live_action": False,
        "reused": item.reused,
        "operator_halt_status": item.operator_halt_status,
        "operator_halt_before": item.operator_halt_before,
        "operator_halt_after": item.operator_halt_after,
        "decision": (
            {
                "decision_id": str(item.decision.decision_id),
                "decision": item.decision.decision,
                "reviewer": item.decision.reviewer,
                "source": item.decision.source,
                "reviewer_notes": item.decision.reviewer_notes,
                "decided_at": item.decision.decided_at.isoformat(),
                "executed": False,
                "settings_applied": False,
                "owner_approved": False,
                "halt_changed": False,
                "live_action": False,
                "no_execution": True,
            }
            if item.decision is not None
            else None
        ),
    }


def _format_request_line(item: SettingsChangeRequestView) -> str:
    names = ",".join(item.requested_setting_names) or "-"
    desired = "null" if item.desired_boolean is None else _bool_text(item.desired_boolean)
    return (
        "Request: "
        f"id={item.request_id} "
        f"type={item.request_type} "
        f"status={item.status} "
        f"decision={item.owner_decision_status} "
        f"settings={names} "
        f"desired_boolean={desired} "
        f"desired_status={item.desired_status or '-'} "
        f"finding={item.finding_code or '-'} "
        f"next_action={item.next_action_code or '-'} "
        f"reused={_bool_text(item.reused)} "
        f"executed={_bool_text(item.executed)} "
        f"settings_applied={_bool_text(item.settings_applied)} "
        f"owner_approved={_bool_text(item.owner_approved)} "
        f"live_action={_bool_text(item.live_action)} "
        f"no_execution={_bool_text(item.no_execution)}"
    )


def _to_view(
    row: LiveSettingsChangeRequest,
    halt_before: HaltStatus,
    halt_after: HaltStatus,
    *,
    reused: bool,
) -> SettingsChangeRequestView:
    decision_row = row.decision_record
    decision = None
    if decision_row is not None:
        decision = SettingsChangeDecisionView(
            decision_id=decision_row.id,
            decision=decision_row.decision,
            reviewer=decision_row.reviewer,
            source=decision_row.source,
            reviewer_notes=decision_row.reviewer_notes,
            decided_at=decision_row.decided_at,
            executed=False,
            settings_applied=False,
            owner_approved=False,
            halt_changed=False,
            live_action=False,
            no_execution=True,
        )
    return SettingsChangeRequestView(
        request_id=row.id,
        request_type=row.request_type,
        status=row.status,
        owner_decision_status=row.owner_decision_status,
        idempotency_key=row.idempotency_key,
        requested_setting_names=_stored_setting_names(row.requested_setting_names),
        desired_boolean=row.desired_boolean,
        desired_status=row.desired_status,
        finding_code=row.finding_code,
        next_action_code=row.next_action_code,
        source=row.source,
        reviewer_notes=row.reviewer_notes,
        requested_at=row.requested_at,
        record_only=True,
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
        settings_applied=False,
        halt_changed=False,
        live_action=False,
        reused=reused,
        operator_halt_status=halt_after.value,
        operator_halt_before=halt_before.value,
        operator_halt_after=halt_after.value,
        decision=decision,
    )


def _parse_request_type(value: str) -> SettingsChangeRequestType:
    cleaned = (value or "").strip()
    try:
        return SettingsChangeRequestType(cleaned)
    except ValueError:
        raise SettingsChangeRequestError(
            "invalid_request_type",
            "Unknown settings change request type",
        ) from None


def _optional_request_type(value: str | None) -> SettingsChangeRequestType | None:
    if value is None or not value.strip():
        return None
    return _parse_request_type(value)


def _optional_status(value: str | None) -> SettingsChangeRequestStatus | None:
    if value is None or not value.strip():
        return None
    cleaned = value.strip()
    try:
        return SettingsChangeRequestStatus(cleaned)
    except ValueError:
        raise SettingsChangeRequestError(
            "invalid_status",
            "Unknown settings change request status",
        ) from None


def _optional_decision_status(value: str | None) -> SettingsChangeDecisionStatus | None:
    if value is None or not value.strip():
        return None
    cleaned = value.strip()
    try:
        return SettingsChangeDecisionStatus(cleaned)
    except ValueError:
        raise SettingsChangeRequestError(
            "invalid_decision",
            "Unknown owner decision status",
        ) from None


def _parse_decision(value: str) -> SettingsChangeDecisionStatus:
    parsed = _optional_decision_status(value)
    if parsed is None or parsed is SettingsChangeDecisionStatus.PENDING:
        raise SettingsChangeRequestError(
            "invalid_decision",
            "Owner decision must be approved, rejected, or needs_changes",
        )
    return parsed


def _parse_setting_names(values: Sequence[str]) -> tuple[str, ...]:
    names: list[str] = []
    seen: set[str] = set()
    for raw in values:
        name = _normalize_setting_name(raw)
        if name in seen:
            continue
        seen.add(name)
        names.append(name)
    if not names:
        raise SettingsChangeRequestError(
            "invalid_setting_name",
            "At least one requested setting name is required",
        )
    return tuple(names)


def _normalize_setting_name(value: str) -> str:
    cleaned = (value or "").strip().upper().replace("-", "_").replace(" ", "_")
    _reject_secret_text(cleaned, "setting_name")
    if cleaned == "OUTBOUND_HALTED":
        cleaned = "OPERATOR_HALT"
    if not SETTING_NAME_RE.fullmatch(cleaned) or cleaned not in ALLOWED_SETTINGS:
        raise SettingsChangeRequestError(
            "invalid_setting_name",
            "Requested setting name is not an allowed live-settings identifier",
        )
    return cleaned


def _validate_desired_state(
    request_type: SettingsChangeRequestType,
    setting_names: tuple[str, ...],
    *,
    desired_boolean: bool | None,
    desired_status: str | None,
) -> tuple[bool | None, str | None]:
    status = _parse_desired_status(desired_status)
    match request_type:
        case SettingsChangeRequestType.KEEP_OUTBOUND_DISABLED:
            _require_settings(setting_names, {"OUTBOUND_ENABLED"}, exact=True)
            return False, SettingsChangeDesiredStatus.DISABLED.value
        case SettingsChangeRequestType.REQUEST_OUTBOUND_ENABLEMENT_REVIEW:
            _require_settings(setting_names, {"OUTBOUND_ENABLED"}, exact=True)
            return True, SettingsChangeDesiredStatus.ENABLED.value
        case SettingsChangeRequestType.REQUEST_PROVIDER_LIVE_FLAG_REVIEW:
            if len(setting_names) != 1 or setting_names[0] not in LIVE_PROVIDER_FLAG_SETTINGS:
                raise SettingsChangeRequestError(
                    "invalid_setting_name",
                    "Provider live-flag review requires exactly one live-provider flag name",
                )
            enabled = True if desired_boolean is None else desired_boolean
            return enabled, (
                SettingsChangeDesiredStatus.ENABLED.value
                if enabled
                else SettingsChangeDesiredStatus.DISABLED.value
            )
        case SettingsChangeRequestType.REQUEST_OPERATOR_HALT_REVIEW:
            _require_settings(setting_names, {"OPERATOR_HALT"}, exact=True)
            halted = True if desired_boolean is None else desired_boolean
            if status is SettingsChangeDesiredStatus.CLEARED:
                halted = False
            elif status is SettingsChangeDesiredStatus.HALTED:
                halted = True
            return halted, (
                SettingsChangeDesiredStatus.HALTED.value
                if halted
                else SettingsChangeDesiredStatus.CLEARED.value
            )
        case SettingsChangeRequestType.REQUEST_CREDENTIAL_CONFIGURATION_REVIEW:
            if any(name not in CREDENTIAL_SETTINGS for name in setting_names):
                raise SettingsChangeRequestError(
                    "invalid_setting_name",
                    "Credential review may name required env/config variables only",
                )
            if desired_boolean is True:
                raise SettingsChangeRequestError(
                    "invalid_desired_state",
                    "Credential review cannot request a secret value or live enablement",
                )
            return None, SettingsChangeDesiredStatus.CONFIGURED.value
        case SettingsChangeRequestType.KEEP_SAFE_DEFAULT:
            if any(name in CREDENTIAL_SETTINGS for name in setting_names):
                raise SettingsChangeRequestError(
                    "invalid_setting_name",
                    "Keep-safe-default notes may name flags or operator halt only",
                )
            if setting_names == ("OPERATOR_HALT",):
                return True, SettingsChangeDesiredStatus.HALTED.value
            if any(name not in FLAG_SETTINGS - HALT_SETTINGS for name in setting_names):
                raise SettingsChangeRequestError(
                    "invalid_setting_name",
                    "Keep-safe-default notes must use allowed live-settings flag names",
                )
            return False, SettingsChangeDesiredStatus.DISABLED.value
        case _:
            return _unreachable(request_type)


def _require_settings(
    setting_names: tuple[str, ...],
    allowed: set[str],
    *,
    exact: bool,
) -> None:
    actual = set(setting_names)
    if exact and actual != allowed:
        raise SettingsChangeRequestError(
            "invalid_setting_name",
            "Requested setting names do not match the request type",
        )
    if not exact and not actual.issubset(allowed):
        raise SettingsChangeRequestError(
            "invalid_setting_name",
            "Requested setting names do not match the request type",
        )


def _parse_desired_status(value: str | None) -> SettingsChangeDesiredStatus | None:
    if value is None or not value.strip():
        return None
    cleaned = value.strip().lower()
    try:
        return SettingsChangeDesiredStatus(cleaned)
    except ValueError:
        raise SettingsChangeRequestError(
            "invalid_desired_state",
            "Unknown desired status",
        ) from None


def _optional_code(value: str | None, field: str) -> str | None:
    if value is None or not value.strip():
        return None
    text = value.strip().lower().replace("-", "_").replace(" ", "_")
    _reject_secret_text(text, field)
    if not CODE_RE.fullmatch(text):
        raise SettingsChangeRequestError(
            "invalid_code",
            f"{field} must be a sanitized code",
        )
    if field == "finding_code":
        try:
            return FindingCode(text).value
        except ValueError:
            return text if CODE_RE.fullmatch(text) else None
    if field == "next_action_code":
        try:
            return NextActionCode(text).value
        except ValueError:
            return text
    return text


def _idempotency_key(
    *,
    supplied: str | None,
    request_type: SettingsChangeRequestType,
    setting_names: tuple[str, ...],
    desired_boolean: bool | None,
    desired_status: str | None,
    finding_code: str | None,
    next_action_code: str | None,
) -> str:
    if supplied is not None and supplied.strip():
        key = supplied.strip()
        _reject_secret_text(key, "idempotency_key")
        if not IDEMPOTENCY_KEY_RE.fullmatch(key):
            raise SettingsChangeRequestError(
                "invalid_idempotency_key",
                "Idempotency key must be 8-128 URL-safe characters",
            )
        return key
    payload = {
        "request_type": request_type.value,
        "requested_setting_names": list(setting_names),
        "desired_boolean": desired_boolean,
        "desired_status": desired_status,
        "finding_code": finding_code,
        "next_action_code": next_action_code,
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()
    return f"scr:{digest}"


def _sanitize_notes(value: str | None) -> str | None:
    if value is None:
        return None
    _reject_secret_text(value, "reviewer_notes")
    cleaned = sanitize_operator_text(value)
    if cleaned is None:
        return None
    return cleaned or None


def _reject_secret_text(value: str, field: str) -> None:
    lowered = value.lower()
    if (
        "sk-" in lowered
        or "rk-" in lowered
        or "bearer " in lowered
        or "password" in lowered
        or "postgresql+" in lowered
        or "@" in value
        or "api_key=" in lowered
        or "token=" in lowered
    ):
        raise SettingsChangeRequestError(
            "secret_value_rejected",
            f"{field} must not include secret values",
        )


def _stored_setting_names(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    names: list[str] = []
    for item in value:
        if isinstance(item, str) and item in ALLOWED_SETTINGS:
            names.append("OPERATOR_HALT" if item == "OUTBOUND_HALTED" else item)
    return tuple(names)


def _request_audit(
    request_type: SettingsChangeRequestType,
    setting_names: tuple[str, ...],
    desired_boolean: bool | None,
    desired_status: str | None,
    finding_code: str | None,
    next_action_code: str | None,
    source: str,
    settings: Settings,
    halt: HaltStatus,
) -> dict[str, object]:
    del settings
    return {
        "request_type": request_type.value,
        "requested_setting_names": list(setting_names),
        "desired_boolean": desired_boolean,
        "desired_status": desired_status,
        "finding_code": finding_code,
        "next_action_code": next_action_code,
        "source": source,
        "record_only": True,
        "no_execution": True,
        "executed": False,
        "settings_applied": False,
        "owner_approved": False,
        "halt_changed": False,
        "live_action": False,
        "operator_halt_status": halt.value,
        "secrets_exposed": False,
    }


def _decision_audit(
    row: LiveSettingsChangeRequest,
    decision: SettingsChangeDecisionStatus,
    reviewer: str,
    source: str,
    previous: str | None,
) -> dict[str, object]:
    return {
        "request_id": str(row.id),
        "request_type": row.request_type,
        "decision": decision.value,
        "previous_decision": previous,
        "reviewer": reviewer,
        "source": source,
        "executed": False,
        "settings_applied": False,
        "owner_approved": False,
        "halt_changed": False,
        "live_action": False,
        "no_execution": True,
        "record_only": True,
    }


def _require_halt_unchanged(db: Session, halt_before: HaltStatus) -> HaltStatus:
    halt_after = read_operator_halt(db)
    if halt_after is not halt_before:
        raise RuntimeError("settings change requests must not change operator halt status")
    return halt_after


def _count_by(
    items: Sequence[SettingsChangeRequestView],
    key: Any,
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        value = str(key(item))
        counts[value] = counts.get(value, 0) + 1
    return counts


def _bool_text(value: object) -> str:
    return "true" if value else "false"


def _unreachable(value: object) -> Never:
    raise RuntimeError(f"unhandled settings change request variant: {value!r}")
