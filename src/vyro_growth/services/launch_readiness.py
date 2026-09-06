"""Read-only launch readiness checklist and sanitized secret inventory.

Phase 27 inspects local config, operator halt, stored approval packets, the
action-readiness queue, and the documented CI smoke gate. It never executes
approved items, calls live providers, prints secret values, or changes
outbound / live-provider / halt settings.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Never

import structlog
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from vyro_growth.config import (
    Settings,
    any_live_provider_enabled,
    is_development_environment,
    live_provider_flags,
    validate_runtime_settings,
)
from vyro_growth.domain import (
    ActionReadinessBlockerStatus,
    FindingCode,
    FindingSeverity,
    LaunchReadinessStatus,
    NextActionCode,
    SecretName,
    SecretPresenceStatus,
)
from vyro_growth.models import OwnerApprovalPacket, OwnerApprovalPacketDecision
from vyro_growth.observability import sanitize_mapping, sanitize_operator_text
from vyro_growth.services.action_readiness import ActionReadinessService
from vyro_growth.services.operator_halt import HaltStatus, read_operator_halt
from vyro_growth.services.readiness import database_is_ready
from vyro_growth.services.settings_change_requests import (
    SettingsChangeProposal,
    pending_settings_change_request_count,
)

logger = structlog.get_logger(__name__)

CI_SMOKE_JOB = "smoke-dry-run"
CI_SMOKE_RUN = "vyro-growth smoke-dry-run --local-only --json"
CI_SMOKE_CHECK = "vyro-growth check-smoke-output --file"
CI_WORKFLOW_RELATIVE = Path(".github") / "workflows" / "ci.yml"
REQUIRED_FLAG_NAMES: tuple[str, ...] = (
    "OUTBOUND_ENABLED",
    "OPENAI_PERSONALIZATION_ENABLED",
    "SMARTLEAD_LIVE_ENABLED",
    "OPENAI_REPLY_CLASSIFICATION_ENABLED",
    "GOOGLE_CALENDAR_LIVE_ENABLED",
    "VOICE_LIVE_ENABLED",
)
REQUIRED_CONFIG_NAMES: tuple[str, ...] = (
    *REQUIRED_FLAG_NAMES,
    *(item.value for item in SecretName),
)
_SEVERITY_RANK = {
    FindingSeverity.INFO: 0,
    FindingSeverity.WARNING: 1,
    FindingSeverity.BLOCKED: 2,
}
_NEXT_ACTION_LABELS: dict[NextActionCode, str] = {
    NextActionCode.DISABLE_OUTBOUND: (
        "Set OUTBOUND_ENABLED=false. Do not treat this as owner-approved live launch."
    ),
    NextActionCode.DISABLE_LIVE_PROVIDERS: (
        "Disable live-provider flags. They are not owner-approved for live use."
    ),
    NextActionCode.RECORD_OPERATOR_HALT: (
        "Record the persistent operator halt before any launch review."
    ),
    NextActionCode.KEEP_OPERATOR_HALT: (
        "Keep operator halt active until a separate explicit owner action."
    ),
    NextActionCode.CHECK_RUNTIME_CONFIG: (
        "Run vyro-growth check-config. Do not print secret values."
    ),
    NextActionCode.CONFIGURE_REQUIRED_CREDENTIALS: (
        "Configure the named required credential in local env. Do not paste values here."
    ),
    NextActionCode.RESTORE_CI_SMOKE_GATE: (
        "Restore the documented CI smoke-dry-run job and check-smoke-output gate."
    ),
    NextActionCode.OWNER_REVIEW_APPROVAL_PACKETS: (
        "Owner-review pending approval packets. Recording a decision does not execute."
    ),
    NextActionCode.INSPECT_ACTION_READINESS: (
        "Inspect blocked action-readiness candidates. Read-only; do not execute."
    ),
    NextActionCode.KEEP_OUTBOUND_DISABLED: "Keep OUTBOUND_ENABLED=false.",
    NextActionCode.KEEP_LIVE_PROVIDERS_DISABLED: "Keep every live-provider flag disabled.",
    NextActionCode.REVIEW_SETTINGS_CHANGE_REQUESTS: (
        "Review pending live settings change requests at "
        "/internal/operator-settings-change-requests. "
        "Inspect remaining execution blockers at "
        "/internal/operator-settings-execution-preflight. "
        "Recording a decision does not apply them."
    ),
    NextActionCode.INSPECT_SETTINGS_EXECUTION_PREFLIGHT: (
        "Inspect remaining settings-execution blockers at "
        "/internal/operator-settings-execution-preflight. "
        "Read-only dry-run view; do not execute."
    ),
    NextActionCode.INSPECT_OPERATOR_AUDIT_TIMELINE: (
        "Inspect the operator activity audit timeline at "
        "/internal/operator-audit-timeline. Read-only; do not execute."
    ),
    NextActionCode.HANDOFF_IS_NOT_GO_LIVE: (
        "Inspect the owner go-live handoff packet at "
        "/internal/operator-owner-handoff-packet. "
        "Read-only manual-review view; it is not permission or machinery "
        "for going live."
    ),
    NextActionCode.BINDER_IS_NOT_GO_LIVE: (
        "Inspect the compliance evidence binder at "
        "/internal/operator-compliance-evidence-binder. "
        "Read-only owner-review view; it is not permission or machinery "
        "for going live."
    ),
    NextActionCode.RUNBOOK_IS_NOT_DEPLOYMENT: (
        "Inspect the release-candidate deployment runbook at "
        "/internal/operator-release-candidate-runbook. "
        "Read-only owner-review view; it is not a deployment mechanism or "
        "permission to go live."
    ),
    NextActionCode.MANIFEST_IS_NOT_BUILD_OR_DEPLOY: (
        "Inspect the release artifact manifest at "
        "/internal/operator-release-artifact-manifest. "
        "Read-only owner-review view; it is not a build, artifact "
        "publishing, or deployment mechanism."
    ),
    NextActionCode.GO_LIVE_READINESS_INDEX_IS_NOT_PERMISSION: (
        "Inspect the go-live readiness index at "
        "/internal/operator-go-live-readiness-index. "
        "Read-only owner-review view; it is not permission to go live "
        "and is not an execution surface."
    ),
    NextActionCode.LAUNCH_BLOCKERS_PLAN_IS_NOT_PERMISSION: (
        "Inspect the launch blockers remediation plan at "
        "/internal/operator-launch-blockers-plan or "
        "/internal/launch-blockers-plan or via `vyro-growth "
        "launch-blockers-plan`. Read-only planning view; it is not "
        "permission to go live and is not an execution surface."
    ),
    NextActionCode.STAGED_ROLLOUT_PLAN_IS_NOT_GO_LIVE: (
        "Inspect the staged go-live rollout plan at "
        "/internal/staged-rollout-plan or via `vyro-growth "
        "staged-rollout-plan`. Read-only staged planning export; it is "
        "not permission to go live and is not an execution surface."
    ),
}


@dataclass(frozen=True)
class SecretInventoryItem:
    name: str
    present: bool
    status: str
    required: bool


@dataclass(frozen=True)
class ConfigFlagStatus:
    name: str
    enabled: bool


@dataclass(frozen=True)
class CiSmokeGateStatus:
    present: bool
    documented: bool
    job_name: str


@dataclass(frozen=True)
class LaunchReadinessFinding:
    severity: str
    code: str
    next_action_code: str
    next_action_label: str


@dataclass(frozen=True)
class LaunchReadinessChecklist:
    generated_at: datetime
    overall_status: str
    read_only: bool
    no_execution: bool
    executed: int
    live_action: bool
    outbound_attempted: bool
    owner_approved: bool
    operator_halt_status: str
    operator_halt_before: str
    operator_halt_after: str
    outbound_enabled: bool
    live_providers_enabled: bool
    live_providers: dict[str, bool]
    config_ok: bool
    required_config_names: tuple[str, ...]
    config_flags: tuple[ConfigFlagStatus, ...]
    secret_inventory: tuple[SecretInventoryItem, ...]
    ci_smoke_gate: CiSmokeGateStatus
    pending_owner_approval_packets: int
    action_readiness_candidate_count: int
    action_readiness_blocked_count: int
    pending_settings_change_request_count: int
    proposed_settings_change_requests: tuple[SettingsChangeProposal, ...]
    findings: tuple[LaunchReadinessFinding, ...]
    next_actions: tuple[LaunchReadinessFinding, ...]
    database: str
    environment: str


class LaunchReadinessService:
    """Compose existing read-only checks into a sanitized launch checklist."""

    def __init__(self, *, action_readiness: ActionReadinessService | None = None) -> None:
        self.action_readiness = action_readiness or ActionReadinessService()

    def assess(
        self,
        db: Session,
        settings: Settings,
        *,
        repo_root: Path | None = None,
    ) -> LaunchReadinessChecklist:
        halt_before = HaltStatus.UNAVAILABLE
        pending_packets = 0
        candidate_count = 0
        blocked_count = 0
        pending_settings_requests = 0
        db_ok = database_is_ready(db)
        if db_ok:
            try:
                halt_before = read_operator_halt(db)
                pending_packets = _pending_packet_count(db)
                pending_settings_requests = pending_settings_change_request_count(db)
                queue = self.action_readiness.list_queue(db, settings)
                candidate_count = queue.candidate_count
                blocked_count = sum(
                    1
                    for item in queue.candidates
                    if item.blocker_status == ActionReadinessBlockerStatus.BLOCKED.value
                )
            except SQLAlchemyError:
                db_ok = False
                halt_before = HaltStatus.UNAVAILABLE
                pending_packets = 0
                candidate_count = 0
                blocked_count = 0
                pending_settings_requests = 0
        halt_after = read_operator_halt(db) if db_ok else HaltStatus.UNAVAILABLE
        if halt_after is not halt_before:
            raise RuntimeError("launch readiness must not change operator halt status")

        smoke = inspect_ci_smoke_gate(repo_root or default_repo_root())
        inventory = _secret_inventory(settings)
        flags = _config_flags(settings)
        live_flags = live_provider_flags(settings)
        config_issues = validate_runtime_settings(settings)
        findings = _findings(
            settings=settings,
            halt=halt_before,
            db_ok=db_ok,
            config_issues=config_issues,
            inventory=inventory,
            smoke=smoke,
            pending_packets=pending_packets,
            blocked_count=blocked_count,
            pending_settings_requests=pending_settings_requests,
        )
        next_actions = _next_actions(findings, settings)
        proposals = _proposed_settings_changes(next_actions, inventory)
        overall = _overall_status(findings)
        checklist = LaunchReadinessChecklist(
            generated_at=datetime.now(tz=UTC),
            overall_status=overall.value,
            read_only=True,
            no_execution=True,
            executed=0,
            live_action=False,
            outbound_attempted=False,
            owner_approved=False,
            operator_halt_status=halt_before.value,
            operator_halt_before=halt_before.value,
            operator_halt_after=halt_after.value,
            outbound_enabled=settings.outbound_enabled,
            live_providers_enabled=any_live_provider_enabled(settings),
            live_providers=dict(live_flags),
            config_ok=not config_issues,
            required_config_names=REQUIRED_CONFIG_NAMES,
            config_flags=flags,
            secret_inventory=inventory,
            ci_smoke_gate=smoke,
            pending_owner_approval_packets=pending_packets,
            action_readiness_candidate_count=candidate_count,
            action_readiness_blocked_count=blocked_count,
            pending_settings_change_request_count=pending_settings_requests,
            proposed_settings_change_requests=proposals,
            findings=findings,
            next_actions=next_actions,
            database="ok" if db_ok else "unavailable",
            environment=settings.environment,
        )
        logger.info(
            "launch_readiness_built",
            read_only=True,
            overall_status=checklist.overall_status,
            outbound_enabled=checklist.outbound_enabled,
            live_providers_enabled=checklist.live_providers_enabled,
            operator_halt_status=checklist.operator_halt_status,
            pending_owner_approval_packets=pending_packets,
            action_readiness_blocked_count=blocked_count,
            ci_smoke_gate_documented=smoke.documented,
            executed=0,
            live_action=False,
        )
        return checklist


def default_repo_root() -> Path:
    here = Path(__file__).resolve()
    candidates = (Path.cwd(), here.parents[3], here.parents[2])
    for candidate in candidates:
        if (candidate / CI_WORKFLOW_RELATIVE).is_file():
            return candidate
    return Path.cwd()


def inspect_ci_smoke_gate(repo_root: Path) -> CiSmokeGateStatus:
    """Inspect the local CI workflow file. Does not call GitHub Actions."""

    path = repo_root / CI_WORKFLOW_RELATIVE
    if not path.is_file():
        return CiSmokeGateStatus(present=False, documented=False, job_name="missing")
    text = path.read_text(encoding="utf-8")
    documented = (
        f"{CI_SMOKE_JOB}:" in text and CI_SMOKE_RUN in text and CI_SMOKE_CHECK in text
    )
    return CiSmokeGateStatus(
        present=True,
        documented=documented,
        job_name=CI_SMOKE_JOB if documented else "missing",
    )


def format_launch_readiness(checklist: LaunchReadinessChecklist, *, as_json: bool = False) -> str:
    payload = sanitize_mapping(checklist_payload(checklist))
    if as_json:
        return json.dumps(payload, sort_keys=True)
    lines = [
        "Launch readiness:",
        f"overall={payload['overall_status']}",
        f"read_only={_bool_text(payload['read_only'])}",
        f"no_execution={_bool_text(payload['no_execution'])}",
        f"executed={payload['executed']}",
        f"live_action={_bool_text(payload['live_action'])}",
        f"outbound_attempted={_bool_text(payload['outbound_attempted'])}",
        f"owner_approved={_bool_text(payload['owner_approved'])}",
        (
            "Operator halt: "
            f"status={payload['operator_halt_status']} "
            f"before={payload['operator_halt_before']} "
            f"after={payload['operator_halt_after']}"
        ),
        f"Outbound: enabled={_bool_text(payload['outbound_enabled'])}",
        (
            "Live providers: "
            f"enabled={_bool_text(payload['live_providers_enabled'])} "
            f"flags={_format_mapping(payload['live_providers'])}"
        ),
        f"Config: ok={_bool_text(payload['config_ok'])} names={','.join(REQUIRED_CONFIG_NAMES)}",
        (
            "CI smoke gate: "
            f"present={_bool_text(payload['ci_smoke_gate']['present'])} "
            f"documented={_bool_text(payload['ci_smoke_gate']['documented'])} "
            f"job={payload['ci_smoke_gate']['job_name']}"
        ),
        f"Pending owner approval packets: {payload['pending_owner_approval_packets']}",
        (
            "Action readiness: "
            f"candidates={payload['action_readiness_candidate_count']} "
            f"blocked={payload['action_readiness_blocked_count']}"
        ),
        (
            "Settings change requests: "
            f"pending={payload['pending_settings_change_request_count']} "
            f"proposed={len(payload['proposed_settings_change_requests'])}"
        ),
        f"Database: {payload['database']}",
        f"Environment: {payload['environment']}",
    ]
    for item in checklist.secret_inventory:
        lines.append(
            "Secret: "
            f"name={item.name} present={_bool_text(item.present)} "
            f"status={item.status} required={_bool_text(item.required)}"
        )
    for finding in checklist.findings:
        lines.append(
            "Finding: "
            f"severity={finding.severity} code={finding.code} "
            f"next_action={finding.next_action_code} label={finding.next_action_label}"
        )
    for action in checklist.next_actions:
        lines.append(
            "Next action: "
            f"severity={action.severity} code={action.next_action_code} "
            f"label={action.next_action_label}"
        )
    for proposal in checklist.proposed_settings_change_requests:
        names = ",".join(proposal.requested_setting_names) or "-"
        desired = (
            "null" if proposal.desired_boolean is None else _bool_text(proposal.desired_boolean)
        )
        lines.append(
            "Proposed settings change: "
            f"type={proposal.request_type} "
            f"settings={names} "
            f"desired_boolean={desired} "
            f"desired_status={proposal.desired_status or '-'} "
            f"finding={proposal.finding_code or '-'} "
            f"next_action={proposal.next_action_code or '-'} "
            f"record_only={_bool_text(proposal.record_only)} "
            f"settings_applied={_bool_text(proposal.settings_applied)}"
        )
    return "\n".join(lines)


def checklist_payload(checklist: LaunchReadinessChecklist) -> dict[str, Any]:
    return {
        "generated_at": checklist.generated_at.isoformat(),
        "overall_status": checklist.overall_status,
        "read_only": True,
        "no_execution": True,
        "executed": 0,
        "live_action": False,
        "outbound_attempted": False,
        "owner_approved": False,
        "operator_halt_status": checklist.operator_halt_status,
        "operator_halt_before": checklist.operator_halt_before,
        "operator_halt_after": checklist.operator_halt_after,
        "outbound_enabled": checklist.outbound_enabled,
        "live_providers_enabled": checklist.live_providers_enabled,
        "live_providers": dict(checklist.live_providers),
        "config_ok": checklist.config_ok,
        "required_config_names": list(checklist.required_config_names),
        "config_flags": [
            {"name": item.name, "enabled": item.enabled} for item in checklist.config_flags
        ],
        "secret_inventory": [
            {
                "name": item.name,
                "present": item.present,
                "status": item.status,
                "required": item.required,
            }
            for item in checklist.secret_inventory
        ],
        "ci_smoke_gate": {
            "present": checklist.ci_smoke_gate.present,
            "documented": checklist.ci_smoke_gate.documented,
            "job_name": checklist.ci_smoke_gate.job_name,
        },
        "pending_owner_approval_packets": checklist.pending_owner_approval_packets,
        "action_readiness_candidate_count": checklist.action_readiness_candidate_count,
        "action_readiness_blocked_count": checklist.action_readiness_blocked_count,
        "pending_settings_change_request_count": checklist.pending_settings_change_request_count,
        "proposed_settings_change_requests": [
            {
                "request_type": item.request_type,
                "requested_setting_names": list(item.requested_setting_names),
                "desired_boolean": item.desired_boolean,
                "desired_status": item.desired_status,
                "finding_code": item.finding_code,
                "next_action_code": item.next_action_code,
                "record_only": True,
                "no_execution": True,
                "settings_applied": False,
            }
            for item in checklist.proposed_settings_change_requests
        ],
        "findings": [_finding_payload(item) for item in checklist.findings],
        "next_actions": [_finding_payload(item) for item in checklist.next_actions],
        "database": checklist.database,
        "environment": checklist.environment,
    }


def _finding_payload(item: LaunchReadinessFinding) -> dict[str, str]:
    return {
        "severity": item.severity,
        "code": item.code,
        "next_action_code": item.next_action_code,
        "next_action_label": item.next_action_label,
    }


def _secret_inventory(settings: Settings) -> tuple[SecretInventoryItem, ...]:
    items: list[SecretInventoryItem] = []
    for name in SecretName:
        present = _secret_present(name, settings)
        required = _secret_required(name, settings)
        items.append(
            SecretInventoryItem(
                name=name.value,
                present=present,
                status=(
                    SecretPresenceStatus.REDACTED.value
                    if present
                    else SecretPresenceStatus.MISSING.value
                ),
                required=required,
            )
        )
    return tuple(items)


def _secret_present(name: SecretName, settings: Settings) -> bool:
    match name:
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
        case _:
            return _unreachable(name)


def _secret_required(name: SecretName, settings: Settings) -> bool:
    match name:
        case SecretName.DATABASE_URL:
            return True
        case SecretName.INTERNAL_API_KEY:
            return not is_development_environment(settings)
        case SecretName.OPENAI_API_KEY:
            return (
                settings.openai_personalization_enabled
                or settings.openai_reply_classification_enabled
            )
        case SecretName.SMARTLEAD_API_KEY:
            return settings.smartlead_live_enabled
        case SecretName.GOOGLE_CALENDAR_API_KEY:
            return settings.google_calendar_live_enabled
        case SecretName.VOICE_API_KEY:
            return settings.voice_live_enabled
        case _:
            return _unreachable(name)


def _config_flags(settings: Settings) -> tuple[ConfigFlagStatus, ...]:
    return (
        ConfigFlagStatus(name="OUTBOUND_ENABLED", enabled=settings.outbound_enabled),
        ConfigFlagStatus(
            name="OPENAI_PERSONALIZATION_ENABLED",
            enabled=settings.openai_personalization_enabled,
        ),
        ConfigFlagStatus(name="SMARTLEAD_LIVE_ENABLED", enabled=settings.smartlead_live_enabled),
        ConfigFlagStatus(
            name="OPENAI_REPLY_CLASSIFICATION_ENABLED",
            enabled=settings.openai_reply_classification_enabled,
        ),
        ConfigFlagStatus(
            name="GOOGLE_CALENDAR_LIVE_ENABLED",
            enabled=settings.google_calendar_live_enabled,
        ),
        ConfigFlagStatus(name="VOICE_LIVE_ENABLED", enabled=settings.voice_live_enabled),
    )


def _pending_packet_count(db: Session) -> int:
    decided = select(OwnerApprovalPacketDecision.owner_approval_packet_id)
    return int(
        db.scalar(
            select(func.count())
            .select_from(OwnerApprovalPacket)
            .where(OwnerApprovalPacket.id.not_in(decided))
        )
        or 0
    )


def _findings(
    *,
    settings: Settings,
    halt: HaltStatus,
    db_ok: bool,
    config_issues: Sequence[str],
    inventory: Sequence[SecretInventoryItem],
    smoke: CiSmokeGateStatus,
    pending_packets: int,
    blocked_count: int,
    pending_settings_requests: int,
) -> tuple[LaunchReadinessFinding, ...]:
    items: list[LaunchReadinessFinding] = []
    if settings.outbound_enabled:
        items.append(
            _finding(
                FindingSeverity.BLOCKED,
                FindingCode.OUTBOUND_ENABLED,
                NextActionCode.DISABLE_OUTBOUND,
            )
        )
    if any_live_provider_enabled(settings):
        items.append(
            _finding(
                FindingSeverity.BLOCKED,
                FindingCode.LIVE_PROVIDER_ENABLED,
                NextActionCode.DISABLE_LIVE_PROVIDERS,
            )
        )
    if not db_ok:
        items.append(
            _finding(
                FindingSeverity.BLOCKED,
                FindingCode.DATABASE_UNAVAILABLE,
                NextActionCode.CHECK_RUNTIME_CONFIG,
            )
        )
    if config_issues:
        items.append(
            _finding(
                FindingSeverity.BLOCKED,
                FindingCode.CONFIG_NOT_READY,
                NextActionCode.CHECK_RUNTIME_CONFIG,
            )
        )
    missing_required = tuple(item.name for item in inventory if item.required and not item.present)
    if missing_required:
        items.append(
            _finding(
                FindingSeverity.BLOCKED,
                FindingCode.MISSING_REQUIRED_CREDENTIAL,
                NextActionCode.CONFIGURE_REQUIRED_CREDENTIALS,
                label=(
                    "Configure required credentials "
                    f"{','.join(missing_required)}. Values are never printed."
                ),
            )
        )
    if not smoke.documented:
        items.append(
            _finding(
                FindingSeverity.BLOCKED,
                FindingCode.SMOKE_GATE_MISSING,
                NextActionCode.RESTORE_CI_SMOKE_GATE,
            )
        )
    match halt:
        case HaltStatus.UNAVAILABLE:
            items.append(
                _finding(
                    FindingSeverity.BLOCKED,
                    FindingCode.OPERATOR_HALT_UNAVAILABLE,
                    NextActionCode.RECORD_OPERATOR_HALT,
                )
            )
        case HaltStatus.HALTED:
            items.append(
                _finding(
                    FindingSeverity.WARNING,
                    FindingCode.OPERATOR_HALT_ACTIVE,
                    NextActionCode.KEEP_OPERATOR_HALT,
                )
            )
        case HaltStatus.CLEARED:
            pass
        case _:
            _unreachable(halt)
    if pending_packets:
        items.append(
            _finding(
                FindingSeverity.WARNING,
                FindingCode.PENDING_OWNER_APPROVAL_PACKETS,
                NextActionCode.OWNER_REVIEW_APPROVAL_PACKETS,
                label=(
                    f"Owner-review {pending_packets} pending approval packet(s). "
                    "Recording a decision does not execute."
                ),
            )
        )
    if blocked_count:
        items.append(
            _finding(
                FindingSeverity.WARNING,
                FindingCode.ACTION_READINESS_BLOCKED,
                NextActionCode.INSPECT_ACTION_READINESS,
                label=(
                    f"Inspect {blocked_count} blocked action-readiness candidate(s). "
                    "Read-only; do not execute."
                ),
            )
        )
    if pending_settings_requests:
        items.append(
            _finding(
                FindingSeverity.WARNING,
                FindingCode.PENDING_SETTINGS_CHANGE_REQUESTS,
                NextActionCode.REVIEW_SETTINGS_CHANGE_REQUESTS,
                label=(
                    f"Review {pending_settings_requests} pending live settings "
                    "change request(s) at /internal/operator-settings-change-requests. "
                    "Inspect remaining execution blockers at "
                    "/internal/operator-settings-execution-preflight. "
                    "Recording a decision does not apply them."
                ),
            )
        )
    return tuple(items)


def _next_actions(
    findings: Sequence[LaunchReadinessFinding],
    settings: Settings,
) -> tuple[LaunchReadinessFinding, ...]:
    selected: dict[str, LaunchReadinessFinding] = {}

    def add(item: LaunchReadinessFinding) -> None:
        current = selected.get(item.next_action_code)
        if current is not None and _SEVERITY_RANK[FindingSeverity(current.severity)] >= (
            _SEVERITY_RANK[FindingSeverity(item.severity)]
        ):
            return
        selected[item.next_action_code] = item

    for finding in findings:
        add(finding)
    if not settings.outbound_enabled:
        add(
            _finding(
                FindingSeverity.INFO,
                FindingCode.SAFE_DEFAULTS,
                NextActionCode.KEEP_OUTBOUND_DISABLED,
            )
        )
    if not any_live_provider_enabled(settings):
        add(
            _finding(
                FindingSeverity.INFO,
                FindingCode.SAFE_DEFAULTS,
                NextActionCode.KEEP_LIVE_PROVIDERS_DISABLED,
            )
        )
    add(
        _finding(
            FindingSeverity.INFO,
            FindingCode.SAFE_DEFAULTS,
            NextActionCode.INSPECT_SETTINGS_EXECUTION_PREFLIGHT,
        )
    )
    add(
        _finding(
            FindingSeverity.INFO,
            FindingCode.SAFE_DEFAULTS,
            NextActionCode.INSPECT_OPERATOR_AUDIT_TIMELINE,
        )
    )
    add(
        _finding(
            FindingSeverity.INFO,
            FindingCode.SAFE_DEFAULTS,
            NextActionCode.HANDOFF_IS_NOT_GO_LIVE,
        )
    )
    add(
        _finding(
            FindingSeverity.INFO,
            FindingCode.SAFE_DEFAULTS,
            NextActionCode.RUNBOOK_IS_NOT_DEPLOYMENT,
        )
    )
    add(
        _finding(
            FindingSeverity.INFO,
            FindingCode.SAFE_DEFAULTS,
            NextActionCode.MANIFEST_IS_NOT_BUILD_OR_DEPLOY,
        )
    )
    add(
        _finding(
            FindingSeverity.INFO,
            FindingCode.SAFE_DEFAULTS,
            NextActionCode.GO_LIVE_READINESS_INDEX_IS_NOT_PERMISSION,
        )
    )
    add(
        _finding(
            FindingSeverity.INFO,
            FindingCode.SAFE_DEFAULTS,
            NextActionCode.LAUNCH_BLOCKERS_PLAN_IS_NOT_PERMISSION,
        )
    )
    add(
        _finding(
            FindingSeverity.INFO,
            FindingCode.SAFE_DEFAULTS,
            NextActionCode.STAGED_ROLLOUT_PLAN_IS_NOT_GO_LIVE,
        )
    )
    return tuple(
        sorted(
            selected.values(),
            key=lambda item: (
                -_SEVERITY_RANK[FindingSeverity(item.severity)],
                item.next_action_code,
            ),
        )
    )


def _proposed_settings_changes(
    next_actions: Sequence[LaunchReadinessFinding],
    inventory: Sequence[SecretInventoryItem],
) -> tuple[SettingsChangeProposal, ...]:
    missing_required = tuple(item.name for item in inventory if item.required and not item.present)
    live_flags = tuple(sorted(name for name in REQUIRED_FLAG_NAMES if name != "OUTBOUND_ENABLED"))
    proposals: list[SettingsChangeProposal] = []
    seen: set[str] = set()

    def add(item: SettingsChangeProposal) -> None:
        key = "|".join(
            (
                item.request_type,
                ",".join(item.requested_setting_names),
                str(item.desired_boolean),
                item.desired_status or "",
                item.next_action_code or "",
            )
        )
        if key in seen:
            return
        seen.add(key)
        proposals.append(item)

    for action in next_actions:
        code = action.next_action_code
        if code in {
            NextActionCode.KEEP_OUTBOUND_DISABLED.value,
            NextActionCode.DISABLE_OUTBOUND.value,
        }:
            add(
                SettingsChangeProposal(
                    request_type="keep_outbound_disabled",
                    requested_setting_names=("OUTBOUND_ENABLED",),
                    desired_boolean=False,
                    desired_status="disabled",
                    finding_code=action.code if code == NextActionCode.DISABLE_OUTBOUND.value else (
                        FindingCode.SAFE_DEFAULTS.value
                    ),
                    next_action_code=code,
                )
            )
        elif code in {
            NextActionCode.KEEP_LIVE_PROVIDERS_DISABLED.value,
            NextActionCode.DISABLE_LIVE_PROVIDERS.value,
        }:
            add(
                SettingsChangeProposal(
                    request_type="keep_safe_default",
                    requested_setting_names=live_flags,
                    desired_boolean=False,
                    desired_status="disabled",
                    finding_code=(
                        FindingCode.LIVE_PROVIDER_ENABLED.value
                        if code == NextActionCode.DISABLE_LIVE_PROVIDERS.value
                        else FindingCode.SAFE_DEFAULTS.value
                    ),
                    next_action_code=code,
                )
            )
        elif code in {
            NextActionCode.KEEP_OPERATOR_HALT.value,
            NextActionCode.RECORD_OPERATOR_HALT.value,
        }:
            add(
                SettingsChangeProposal(
                    request_type="request_operator_halt_review",
                    requested_setting_names=("OPERATOR_HALT",),
                    desired_boolean=True,
                    desired_status="halted",
                    finding_code=action.code,
                    next_action_code=code,
                )
            )
        elif code == NextActionCode.CONFIGURE_REQUIRED_CREDENTIALS.value and missing_required:
            add(
                SettingsChangeProposal(
                    request_type="request_credential_configuration_review",
                    requested_setting_names=missing_required,
                    desired_boolean=None,
                    desired_status="configured",
                    finding_code=FindingCode.MISSING_REQUIRED_CREDENTIAL.value,
                    next_action_code=code,
                )
            )
    return tuple(proposals)


def _finding(
    severity: FindingSeverity,
    code: FindingCode,
    next_action: NextActionCode,
    *,
    label: str | None = None,
) -> LaunchReadinessFinding:
    text = sanitize_operator_text(label or _NEXT_ACTION_LABELS[next_action])
    return LaunchReadinessFinding(
        severity=severity.value,
        code=code.value,
        next_action_code=next_action.value,
        next_action_label=text or _NEXT_ACTION_LABELS[next_action],
    )


def _overall_status(findings: Sequence[LaunchReadinessFinding]) -> LaunchReadinessStatus:
    if any(item.severity == FindingSeverity.BLOCKED.value for item in findings):
        return LaunchReadinessStatus.BLOCKED
    if any(item.severity == FindingSeverity.WARNING.value for item in findings):
        return LaunchReadinessStatus.WARNING
    return LaunchReadinessStatus.READY_FOR_OWNER_REVIEW


def _bool_text(value: object) -> str:
    return "true" if value else "false"


def _format_mapping(value: object) -> str:
    if not isinstance(value, dict):
        return "-"
    return ",".join(f"{key}={_bool_text(item)}" for key, item in sorted(value.items()))


def _unreachable(value: object) -> Never:
    raise RuntimeError(f"unhandled launch readiness variant: {value!r}")
