"""Read-only operator activity audit timeline.

Phase 34 assembles existing activity, audit, and decision records into a
sanitized chronological view. It never writes pipeline rows, never executes
an approved item, packet, or settings request, and never changes operator
halt, outbound, or live-provider state.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, Never
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from vyro_growth.config import Settings
from vyro_growth.domain import ReviewDecisionStatus, SettingsChangeDecisionStatus
from vyro_growth.models import (
    Activity,
    LiveSettingsChangeRequestDecision,
    OperatorReviewDecision,
    OwnerApprovalPacketDecision,
)
from vyro_growth.observability import (
    SENSITIVE_KEYS,
    UNSAFE_CONTENT_KEYS,
    sanitize_error_message,
    sanitize_operator_text,
)
from vyro_growth.services.operator_halt import read_operator_halt

logger = structlog.get_logger(__name__)

DEFAULT_ENTRY_LIMIT = 100
AuditWindow = Literal["all", "24h", "7d", "30d"]
AUDIT_WINDOWS: tuple[AuditWindow, ...] = ("all", "24h", "7d", "30d")
DECISION_ACTIVITY_ACTIONS = frozenset(
    {
        "operator_review_decision_recorded",
        "owner_approval_packet_decision_recorded",
        "live_settings_change_decision_recorded",
    }
)
KNOWN_DECISION_STATUSES = frozenset(
    {
        *(item.value for item in ReviewDecisionStatus),
        *(item.value for item in SettingsChangeDecisionStatus),
        "pending",
        "pending_operator_review",
        "completed",
        "failed",
        "planned",
        "skipped",
        "blocked",
        "suppressed",
        "running",
    }
)
_TOKEN_RE = re.compile(r"^[a-z][a-z0-9_]{0,119}$")
_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
_SAFE_ID_KEYS: dict[str, str] = {
    "artifact_id": "artifact_id",
    "owner_approval_packet_id": "packet_id",
    "approval_packet_id": "packet_id",
    "packet_id": "packet_id",
    "request_id": "request_id",
    "candidate_id": "candidate_id",
    "organization_id": "organization_id",
    "discovery_run_id": "run_id",
    "execution_plan_run_id": "run_id",
    "approval_packet_run_id": "run_id",
    "enrichment_run_id": "run_id",
    "optimizer_run_id": "run_id",
    "channel_plan_run_id": "run_id",
    "content_brief_run_id": "run_id",
    "outreach_plan_run_id": "run_id",
    "booking_plan_run_id": "run_id",
    "voice_qualification_run_id": "run_id",
}
_SAFE_STATUS_KEYS = ("status", "item_status", "request_status", "preflight_status")
_SAFE_DECISION_KEYS = ("decision", "owner_decision_status", "decision_status")
_SAFE_REASON_KEYS = (
    "reason",
    "skip_reason",
    "finding_code",
    "next_action_code",
    "blocker_code",
    "error_code",
)
_SAFE_TYPE_KEYS = ("artifact_type", "request_type", "plan_family")
_SOURCE_KEY = "source"


@dataclass(frozen=True)
class AuditTimelineEntry:
    entry_id: UUID
    event_type: str
    source_surface: str
    occurred_at: datetime
    actor_label: str | None
    source_label: str | None
    lead_id: UUID | None
    organization_id: UUID | None
    artifact_id: UUID | None
    artifact_type: str | None
    packet_id: UUID | None
    request_id: UUID | None
    candidate_id: UUID | None
    run_id: UUID | None
    status: str | None
    decision_status: str | None
    reason_label: str | None
    read_only: bool
    no_execution: bool
    executed: bool
    outbound_attempted: bool
    live_action: bool
    owner_approved: bool
    settings_applied: bool
    halt_changed: bool


@dataclass(frozen=True)
class OperatorAuditTimeline:
    generated_at: datetime
    read_only: bool
    no_execution: bool
    dry_run_only: bool
    executed: int
    live_action: bool
    outbound_attempted: bool
    owner_approved: bool
    settings_applied: bool
    halt_changed: bool
    operator_halt_status: str
    operator_halt_before: str
    operator_halt_after: str
    outbound_enabled: bool
    matching_count: int
    shown_count: int
    truncated: bool
    event_type: str | None
    source: str | None
    status: str | None
    window: AuditWindow
    available_event_types: tuple[str, ...]
    available_sources: tuple[str, ...]
    available_statuses: tuple[str, ...]
    entries: tuple[AuditTimelineEntry, ...]


class OperatorAuditTimelineService:
    """Read-only audit timeline. Does not write rows or call live providers."""

    def __init__(self, *, limit: int = DEFAULT_ENTRY_LIMIT) -> None:
        self.limit = limit

    def timeline(
        self,
        db: Session,
        settings: Settings,
        *,
        event_type: str | None = None,
        source: str | None = None,
        status: str | None = None,
        window: AuditWindow = "all",
    ) -> OperatorAuditTimeline:
        halt_before = read_operator_halt(db)
        parsed_event = parse_event_type(event_type)
        parsed_source = parse_source(source)
        parsed_status = parse_status(status)
        parsed_window = parse_window(window)
        collected = _collect_entries(db)
        available_event_types = _unique_sorted(item.event_type for item in collected)
        available_sources = _unique_sorted(item.source_surface for item in collected)
        available_statuses = _unique_sorted(
            value
            for item in collected
            for value in (item.status, item.decision_status)
            if value
        )
        filtered = _apply_filters(
            collected,
            event_type=parsed_event,
            source=parsed_source,
            status=parsed_status,
            window=parsed_window,
        )
        shown = filtered[: self.limit]
        halt_after = read_operator_halt(db)
        if halt_after is not halt_before:
            raise RuntimeError("operator audit timeline must not change operator halt status")
        snapshot = OperatorAuditTimeline(
            generated_at=datetime.now(tz=UTC),
            read_only=True,
            no_execution=True,
            dry_run_only=True,
            executed=0,
            live_action=False,
            outbound_attempted=False,
            owner_approved=False,
            settings_applied=False,
            halt_changed=False,
            operator_halt_status=halt_after.value,
            operator_halt_before=halt_before.value,
            operator_halt_after=halt_after.value,
            outbound_enabled=bool(settings.outbound_enabled),
            matching_count=len(filtered),
            shown_count=len(shown),
            truncated=len(filtered) > len(shown),
            event_type=parsed_event,
            source=parsed_source,
            status=parsed_status,
            window=parsed_window,
            available_event_types=available_event_types,
            available_sources=available_sources,
            available_statuses=available_statuses,
            entries=tuple(shown),
        )
        logger.info(
            "operator_audit_timeline_built",
            read_only=True,
            no_execution=True,
            matching_count=snapshot.matching_count,
            shown_count=snapshot.shown_count,
            operator_halt_status=snapshot.operator_halt_status,
            outbound_enabled=snapshot.outbound_enabled,
        )
        return snapshot


def parse_window(value: str | AuditWindow | None) -> AuditWindow:
    match value:
        case "all" | "24h" | "7d" | "30d":
            return value
        case _:
            return "all"


def parse_event_type(value: str | None) -> str | None:
    return _parse_token(value)


def parse_source(value: str | None) -> str | None:
    return _parse_token(value)


def parse_status(value: str | None) -> str | None:
    token = _parse_token(value)
    if token is None:
        return None
    if token in KNOWN_DECISION_STATUSES or _TOKEN_RE.fullmatch(token):
        return token
    return None


def _parse_token(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip().lower()
    if not cleaned or not _TOKEN_RE.fullmatch(cleaned):
        return None
    return cleaned


def _collect_entries(db: Session) -> list[AuditTimelineEntry]:
    entries: list[AuditTimelineEntry] = []
    activities = db.scalars(select(Activity)).all()
    for activity in activities:
        if activity.action in DECISION_ACTIVITY_ACTIONS:
            continue
        entries.append(_from_activity(activity))
    for review in db.scalars(select(OperatorReviewDecision)).all():
        entries.append(_from_review_decision(review))
    for packet in db.scalars(select(OwnerApprovalPacketDecision)).all():
        entries.append(_from_packet_decision(packet))
    for request_decision in db.scalars(select(LiveSettingsChangeRequestDecision)).all():
        entries.append(_from_settings_decision(request_decision))
    entries.sort(key=lambda item: (_as_utc(item.occurred_at), str(item.entry_id)), reverse=True)
    return entries


def _apply_filters(
    entries: Sequence[AuditTimelineEntry],
    *,
    event_type: str | None,
    source: str | None,
    status: str | None,
    window: AuditWindow,
) -> list[AuditTimelineEntry]:
    cutoff = _window_cutoff(window)
    selected: list[AuditTimelineEntry] = []
    for item in entries:
        if cutoff is not None and _as_utc(item.occurred_at) < cutoff:
            continue
        if event_type and item.event_type != event_type:
            continue
        if source and item.source_surface != source:
            continue
        if status and status not in {item.status, item.decision_status}:
            continue
        selected.append(item)
    return selected


def _window_cutoff(window: AuditWindow) -> datetime | None:
    now = datetime.now(tz=UTC)
    match window:
        case "all":
            return None
        case "24h":
            return now - timedelta(hours=24)
        case "7d":
            return now - timedelta(days=7)
        case "30d":
            return now - timedelta(days=30)
        case _:
            return _unreachable_window(window)


def _from_activity(row: Activity) -> AuditTimelineEntry:
    details = row.details if isinstance(row.details, dict) else {}
    ids = _extract_ids(details)
    actor = _safe_label(row.actor) or "system"
    source_label = _safe_label(_string_value(details.get(_SOURCE_KEY))) or actor
    return AuditTimelineEntry(
        entry_id=row.id,
        event_type=_safe_token(row.action) or "activity",
        source_surface=_safe_token(row.actor) or "activity",
        occurred_at=_as_utc(row.created_at),
        actor_label=actor,
        source_label=source_label,
        lead_id=row.lead_id,
        organization_id=ids.get("organization_id"),
        artifact_id=ids.get("artifact_id"),
        artifact_type=_safe_token(_first_string(details, _SAFE_TYPE_KEYS)),
        packet_id=ids.get("packet_id"),
        request_id=ids.get("request_id"),
        candidate_id=ids.get("candidate_id"),
        run_id=ids.get("run_id"),
        status=_safe_token(_first_string(details, _SAFE_STATUS_KEYS)),
        decision_status=_safe_token(_first_string(details, _SAFE_DECISION_KEYS)),
        reason_label=_reason_label(details),
        read_only=True,
        no_execution=True,
        executed=_flag(details.get("executed")),
        outbound_attempted=_flag(details.get("outbound_attempted")),
        live_action=_flag(details.get("live_action")),
        owner_approved=_flag(details.get("owner_approved")),
        settings_applied=_flag(details.get("settings_applied")),
        halt_changed=_flag(details.get("halt_changed")),
    )


def _from_review_decision(row: OperatorReviewDecision) -> AuditTimelineEntry:
    return AuditTimelineEntry(
        entry_id=row.id,
        event_type="operator_review_decision",
        source_surface="operator_review_decision",
        occurred_at=_as_utc(row.decided_at),
        actor_label=_safe_label(row.reviewer) or "operator",
        source_label=_safe_label(row.source) or "cli",
        lead_id=None,
        organization_id=None,
        artifact_id=row.artifact_id,
        artifact_type=_safe_token(row.artifact_type),
        packet_id=None,
        request_id=None,
        candidate_id=None,
        run_id=None,
        status=_safe_token(row.item_status),
        decision_status=_safe_token(row.decision),
        reason_label=None,
        read_only=True,
        no_execution=True,
        executed=bool(row.executed),
        outbound_attempted=bool(row.outbound_attempted),
        live_action=False,
        owner_approved=False,
        settings_applied=False,
        halt_changed=False,
    )


def _from_packet_decision(row: OwnerApprovalPacketDecision) -> AuditTimelineEntry:
    return AuditTimelineEntry(
        entry_id=row.id,
        event_type="approval_packet_decision",
        source_surface="approval_packet_decision",
        occurred_at=_as_utc(row.decided_at),
        actor_label=_safe_label(row.reviewer) or "operator",
        source_label=_safe_label(row.source) or "operator_ui",
        lead_id=None,
        organization_id=None,
        artifact_id=None,
        artifact_type=None,
        packet_id=row.owner_approval_packet_id,
        request_id=None,
        candidate_id=None,
        run_id=None,
        status=_safe_token(row.decision),
        decision_status=_safe_token(row.decision),
        reason_label=None,
        read_only=True,
        no_execution=True,
        executed=bool(row.executed),
        outbound_attempted=bool(row.outbound_attempted),
        live_action=False,
        owner_approved=bool(row.owner_approved),
        settings_applied=False,
        halt_changed=False,
    )


def _from_settings_decision(row: LiveSettingsChangeRequestDecision) -> AuditTimelineEntry:
    return AuditTimelineEntry(
        entry_id=row.id,
        event_type="settings_change_decision",
        source_surface="settings_change_decision",
        occurred_at=_as_utc(row.decided_at),
        actor_label=_safe_label(row.reviewer) or "operator",
        source_label=_safe_label(row.source) or "cli",
        lead_id=None,
        organization_id=None,
        artifact_id=None,
        artifact_type=None,
        packet_id=None,
        request_id=row.live_settings_change_request_id,
        candidate_id=None,
        run_id=None,
        status=_safe_token(row.decision),
        decision_status=_safe_token(row.decision),
        reason_label=None,
        read_only=True,
        no_execution=True,
        executed=bool(row.executed),
        outbound_attempted=bool(row.outbound_attempted),
        live_action=bool(row.live_action),
        owner_approved=bool(row.owner_approved),
        settings_applied=bool(row.settings_applied),
        halt_changed=bool(row.halt_changed),
    )


def _extract_ids(details: dict[str, Any]) -> dict[str, UUID]:
    found: dict[str, UUID] = {}
    for key, field in _SAFE_ID_KEYS.items():
        if field in found:
            continue
        parsed = _safe_uuid(details.get(key))
        if parsed is not None:
            found[field] = parsed
    return found


def _reason_label(details: dict[str, Any]) -> str | None:
    for key in _SAFE_REASON_KEYS:
        raw = details.get(key)
        if not isinstance(raw, str) or not raw.strip():
            continue
        if key.lower() in SENSITIVE_KEYS or key.lower() in UNSAFE_CONTENT_KEYS:
            continue
        cleaned = sanitize_error_message(raw) if key == "reason" else sanitize_operator_text(raw)
        if cleaned:
            return cleaned
    return None


def _first_string(details: dict[str, Any], keys: Iterable[str]) -> str | None:
    for key in keys:
        value = _string_value(details.get(key))
        if value:
            return value
    return None


def _string_value(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _safe_token(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip().lower().replace(" ", "_")
    if not cleaned or not _TOKEN_RE.fullmatch(cleaned):
        sanitized = sanitize_operator_text(cleaned)
        if sanitized and _TOKEN_RE.fullmatch(sanitized.lower().replace(" ", "_")):
            return sanitized.lower().replace(" ", "_")
        return None
    return cleaned


def _safe_label(value: str | None) -> str | None:
    if value is None:
        return None
    return sanitize_operator_text(value)


def _safe_uuid(value: object) -> UUID | None:
    if isinstance(value, UUID):
        return value
    if isinstance(value, str) and _UUID_RE.fullmatch(value.strip()):
        return UUID(value.strip())
    return None


def _flag(value: object) -> bool:
    return value is True


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _unique_sorted(values: Iterable[str | None]) -> tuple[str, ...]:
    unique = sorted({item for item in values if item})
    return tuple(unique)


def _unreachable_window(value: str) -> Never:
    raise RuntimeError(f"unhandled audit timeline window: {value!r}")
