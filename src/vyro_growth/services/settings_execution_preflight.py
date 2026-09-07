"""Dry-run preflight for approved live settings change requests.

Phase 30 evaluates recorded settings-change requests and owner decisions and
explains what would still block real execution. It never applies settings,
lifts halt, sets live owner_approved, calls providers, or executes anything.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Never
from uuid import UUID

import structlog
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from vyro_growth.config import Settings, any_live_provider_enabled
from vyro_growth.domain import (
    ReviewDecisionStatus,
    SecretName,
    SettingsChangeDecisionStatus,
    SettingsChangeRequestType,
    SettingsExecutionBlockerCode,
    SettingsExecutionGateCode,
    SettingsExecutionPreflightStatus,
)
from vyro_growth.models import OwnerApprovalPacket, OwnerApprovalPacketDecision
from vyro_growth.observability import sanitize_mapping
from vyro_growth.services.operator_halt import HaltStatus, read_operator_halt
from vyro_growth.services.settings_change_requests import (
    CREDENTIAL_SETTINGS,
    LIVE_PROVIDER_FLAG_SETTINGS,
    SettingsChangeRequestService,
    SettingsChangeRequestView,
)

logger = structlog.get_logger(__name__)

FUTURE_EXECUTION_PHASE_EXISTS = False
LIVE_CREDENTIAL_NAMES: frozenset[str] = frozenset(
    {
        SecretName.OPENAI_API_KEY.value,
        SecretName.SMARTLEAD_API_KEY.value,
        SecretName.GOOGLE_CALENDAR_API_KEY.value,
        SecretName.VOICE_API_KEY.value,
        SecretName.DECISION_MAKER_API_KEY.value,
    }
)
FLAG_CREDENTIALS: dict[str, str] = {
    "OPENAI_PERSONALIZATION_ENABLED": SecretName.OPENAI_API_KEY.value,
    "OPENAI_REPLY_CLASSIFICATION_ENABLED": SecretName.OPENAI_API_KEY.value,
    "SMARTLEAD_LIVE_ENABLED": SecretName.SMARTLEAD_API_KEY.value,
    "GOOGLE_CALENDAR_LIVE_ENABLED": SecretName.GOOGLE_CALENDAR_API_KEY.value,
    "VOICE_LIVE_ENABLED": SecretName.VOICE_API_KEY.value,
    "DECISION_MAKER_LIVE_ENABLED": SecretName.DECISION_MAKER_API_KEY.value,
}
EXECUTION_STATUSES: frozenset[str] = frozenset(
    item.value for item in SettingsExecutionPreflightStatus
)
REQUEST_TYPES: frozenset[str] = frozenset(item.value for item in SettingsChangeRequestType)
DECISION_STATUSES: frozenset[str] = frozenset(item.value for item in SettingsChangeDecisionStatus)
GATE_BLOCKERS: frozenset[str] = frozenset(
    {
        SettingsExecutionBlockerCode.OPERATOR_HALT_ACTIVE.value,
        SettingsExecutionBlockerCode.OPERATOR_HALT_UNAVAILABLE.value,
        SettingsExecutionBlockerCode.OUTBOUND_DISABLED.value,
        SettingsExecutionBlockerCode.PROVIDER_LIVE_FLAG_FALSE.value,
        SettingsExecutionBlockerCode.MISSING_CREDENTIAL.value,
    }
)


@dataclass(frozen=True)
class SettingsExecutionPreflightItem:
    request_id: UUID
    request_type: str
    request_status: str
    decision_status: str
    requested_setting_names: tuple[str, ...]
    desired_boolean: bool | None
    desired_status: str | None
    execution_status: str
    blocker_codes: tuple[str, ...]
    missing_approval_codes: tuple[str, ...]
    missing_gate_codes: tuple[str, ...]
    missing_credential_names: tuple[str, ...]
    closed_provider_flag_names: tuple[str, ...]
    requested_at: datetime
    simulated_at: datetime
    record_only: bool
    no_execution: bool
    dry_run_only: bool
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
    execution_allowed: bool
    future_execution_phase_exists: bool


@dataclass(frozen=True)
class SettingsExecutionPreflight:
    generated_at: datetime
    overall_status: str
    request_count: int
    pending_decision_count: int
    approved_decision_count: int
    rejected_or_needs_changes_count: int
    blocked_count: int
    executable_count: int
    by_request_type: dict[str, int]
    by_decision_status: dict[str, int]
    by_execution_status: dict[str, int]
    blocker_codes: tuple[str, ...]
    missing_approval_codes: tuple[str, ...]
    missing_gate_codes: tuple[str, ...]
    missing_credential_names: tuple[str, ...]
    closed_provider_flag_names: tuple[str, ...]
    record_only: bool
    no_execution: bool
    dry_run_only: bool
    executed: int
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
    execution_allowed: bool
    future_execution_phase_exists: bool
    outbound_enabled: bool
    live_providers_enabled: bool
    operator_halt_status: str
    operator_halt_before: str
    operator_halt_after: str
    pending_owner_approval_packet_count: int
    approved_owner_approval_packet_count: int
    requests: tuple[SettingsExecutionPreflightItem, ...]


@dataclass(frozen=True)
class SettingsExecutionPreflightFilters:
    request_type: str | None = None
    decision_status: str | None = None
    execution_status: str | None = None


class SettingsExecutionPreflightService:
    """Simulate settings-request execution gates without applying anything."""

    def __init__(self, *, requests: SettingsChangeRequestService | None = None) -> None:
        self.requests = requests or SettingsChangeRequestService()

    def simulate(
        self,
        db: Session,
        settings: Settings,
        *,
        filters: SettingsExecutionPreflightFilters | None = None,
    ) -> SettingsExecutionPreflight:
        halt_before = read_operator_halt(db)
        listed = self.requests.list_requests(db, settings)
        pending_packets, approved_packets = _packet_decision_counts(db)
        simulated_at = datetime.now(tz=UTC)
        selected = _parse_filters(filters)
        items = tuple(
            _simulate_item(
                item,
                settings=settings,
                halt=halt_before,
                pending_packets=pending_packets,
                approved_packets=approved_packets,
                simulated_at=simulated_at,
            )
            for item in listed.requests
        )
        visible = tuple(item for item in items if _matches_filters(item, selected))
        halt_after = read_operator_halt(db)
        if halt_after is not halt_before:
            raise RuntimeError("settings execution preflight must not change operator halt status")
        result = _to_result(
            visible,
            settings=settings,
            halt_before=halt_before,
            halt_after=halt_after,
            pending_packets=pending_packets,
            approved_packets=approved_packets,
            generated_at=simulated_at,
        )
        logger.info(
            "settings_execution_preflight_simulated",
            request_count=result.request_count,
            overall_status=result.overall_status,
            dry_run_only=True,
            no_execution=True,
            executed=0,
            settings_applied=False,
            live_action=False,
            execution_allowed=False,
            future_execution_phase_exists=False,
        )
        return result


def format_settings_execution_preflight(
    result: SettingsExecutionPreflight,
    *,
    as_json: bool = False,
) -> str:
    payload = sanitize_mapping(preflight_payload(result))
    if as_json:
        return json.dumps(payload, sort_keys=True)
    lines = [
        "Settings execution preflight:",
        f"overall={payload['overall_status']}",
        f"requests={payload['request_count']}",
        f"pending_decisions={payload['pending_decision_count']}",
        f"approved_decisions={payload['approved_decision_count']}",
        f"blocked={payload['blocked_count']}",
        f"executable={payload['executable_count']}",
        f"record_only={_bool_text(payload['record_only'])}",
        f"no_execution={_bool_text(payload['no_execution'])}",
        f"dry_run_only={_bool_text(payload['dry_run_only'])}",
        f"executed={payload['executed']}",
        f"settings_applied={_bool_text(payload['settings_applied'])}",
        f"halt_changed={_bool_text(payload['halt_changed'])}",
        f"owner_approved={_bool_text(payload['owner_approved'])}",
        f"live_action={_bool_text(payload['live_action'])}",
        f"execution_allowed={_bool_text(payload['execution_allowed'])}",
        (
            "future_execution_phase_exists="
            f"{_bool_text(payload['future_execution_phase_exists'])}"
        ),
        (
            "Operator halt: "
            f"status={payload['operator_halt_status']} "
            f"before={payload['operator_halt_before']} "
            f"after={payload['operator_halt_after']}"
        ),
        f"Outbound: enabled={_bool_text(payload['outbound_enabled'])}",
        f"Live providers: enabled={_bool_text(payload['live_providers_enabled'])}",
        (
            "Approval packets: "
            f"pending={payload['pending_owner_approval_packet_count']} "
            f"approved={payload['approved_owner_approval_packet_count']}"
        ),
        f"blocker_codes={_format_codes(result.blocker_codes)}",
        f"missing_approval_codes={_format_codes(result.missing_approval_codes)}",
        f"missing_gate_codes={_format_codes(result.missing_gate_codes)}",
        f"missing_credential_names={_format_codes(result.missing_credential_names)}",
        f"closed_provider_flag_names={_format_codes(result.closed_provider_flag_names)}",
    ]
    for item in result.requests:
        lines.append(_format_item_line(item))
    return "\n".join(lines)


def preflight_payload(result: SettingsExecutionPreflight) -> dict[str, Any]:
    return {
        "generated_at": result.generated_at.isoformat(),
        "overall_status": result.overall_status,
        "request_count": result.request_count,
        "pending_decision_count": result.pending_decision_count,
        "approved_decision_count": result.approved_decision_count,
        "rejected_or_needs_changes_count": result.rejected_or_needs_changes_count,
        "blocked_count": result.blocked_count,
        "executable_count": 0,
        "by_request_type": dict(result.by_request_type),
        "by_decision_status": dict(result.by_decision_status),
        "by_execution_status": dict(result.by_execution_status),
        "blocker_codes": list(result.blocker_codes),
        "missing_approval_codes": list(result.missing_approval_codes),
        "missing_gate_codes": list(result.missing_gate_codes),
        "missing_credential_names": list(result.missing_credential_names),
        "closed_provider_flag_names": list(result.closed_provider_flag_names),
        "record_only": True,
        "no_execution": True,
        "dry_run_only": True,
        "executed": 0,
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
        "execution_allowed": False,
        "future_execution_phase_exists": False,
        "outbound_enabled": result.outbound_enabled,
        "live_providers_enabled": result.live_providers_enabled,
        "operator_halt_status": result.operator_halt_status,
        "operator_halt_before": result.operator_halt_before,
        "operator_halt_after": result.operator_halt_after,
        "pending_owner_approval_packet_count": result.pending_owner_approval_packet_count,
        "approved_owner_approval_packet_count": result.approved_owner_approval_packet_count,
        "requests": [item_payload(item) for item in result.requests],
    }


def item_payload(item: SettingsExecutionPreflightItem) -> dict[str, Any]:
    return {
        "request_id": str(item.request_id),
        "request_type": item.request_type,
        "request_status": item.request_status,
        "decision_status": item.decision_status,
        "requested_setting_names": list(item.requested_setting_names),
        "desired_boolean": item.desired_boolean,
        "desired_status": item.desired_status,
        "execution_status": item.execution_status,
        "blocker_codes": list(item.blocker_codes),
        "missing_approval_codes": list(item.missing_approval_codes),
        "missing_gate_codes": list(item.missing_gate_codes),
        "missing_credential_names": list(item.missing_credential_names),
        "closed_provider_flag_names": list(item.closed_provider_flag_names),
        "requested_at": item.requested_at.isoformat(),
        "simulated_at": item.simulated_at.isoformat(),
        "record_only": True,
        "no_execution": True,
        "dry_run_only": True,
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
        "execution_allowed": False,
        "future_execution_phase_exists": False,
    }


def _simulate_item(
    item: SettingsChangeRequestView,
    *,
    settings: Settings,
    halt: HaltStatus,
    pending_packets: int,
    approved_packets: int,
    simulated_at: datetime,
) -> SettingsExecutionPreflightItem:
    missing_credentials = _missing_credential_names(item, settings)
    closed_flags = _closed_provider_flag_names(settings)
    blocker_codes, missing_approvals, missing_gates = _item_codes(
        settings=settings,
        halt=halt,
        missing_credentials=missing_credentials,
        closed_flags=closed_flags,
        pending_packets=pending_packets,
        approved_packets=approved_packets,
        decision_status=item.owner_decision_status,
    )
    return SettingsExecutionPreflightItem(
        request_id=item.request_id,
        request_type=item.request_type,
        request_status=item.status,
        decision_status=item.owner_decision_status,
        requested_setting_names=item.requested_setting_names,
        desired_boolean=item.desired_boolean,
        desired_status=item.desired_status,
        execution_status=_execution_status(blocker_codes),
        blocker_codes=blocker_codes,
        missing_approval_codes=missing_approvals,
        missing_gate_codes=missing_gates,
        missing_credential_names=missing_credentials,
        closed_provider_flag_names=closed_flags,
        requested_at=item.requested_at,
        simulated_at=simulated_at,
        record_only=True,
        no_execution=True,
        dry_run_only=True,
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
        execution_allowed=False,
        future_execution_phase_exists=False,
    )


def _item_codes(
    *,
    settings: Settings,
    halt: HaltStatus,
    missing_credentials: Sequence[str],
    closed_flags: Sequence[str],
    pending_packets: int,
    approved_packets: int,
    decision_status: str | None,
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    blockers: list[str] = [
        SettingsExecutionBlockerCode.EXECUTION_DISABLED_IN_THIS_PHASE.value,
        SettingsExecutionBlockerCode.FUTURE_EXECUTION_PHASE_ABSENT.value,
        SettingsExecutionBlockerCode.MISSING_EXPLICIT_OWNER_APPROVAL.value,
    ]
    approvals: list[str] = [
        SettingsExecutionBlockerCode.MISSING_EXPLICIT_OWNER_APPROVAL.value,
    ]
    gates: list[str] = [
        SettingsExecutionGateCode.EXECUTION_PHASE_GATE.value,
        SettingsExecutionGateCode.EXPLICIT_OWNER_APPROVAL_GATE.value,
    ]
    match halt:
        case HaltStatus.HALTED:
            blockers.append(SettingsExecutionBlockerCode.OPERATOR_HALT_ACTIVE.value)
            gates.append(SettingsExecutionGateCode.OPERATOR_HALT_GATE.value)
        case HaltStatus.UNAVAILABLE:
            blockers.append(SettingsExecutionBlockerCode.OPERATOR_HALT_UNAVAILABLE.value)
            gates.append(SettingsExecutionGateCode.OPERATOR_HALT_GATE.value)
        case HaltStatus.CLEARED:
            pass
        case _:
            _unreachable(halt)
    if not settings.outbound_enabled:
        blockers.append(SettingsExecutionBlockerCode.OUTBOUND_DISABLED.value)
        gates.append(SettingsExecutionGateCode.OUTBOUND_ENABLED_GATE.value)
    if closed_flags:
        blockers.append(SettingsExecutionBlockerCode.PROVIDER_LIVE_FLAG_FALSE.value)
        gates.append(SettingsExecutionGateCode.PROVIDER_LIVE_FLAG_GATE.value)
    if missing_credentials:
        blockers.append(SettingsExecutionBlockerCode.MISSING_CREDENTIAL.value)
        gates.append(SettingsExecutionGateCode.CREDENTIAL_GATE.value)
    if decision_status is not None:
        _append_decision_codes(decision_status, blockers, approvals, gates)
    if pending_packets > 0 or approved_packets == 0:
        blockers.append(
            SettingsExecutionBlockerCode.MISSING_OWNER_APPROVAL_PACKET_DECISION.value
        )
        approvals.append(
            SettingsExecutionBlockerCode.MISSING_OWNER_APPROVAL_PACKET_DECISION.value
        )
        gates.append(SettingsExecutionGateCode.APPROVAL_PACKET_DECISION_GATE.value)
    return (
        _unique_sorted(blockers),
        _unique_sorted(approvals),
        _unique_sorted(gates),
    )


def _append_decision_codes(
    decision_status: str,
    blockers: list[str],
    approvals: list[str],
    gates: list[str],
) -> None:
    try:
        decision = SettingsChangeDecisionStatus(decision_status)
    except ValueError:
        decision = SettingsChangeDecisionStatus.PENDING
    match decision:
        case SettingsChangeDecisionStatus.PENDING:
            blockers.append(SettingsExecutionBlockerCode.PENDING_DECISION.value)
            approvals.append(SettingsExecutionBlockerCode.PENDING_DECISION.value)
            gates.append(SettingsExecutionGateCode.OWNER_DECISION_GATE.value)
        case SettingsChangeDecisionStatus.REJECTED:
            blockers.append(SettingsExecutionBlockerCode.REJECTED_DECISION.value)
            approvals.append(SettingsExecutionBlockerCode.REJECTED_DECISION.value)
            gates.append(SettingsExecutionGateCode.OWNER_DECISION_GATE.value)
        case SettingsChangeDecisionStatus.NEEDS_CHANGES:
            blockers.append(SettingsExecutionBlockerCode.NEEDS_CHANGES_DECISION.value)
            approvals.append(SettingsExecutionBlockerCode.NEEDS_CHANGES_DECISION.value)
            gates.append(SettingsExecutionGateCode.OWNER_DECISION_GATE.value)
        case SettingsChangeDecisionStatus.APPROVED:
            pass
        case _:
            _unreachable(decision)


def _execution_status(blocker_codes: Sequence[str]) -> str:
    codes = set(blocker_codes)
    if SettingsExecutionBlockerCode.PENDING_DECISION.value in codes:
        return SettingsExecutionPreflightStatus.PENDING_DECISION.value
    if (
        SettingsExecutionBlockerCode.REJECTED_DECISION.value in codes
        or SettingsExecutionBlockerCode.NEEDS_CHANGES_DECISION.value in codes
    ):
        return SettingsExecutionPreflightStatus.DECISION_NOT_APPROVED.value
    if codes & GATE_BLOCKERS:
        return SettingsExecutionPreflightStatus.EXECUTION_GATES_CLOSED.value
    if SettingsExecutionBlockerCode.MISSING_OWNER_APPROVAL_PACKET_DECISION.value in codes:
        return SettingsExecutionPreflightStatus.MISSING_OWNER_PACKET_DECISION.value
    if SettingsExecutionBlockerCode.MISSING_EXPLICIT_OWNER_APPROVAL.value in codes:
        return SettingsExecutionPreflightStatus.MISSING_EXPLICIT_OWNER_APPROVAL.value
    return SettingsExecutionPreflightStatus.DRY_RUN_BLOCKED.value


def _to_result(
    items: Sequence[SettingsExecutionPreflightItem],
    *,
    settings: Settings,
    halt_before: HaltStatus,
    halt_after: HaltStatus,
    pending_packets: int,
    approved_packets: int,
    generated_at: datetime,
) -> SettingsExecutionPreflight:
    pending_decisions = sum(
        1
        for item in items
        if item.decision_status == SettingsChangeDecisionStatus.PENDING.value
    )
    approved_decisions = sum(
        1
        for item in items
        if item.decision_status == SettingsChangeDecisionStatus.APPROVED.value
    )
    rejected_or_needs_changes = sum(
        1
        for item in items
        if item.decision_status
        in {
            SettingsChangeDecisionStatus.REJECTED.value,
            SettingsChangeDecisionStatus.NEEDS_CHANGES.value,
        }
    )
    missing_credentials = _unique_sorted(
        name for item in items for name in item.missing_credential_names
    )
    if not items:
        missing_credentials = _unique_sorted(_missing_live_credentials(settings))
    closed_flags = _closed_provider_flag_names(settings)
    global_blockers = _unique_sorted(
        code for item in items for code in item.blocker_codes
    )
    global_approvals = _unique_sorted(
        code for item in items for code in item.missing_approval_codes
    )
    global_gates = _unique_sorted(code for item in items for code in item.missing_gate_codes)
    if not items:
        empty_item = _empty_queue_codes(
            settings=settings,
            halt=halt_before,
            pending_packets=pending_packets,
            approved_packets=approved_packets,
        )
        global_blockers, global_approvals, global_gates = empty_item
    return SettingsExecutionPreflight(
        generated_at=generated_at,
        overall_status=SettingsExecutionPreflightStatus.BLOCKED.value,
        request_count=len(items),
        pending_decision_count=pending_decisions,
        approved_decision_count=approved_decisions,
        rejected_or_needs_changes_count=rejected_or_needs_changes,
        blocked_count=len(items),
        executable_count=0,
        by_request_type=_count_by(items, lambda item: item.request_type),
        by_decision_status=_count_by(items, lambda item: item.decision_status),
        by_execution_status=_count_by(items, lambda item: item.execution_status),
        blocker_codes=global_blockers,
        missing_approval_codes=global_approvals,
        missing_gate_codes=global_gates,
        missing_credential_names=missing_credentials,
        closed_provider_flag_names=closed_flags,
        record_only=True,
        no_execution=True,
        dry_run_only=True,
        executed=0,
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
        execution_allowed=False,
        future_execution_phase_exists=FUTURE_EXECUTION_PHASE_EXISTS,
        outbound_enabled=settings.outbound_enabled,
        live_providers_enabled=any_live_provider_enabled(settings),
        operator_halt_status=halt_after.value,
        operator_halt_before=halt_before.value,
        operator_halt_after=halt_after.value,
        pending_owner_approval_packet_count=pending_packets,
        approved_owner_approval_packet_count=approved_packets,
        requests=tuple(items),
    )


def _empty_queue_codes(
    *,
    settings: Settings,
    halt: HaltStatus,
    pending_packets: int,
    approved_packets: int,
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    return _item_codes(
        settings=settings,
        halt=halt,
        missing_credentials=_missing_live_credentials(settings),
        closed_flags=_closed_provider_flag_names(settings),
        pending_packets=pending_packets,
        approved_packets=approved_packets,
        decision_status=None,
    )


def _missing_credential_names(
    item: SettingsChangeRequestView,
    settings: Settings,
) -> tuple[str, ...]:
    names: list[str] = []
    for setting_name in item.requested_setting_names:
        if setting_name in CREDENTIAL_SETTINGS and not _secret_present(setting_name, settings):
            names.append(setting_name)
        credential = FLAG_CREDENTIALS.get(setting_name)
        if credential is not None and not _secret_present(credential, settings):
            names.append(credential)
    if item.request_type in {
        SettingsChangeRequestType.REQUEST_OUTBOUND_ENABLEMENT_REVIEW.value,
        SettingsChangeRequestType.KEEP_SAFE_DEFAULT.value,
        SettingsChangeRequestType.REQUEST_PROVIDER_LIVE_FLAG_REVIEW.value,
    }:
        names.extend(_missing_live_credentials(settings))
    return _unique_sorted(names)


def _missing_live_credentials(settings: Settings) -> tuple[str, ...]:
    return _unique_sorted(
        name for name in LIVE_CREDENTIAL_NAMES if not _secret_present(name, settings)
    )


def _secret_present(name: str, settings: Settings) -> bool:
    try:
        secret = SecretName(name)
    except ValueError:
        return True
    match secret:
        case SecretName.DATABASE_URL:
            return bool(settings.database_url.strip())
        case SecretName.INTERNAL_API_KEY:
            return bool(settings.internal_api_key.strip())
        case SecretName.OPENAI_API_KEY:
            return bool(settings.openai_api_key.strip())
        case SecretName.SMARTLEAD_API_KEY:
            return bool(settings.smartlead_api_key.strip())
        case SecretName.GOOGLE_CALENDAR_API_KEY:
            return bool(settings.google_calendar_api_key.strip())
        case SecretName.VOICE_API_KEY:
            return bool(settings.voice_api_key.strip())
        case SecretName.DECISION_MAKER_API_KEY:
            return bool(settings.decision_maker_api_key.strip())
        case _:
            return _unreachable(secret)


def _closed_provider_flag_names(settings: Settings) -> tuple[str, ...]:
    names: list[str] = []
    for name in sorted(LIVE_PROVIDER_FLAG_SETTINGS):
        if _flag_enabled(name, settings) is False:
            names.append(name)
    return tuple(names)


def _flag_enabled(name: str, settings: Settings) -> bool | None:
    mapping = {
        "OUTBOUND_ENABLED": settings.outbound_enabled,
        "OPENAI_PERSONALIZATION_ENABLED": settings.openai_personalization_enabled,
        "SMARTLEAD_LIVE_ENABLED": settings.smartlead_live_enabled,
        "OPENAI_REPLY_CLASSIFICATION_ENABLED": settings.openai_reply_classification_enabled,
        "GOOGLE_CALENDAR_LIVE_ENABLED": settings.google_calendar_live_enabled,
        "VOICE_LIVE_ENABLED": settings.voice_live_enabled,
        "DECISION_MAKER_LIVE_ENABLED": settings.decision_maker_live_enabled,
    }
    return mapping.get(name)


def _packet_decision_counts(db: Session) -> tuple[int, int]:
    packet_count = int(db.scalar(select(func.count()).select_from(OwnerApprovalPacket)) or 0)
    decided_count = int(
        db.scalar(select(func.count()).select_from(OwnerApprovalPacketDecision)) or 0
    )
    approved_count = int(
        db.scalar(
            select(func.count())
            .select_from(OwnerApprovalPacketDecision)
            .where(OwnerApprovalPacketDecision.decision == ReviewDecisionStatus.APPROVED.value)
        )
        or 0
    )
    pending = max(packet_count - decided_count, 0)
    return pending, approved_count


def _parse_filters(
    filters: SettingsExecutionPreflightFilters | None,
) -> SettingsExecutionPreflightFilters:
    selected = filters or SettingsExecutionPreflightFilters()
    return SettingsExecutionPreflightFilters(
        request_type=_allowed_or_none(selected.request_type, REQUEST_TYPES),
        decision_status=_allowed_or_none(selected.decision_status, DECISION_STATUSES),
        execution_status=_allowed_or_none(selected.execution_status, EXECUTION_STATUSES),
    )


def _allowed_or_none(value: str | None, allowed: frozenset[str]) -> str | None:
    if value is None or not value.strip():
        return None
    cleaned = value.strip()
    if cleaned in allowed:
        return cleaned
    return None


def _matches_filters(
    item: SettingsExecutionPreflightItem,
    filters: SettingsExecutionPreflightFilters,
) -> bool:
    if filters.request_type is not None and item.request_type != filters.request_type:
        return False
    if filters.decision_status is not None and item.decision_status != filters.decision_status:
        return False
    if (
        filters.execution_status is not None
        and item.execution_status != filters.execution_status
    ):
        return False
    return True


def _format_item_line(item: SettingsExecutionPreflightItem) -> str:
    names = ",".join(item.requested_setting_names) or "-"
    desired = "null" if item.desired_boolean is None else _bool_text(item.desired_boolean)
    return (
        "Request: "
        f"id={item.request_id} "
        f"type={item.request_type} "
        f"decision={item.decision_status} "
        f"execution={item.execution_status} "
        f"settings={names} "
        f"desired_boolean={desired} "
        f"desired_status={item.desired_status or '-'} "
        f"blockers={_format_codes(item.blocker_codes)} "
        f"gates={_format_codes(item.missing_gate_codes)} "
        f"executed={_bool_text(item.executed)} "
        f"settings_applied={_bool_text(item.settings_applied)} "
        f"execution_allowed={_bool_text(item.execution_allowed)} "
        f"no_execution={_bool_text(item.no_execution)}"
    )


def _format_codes(values: Sequence[str]) -> str:
    return ",".join(values) if values else "-"


def _unique_sorted(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(sorted(set(values)))


def _count_by(
    items: Sequence[SettingsExecutionPreflightItem],
    key: Callable[[SettingsExecutionPreflightItem], str],
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        value = str(key(item))
        counts[value] = counts.get(value, 0) + 1
    return counts


def _bool_text(value: object) -> str:
    return "true" if value else "false"


def _unreachable(value: object) -> Never:
    raise RuntimeError(f"unhandled settings execution preflight variant: {value!r}")
