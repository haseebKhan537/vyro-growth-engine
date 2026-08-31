"""Read-only compliance evidence binder export.

Phase 35 consolidates existing safety evidence into one sanitized
Markdown/JSON packet for owner review. It never executes actions, applies
settings, lifts halt, enables outbound, calls providers, publishes,
deploys, spends, enrolls, books, places calls, or contacts anyone.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Never

import structlog
from sqlalchemy.orm import Session

from vyro_growth.config import Settings, any_live_provider_enabled, live_provider_flags
from vyro_growth.domain import FindingSeverity, NextActionCode, SecretPresenceStatus
from vyro_growth.observability import sanitize_mapping
from vyro_growth.services.dashboard import DashboardAnalyticsService, SafetyCard
from vyro_growth.services.launch_readiness import (
    CI_SMOKE_CHECK,
    CI_SMOKE_RUN,
    CI_WORKFLOW_RELATIVE,
    REQUIRED_FLAG_NAMES,
    LaunchReadinessChecklist,
    LaunchReadinessService,
    inspect_ci_smoke_gate,
)
from vyro_growth.services.operator_audit_timeline import (
    OperatorAuditTimeline,
    OperatorAuditTimelineService,
)
from vyro_growth.services.operator_halt import HaltStatus, read_operator_halt
from vyro_growth.services.owner_handoff import OwnerHandoffPacket, OwnerHandoffPacketService
from vyro_growth.services.settings_execution_preflight import (
    SettingsExecutionPreflight,
    SettingsExecutionPreflightService,
)
from vyro_growth.workers.catalog import undeployed_outbound_job_names
from vyro_growth.workers.outbound import PLACE_CONSENT_CALLBACK_JOB

logger = structlog.get_logger(__name__)

PACKET_KIND = "compliance_evidence_binder"
PACKET_PURPOSE = "manual_owner_review_only"
CLI_COMMAND = "compliance-evidence-binder"
HTTP_ROUTE = "/internal/compliance-evidence-binder"
BINDER_NOT_GO_LIVE_CODE = NextActionCode.BINDER_IS_NOT_GO_LIVE.value
EXECUTION_DISABLED_CODE = "execution_disabled_in_this_phase"
SECTION_BINDER = "compliance_evidence_binder"
SECTION_OUTBOUND_HALT = "outbound_disabled_operator_halt"
SECTION_LIVE_DEFAULTS = "no_live_provider_defaults"
SECTION_CI_GATES = "ci_dry_run_smoke_deploy_config_gates"
SECTION_AUDIT = "operator_audit_timeline"
CI_DEPLOY_JOB = "deploy-config"
CI_DEPLOY_COMPOSE = "docker compose config --quiet"
AUDIT_ENTRY_LIMIT = 25
RELATED_COMMANDS: tuple[str, ...] = (
    "launch-readiness",
    "settings-execution-preflight",
    "owner-handoff-packet",
    "smoke-dry-run",
    "check-smoke-output",
    "check-config",
    CLI_COMMAND,
    "release-candidate-runbook",
)
RELATED_ROUTES: tuple[str, ...] = (
    "/internal/launch-readiness",
    "/internal/settings-execution-preflight",
    "/internal/owner-handoff-packet",
    "/internal/operator-owner-handoff-packet",
    "/internal/operator-audit-timeline",
    HTTP_ROUTE,
    "/internal/operator-compliance-evidence-binder",
    "/internal/release-candidate-runbook",
    "/internal/operator-release-candidate-runbook",
)
GUARDRAIL_DOC_CHECKS: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] = (
    (
        "docs/SECURITY.md",
        ("no_patient_phi", "outbound_disabled_default", "consent_based_phone_only"),
        ("patient PHI", "OUTBOUND_ENABLED", "Consent-based phone"),
    ),
    (
        "docs/DEPLOYMENT.md",
        ("deployment_safe_defaults", "ci_smoke_dry_run", "ci_deploy_config"),
        ("OUTBOUND_ENABLED=false", "smoke-dry-run", "docker compose"),
    ),
    (
        "README.md",
        ("no_cold_robocalling", "operator_halt_fail_closed"),
        ("No indiscriminate cold AI robocalling", "operator halt"),
    ),
)
_SEVERITY_RANK = {
    FindingSeverity.INFO.value: 0,
    FindingSeverity.WARNING.value: 1,
    FindingSeverity.BLOCKED.value: 2,
}


@dataclass(frozen=True)
class BinderChecklistItem:
    code: str
    severity: str
    source_section: str
    status: str


@dataclass(frozen=True)
class SecretPresenceItem:
    name: str
    present: bool
    status: str
    required: bool


@dataclass(frozen=True)
class OutboundHaltEvidence:
    outbound_enabled: bool
    outbound_halted_settings: bool
    operator_halt_status: str
    operator_halt_before: str
    operator_halt_after: str
    halt_changed: bool
    keep_outbound_disabled: bool
    command_name: str
    route_name: str


@dataclass(frozen=True)
class LiveProviderDefaultEvidence:
    live_providers_enabled: bool
    live_provider_flags: dict[str, bool]
    closed_provider_flag_names: tuple[str, ...]
    required_flag_names: tuple[str, ...]
    env_example_defaults_present: bool
    dockerfile_defaults_present: bool
    compose_defaults_present: bool


@dataclass(frozen=True)
class NoExecutionEvidence:
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
    live_action: bool
    execution_allowed: bool
    go_live_permitted: bool
    future_execution_phase_exists: bool
    live_calendar_events: int
    live_meet_links: int
    live_phone_calls: int
    live_send_attempted_enrollments: int
    outbound_attempted_classifications: int
    undeployed_outbound_jobs: tuple[str, ...]


@dataclass(frozen=True)
class RedactionEvidence:
    phi_fields_present: bool
    secret_values_included: bool
    message_bodies_included: bool
    evidence_snippets_included: bool
    emails_included: bool
    phones_included: bool
    redaction_applied: bool
    missing_credential_names: tuple[str, ...]
    secret_inventory: tuple[SecretPresenceItem, ...]


@dataclass(frozen=True)
class ConsentPhoneEvidence:
    voice_live_enabled: bool
    consent_to_call_required: bool
    cold_calling_disabled: bool
    no_live_dialer: bool
    undeployed_callback_job: str
    live_phone_calls: int
    voice_calls_placed: int


@dataclass(frozen=True)
class CiGateStatus:
    present: bool
    documented: bool
    job_name: str
    command_name: str


@dataclass(frozen=True)
class CiGateEvidence:
    smoke_gate: CiGateStatus
    deploy_config_gate: CiGateStatus
    smoke_run_command: str
    smoke_check_command: str


@dataclass(frozen=True)
class GuardrailDocEvidence:
    path: str
    present: bool
    documented_codes: tuple[str, ...]


@dataclass(frozen=True)
class AuditTimelineEntryEvidence:
    event_type: str
    source_surface: str
    occurred_at: datetime
    status: str | None
    decision_status: str | None
    no_execution: bool
    executed: bool
    live_action: bool
    owner_approved: bool
    settings_applied: bool
    halt_changed: bool


@dataclass(frozen=True)
class AuditTimelineEvidence:
    matching_count: int
    shown_count: int
    truncated: bool
    available_event_types: tuple[str, ...]
    available_sources: tuple[str, ...]
    by_event_type: dict[str, int]
    route_name: str
    entries: tuple[AuditTimelineEntryEvidence, ...]


@dataclass(frozen=True)
class ReusedSummaryEvidence:
    launch_readiness_overall_status: str
    launch_readiness_blocker_codes: tuple[str, ...]
    launch_readiness_next_action_codes: tuple[str, ...]
    settings_preflight_overall_status: str
    settings_preflight_blocked_count: int
    settings_preflight_executable_count: int
    settings_preflight_execution_allowed: bool
    owner_handoff_command: str
    owner_handoff_route: str
    owner_handoff_go_live_permitted: bool
    owner_handoff_execution_allowed: bool


@dataclass(frozen=True)
class ComplianceEvidenceBinder:
    generated_at: datetime
    packet_kind: str
    purpose: str
    overall_status: str
    read_only: bool
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
    go_live_permitted: bool
    manual_review_only: bool
    binder_is_not_go_live: bool
    operator_halt_status: str
    operator_halt_before: str
    operator_halt_after: str
    outbound_enabled: bool
    live_providers_enabled: bool
    cli_command: str
    http_route: str
    related_commands: tuple[str, ...]
    related_routes: tuple[str, ...]
    blocker_codes: tuple[str, ...]
    missing_credential_names: tuple[str, ...]
    closed_provider_flag_names: tuple[str, ...]
    outbound_and_halt: OutboundHaltEvidence
    live_provider_defaults: LiveProviderDefaultEvidence
    no_execution_side_effects: NoExecutionEvidence
    phi_secrets_redaction: RedactionEvidence
    consent_phone_boundary: ConsentPhoneEvidence
    ci_gates: CiGateEvidence
    documented_guardrails: tuple[GuardrailDocEvidence, ...]
    operator_audit_timeline: AuditTimelineEvidence
    reused_summaries: ReusedSummaryEvidence
    remaining_manual_owner_checklist: tuple[BinderChecklistItem, ...]


class ComplianceEvidenceBinderService:
    """Compose existing read-only evidence into one owner-review binder."""

    def __init__(
        self,
        *,
        launch_readiness: LaunchReadinessService | None = None,
        settings_preflight: SettingsExecutionPreflightService | None = None,
        owner_handoff: OwnerHandoffPacketService | None = None,
        audit_timeline: OperatorAuditTimelineService | None = None,
        dashboard: DashboardAnalyticsService | None = None,
    ) -> None:
        self.launch_readiness = launch_readiness or LaunchReadinessService()
        self.settings_preflight = settings_preflight or SettingsExecutionPreflightService()
        self.owner_handoff = owner_handoff or OwnerHandoffPacketService()
        self.audit_timeline = audit_timeline or OperatorAuditTimelineService(
            limit=AUDIT_ENTRY_LIMIT
        )
        self.dashboard = dashboard or DashboardAnalyticsService()

    def build(
        self,
        db: Session,
        settings: Settings,
        *,
        repo_root: Path | None = None,
    ) -> ComplianceEvidenceBinder:
        root = repo_root or Path.cwd()
        halt_before = read_operator_halt(db)
        checklist = self.launch_readiness.assess(db, settings, repo_root=root)
        preflight = self.settings_preflight.simulate(db, settings)
        handoff = self.owner_handoff.build(db, settings)
        timeline = self.audit_timeline.timeline(db, settings)
        safety = self.dashboard.summarize(db, settings).safety
        halt_after = read_operator_halt(db)
        if halt_after is not halt_before:
            raise RuntimeError("compliance evidence binder must not change operator halt status")
        outbound = _outbound_halt_evidence(settings, halt_before, halt_after)
        live_defaults = _live_provider_defaults(settings, checklist, root)
        no_execution = _no_execution_evidence(safety)
        redaction = _redaction_evidence(checklist, safety)
        consent = _consent_phone_evidence(settings, safety)
        ci_gates = _ci_gate_evidence(root)
        guardrails = _documented_guardrails(root)
        audit = _audit_timeline_evidence(timeline)
        reused = _reused_summaries(checklist, preflight, handoff)
        items = _remaining_checklist(
            checklist=checklist,
            preflight=preflight,
            handoff=handoff,
            outbound_enabled=settings.outbound_enabled,
            live_providers_enabled=any_live_provider_enabled(settings),
            halt=halt_after,
            ci_gates=ci_gates,
        )
        binder = ComplianceEvidenceBinder(
            generated_at=datetime.now(tz=UTC),
            packet_kind=PACKET_KIND,
            purpose=PACKET_PURPOSE,
            overall_status=checklist.overall_status,
            read_only=True,
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
            future_execution_phase_exists=False,
            go_live_permitted=False,
            manual_review_only=True,
            binder_is_not_go_live=True,
            operator_halt_status=halt_after.value,
            operator_halt_before=halt_before.value,
            operator_halt_after=halt_after.value,
            outbound_enabled=settings.outbound_enabled,
            live_providers_enabled=any_live_provider_enabled(settings),
            cli_command=CLI_COMMAND,
            http_route=HTTP_ROUTE,
            related_commands=RELATED_COMMANDS,
            related_routes=RELATED_ROUTES,
            blocker_codes=_unique_sorted(
                (*checklist_blocker_codes(checklist), *preflight.blocker_codes)
            ),
            missing_credential_names=redaction.missing_credential_names,
            closed_provider_flag_names=live_defaults.closed_provider_flag_names,
            outbound_and_halt=outbound,
            live_provider_defaults=live_defaults,
            no_execution_side_effects=no_execution,
            phi_secrets_redaction=redaction,
            consent_phone_boundary=consent,
            ci_gates=ci_gates,
            documented_guardrails=guardrails,
            operator_audit_timeline=audit,
            reused_summaries=reused,
            remaining_manual_owner_checklist=items,
        )
        logger.info(
            "compliance_evidence_binder_built",
            packet_kind=PACKET_KIND,
            purpose=PACKET_PURPOSE,
            overall_status=binder.overall_status,
            read_only=True,
            no_execution=True,
            executed=0,
            settings_applied=False,
            owner_approved=False,
            live_action=False,
            execution_allowed=False,
            go_live_permitted=False,
            binder_is_not_go_live=True,
            future_execution_phase_exists=False,
        )
        return binder


def format_compliance_evidence_binder(
    binder: ComplianceEvidenceBinder,
    *,
    as_json: bool = False,
) -> str:
    payload = sanitize_mapping(binder_payload(binder))
    if as_json:
        return json.dumps(payload, sort_keys=True)
    return _format_markdown(binder, payload)


def binder_payload(binder: ComplianceEvidenceBinder) -> dict[str, Any]:
    return {
        "generated_at": binder.generated_at.isoformat(),
        "packet_kind": PACKET_KIND,
        "purpose": PACKET_PURPOSE,
        "overall_status": binder.overall_status,
        "read_only": True,
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
        "go_live_permitted": False,
        "manual_review_only": True,
        "binder_is_not_go_live": True,
        "operator_halt_status": binder.operator_halt_status,
        "operator_halt_before": binder.operator_halt_before,
        "operator_halt_after": binder.operator_halt_after,
        "outbound_enabled": binder.outbound_enabled,
        "live_providers_enabled": binder.live_providers_enabled,
        "cli_command": CLI_COMMAND,
        "http_route": HTTP_ROUTE,
        "related_commands": list(RELATED_COMMANDS),
        "related_routes": list(RELATED_ROUTES),
        "blocker_codes": list(binder.blocker_codes),
        "missing_credential_names": list(binder.missing_credential_names),
        "closed_provider_flag_names": list(binder.closed_provider_flag_names),
        "outbound_and_halt": _outbound_payload(binder.outbound_and_halt),
        "live_provider_defaults": _live_defaults_payload(binder.live_provider_defaults),
        "no_execution_side_effects": _no_execution_payload(binder.no_execution_side_effects),
        "phi_secrets_redaction": _redaction_payload(binder.phi_secrets_redaction),
        "consent_phone_boundary": _consent_payload(binder.consent_phone_boundary),
        "ci_gates": _ci_gates_payload(binder.ci_gates),
        "documented_guardrails": [
            {
                "path": item.path,
                "present": item.present,
                "documented_codes": list(item.documented_codes),
            }
            for item in binder.documented_guardrails
        ],
        "operator_audit_timeline": _audit_payload(binder.operator_audit_timeline),
        "reused_summaries": _reused_payload(binder.reused_summaries),
        "remaining_manual_owner_checklist": [
            {
                "code": item.code,
                "severity": item.severity,
                "source_section": item.source_section,
                "status": item.status,
            }
            for item in binder.remaining_manual_owner_checklist
        ],
    }


def inspect_ci_deploy_config_gate(repo_root: Path) -> CiGateStatus:
    """Inspect the local CI workflow file. Does not call GitHub Actions."""

    path = repo_root / CI_WORKFLOW_RELATIVE
    if not path.is_file():
        return CiGateStatus(
            present=False,
            documented=False,
            job_name="missing",
            command_name=CI_DEPLOY_COMPOSE,
        )
    text = path.read_text(encoding="utf-8")
    documented = (
        f"{CI_DEPLOY_JOB}:" in text
        and CI_DEPLOY_COMPOSE in text
        and "OUTBOUND_ENABLED=false" in text
    )
    return CiGateStatus(
        present=True,
        documented=documented,
        job_name=CI_DEPLOY_JOB if documented else "missing",
        command_name=CI_DEPLOY_COMPOSE,
    )


def checklist_blocker_codes(checklist: LaunchReadinessChecklist) -> tuple[str, ...]:
    return _unique_sorted(
        item.code for item in checklist.findings if item.severity == FindingSeverity.BLOCKED.value
    )


def _outbound_halt_evidence(
    settings: Settings,
    halt_before: HaltStatus,
    halt_after: HaltStatus,
) -> OutboundHaltEvidence:
    return OutboundHaltEvidence(
        outbound_enabled=settings.outbound_enabled,
        outbound_halted_settings=settings.outbound_halted,
        operator_halt_status=halt_after.value,
        operator_halt_before=halt_before.value,
        operator_halt_after=halt_after.value,
        halt_changed=False,
        keep_outbound_disabled=not settings.outbound_enabled,
        command_name=CLI_COMMAND,
        route_name=HTTP_ROUTE,
    )


def _live_provider_defaults(
    settings: Settings,
    checklist: LaunchReadinessChecklist,
    repo_root: Path,
) -> LiveProviderDefaultEvidence:
    flags = live_provider_flags(settings)
    closed = _unique_sorted(
        item.name
        for item in checklist.config_flags
        if not item.enabled and item.name != "OUTBOUND_ENABLED"
    )
    env_text = _read_text(repo_root / ".env.example")
    docker_text = _read_text(repo_root / "Dockerfile")
    compose_text = _read_text(repo_root / "docker-compose.yml")
    return LiveProviderDefaultEvidence(
        live_providers_enabled=any_live_provider_enabled(settings),
        live_provider_flags=dict(flags),
        closed_provider_flag_names=closed,
        required_flag_names=REQUIRED_FLAG_NAMES,
        env_example_defaults_present=_flags_disabled_in_text(env_text, assignment="="),
        dockerfile_defaults_present=_flags_disabled_in_text(docker_text, assignment="="),
        compose_defaults_present=_flags_disabled_in_text(compose_text, assignment=": "),
    )


def _no_execution_evidence(safety: SafetyCard) -> NoExecutionEvidence:
    return NoExecutionEvidence(
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
        live_action=False,
        execution_allowed=False,
        go_live_permitted=False,
        future_execution_phase_exists=False,
        live_calendar_events=safety.live_calendar_events,
        live_meet_links=safety.live_meet_links,
        live_phone_calls=safety.live_phone_calls,
        live_send_attempted_enrollments=safety.live_send_attempted_enrollments,
        outbound_attempted_classifications=safety.outbound_attempted_classifications,
        undeployed_outbound_jobs=undeployed_outbound_job_names(),
    )


def _redaction_evidence(
    checklist: LaunchReadinessChecklist,
    safety: SafetyCard,
) -> RedactionEvidence:
    missing = _unique_sorted(
        item.name
        for item in checklist.secret_inventory
        if item.status == SecretPresenceStatus.MISSING.value
    )
    inventory = tuple(
        SecretPresenceItem(
            name=item.name,
            present=item.present,
            status=item.status,
            required=item.required,
        )
        for item in checklist.secret_inventory
    )
    return RedactionEvidence(
        phi_fields_present=safety.phi_fields_present,
        secret_values_included=False,
        message_bodies_included=False,
        evidence_snippets_included=False,
        emails_included=False,
        phones_included=False,
        redaction_applied=True,
        missing_credential_names=missing,
        secret_inventory=inventory,
    )


def _consent_phone_evidence(settings: Settings, safety: SafetyCard) -> ConsentPhoneEvidence:
    return ConsentPhoneEvidence(
        voice_live_enabled=settings.voice_live_enabled,
        consent_to_call_required=True,
        cold_calling_disabled=True,
        no_live_dialer=True,
        undeployed_callback_job=PLACE_CONSENT_CALLBACK_JOB,
        live_phone_calls=safety.live_phone_calls,
        voice_calls_placed=safety.voice_calls_placed,
    )


def _ci_gate_evidence(repo_root: Path) -> CiGateEvidence:
    smoke = inspect_ci_smoke_gate(repo_root)
    deploy = inspect_ci_deploy_config_gate(repo_root)
    return CiGateEvidence(
        smoke_gate=CiGateStatus(
            present=smoke.present,
            documented=smoke.documented,
            job_name=smoke.job_name,
            command_name=CI_SMOKE_RUN,
        ),
        deploy_config_gate=deploy,
        smoke_run_command=CI_SMOKE_RUN,
        smoke_check_command=CI_SMOKE_CHECK,
    )


def _documented_guardrails(repo_root: Path) -> tuple[GuardrailDocEvidence, ...]:
    items: list[GuardrailDocEvidence] = []
    for relative, codes, phrases in GUARDRAIL_DOC_CHECKS:
        text = _read_text(repo_root / relative)
        present = bool(text)
        documented = tuple(
            code for code, phrase in zip(codes, phrases, strict=True) if phrase in text
        )
        items.append(
            GuardrailDocEvidence(
                path=relative,
                present=present,
                documented_codes=documented if present else (),
            )
        )
    return tuple(items)


def _audit_timeline_evidence(timeline: OperatorAuditTimeline) -> AuditTimelineEvidence:
    entries = tuple(
        AuditTimelineEntryEvidence(
            event_type=item.event_type,
            source_surface=item.source_surface,
            occurred_at=item.occurred_at,
            status=item.status,
            decision_status=item.decision_status,
            no_execution=True,
            executed=False,
            live_action=False,
            owner_approved=False,
            settings_applied=False,
            halt_changed=False,
        )
        for item in timeline.entries
    )
    by_event_type: dict[str, int] = {}
    for item in entries:
        by_event_type[item.event_type] = by_event_type.get(item.event_type, 0) + 1
    return AuditTimelineEvidence(
        matching_count=timeline.matching_count,
        shown_count=len(entries),
        truncated=timeline.truncated,
        available_event_types=timeline.available_event_types,
        available_sources=timeline.available_sources,
        by_event_type=by_event_type,
        route_name="/internal/operator-audit-timeline",
        entries=entries,
    )


def _reused_summaries(
    checklist: LaunchReadinessChecklist,
    preflight: SettingsExecutionPreflight,
    handoff: OwnerHandoffPacket,
) -> ReusedSummaryEvidence:
    return ReusedSummaryEvidence(
        launch_readiness_overall_status=checklist.overall_status,
        launch_readiness_blocker_codes=checklist_blocker_codes(checklist),
        launch_readiness_next_action_codes=_unique_sorted(
            item.next_action_code for item in checklist.next_actions
        ),
        settings_preflight_overall_status=preflight.overall_status,
        settings_preflight_blocked_count=preflight.blocked_count,
        settings_preflight_executable_count=0,
        settings_preflight_execution_allowed=False,
        owner_handoff_command="owner-handoff-packet",
        owner_handoff_route="/internal/owner-handoff-packet",
        owner_handoff_go_live_permitted=handoff.go_live_permitted,
        owner_handoff_execution_allowed=False,
    )


def _remaining_checklist(
    *,
    checklist: LaunchReadinessChecklist,
    preflight: SettingsExecutionPreflight,
    handoff: OwnerHandoffPacket,
    outbound_enabled: bool,
    live_providers_enabled: bool,
    halt: HaltStatus,
    ci_gates: CiGateEvidence,
) -> tuple[BinderChecklistItem, ...]:
    selected: dict[str, BinderChecklistItem] = {}

    def add(code: str, severity: str, source_section: str, status: str = "open") -> None:
        current = selected.get(code)
        if current is not None and _SEVERITY_RANK.get(current.severity, 0) >= _SEVERITY_RANK.get(
            severity, 0
        ):
            return
        selected[code] = BinderChecklistItem(
            code=code,
            severity=severity,
            source_section=source_section,
            status=status,
        )

    add(BINDER_NOT_GO_LIVE_CODE, FindingSeverity.INFO.value, SECTION_BINDER)
    add(EXECUTION_DISABLED_CODE, FindingSeverity.INFO.value, SECTION_BINDER)
    add(NextActionCode.HANDOFF_IS_NOT_GO_LIVE.value, FindingSeverity.INFO.value, SECTION_BINDER)
    for item in handoff.remaining_manual_owner_checklist:
        add(item.code, item.severity, item.source_section, item.status)
    for action in checklist.next_actions:
        severity = FindingSeverity.INFO.value
        if action.severity == FindingSeverity.BLOCKED.value:
            severity = FindingSeverity.BLOCKED.value
        elif action.severity == FindingSeverity.WARNING.value:
            severity = FindingSeverity.WARNING.value
        add(action.next_action_code, severity, "launch_readiness")
    if preflight.pending_decision_count or preflight.blocked_count:
        add(
            NextActionCode.INSPECT_SETTINGS_EXECUTION_PREFLIGHT.value,
            FindingSeverity.WARNING.value,
            "settings_execution_preflight",
        )
    if not outbound_enabled:
        add(
            NextActionCode.KEEP_OUTBOUND_DISABLED.value,
            FindingSeverity.INFO.value,
            SECTION_OUTBOUND_HALT,
        )
    if not live_providers_enabled:
        add(
            NextActionCode.KEEP_LIVE_PROVIDERS_DISABLED.value,
            FindingSeverity.INFO.value,
            SECTION_LIVE_DEFAULTS,
        )
    match halt:
        case HaltStatus.HALTED:
            add(
                NextActionCode.KEEP_OPERATOR_HALT.value,
                FindingSeverity.WARNING.value,
                SECTION_OUTBOUND_HALT,
            )
        case HaltStatus.UNAVAILABLE:
            add(
                NextActionCode.RECORD_OPERATOR_HALT.value,
                FindingSeverity.BLOCKED.value,
                SECTION_OUTBOUND_HALT,
            )
        case HaltStatus.CLEARED:
            pass
        case _:
            _unreachable(halt)
    if not ci_gates.smoke_gate.documented or not ci_gates.deploy_config_gate.documented:
        add(
            NextActionCode.RESTORE_CI_SMOKE_GATE.value,
            FindingSeverity.BLOCKED.value,
            SECTION_CI_GATES,
        )
    add(
        NextActionCode.INSPECT_OPERATOR_AUDIT_TIMELINE.value,
        FindingSeverity.INFO.value,
        SECTION_AUDIT,
    )
    return tuple(
        sorted(
            selected.values(),
            key=lambda item: (-_SEVERITY_RANK.get(item.severity, 0), item.code),
        )
    )


def _outbound_payload(evidence: OutboundHaltEvidence) -> dict[str, Any]:
    return {
        "outbound_enabled": evidence.outbound_enabled,
        "outbound_halted_settings": evidence.outbound_halted_settings,
        "operator_halt_status": evidence.operator_halt_status,
        "operator_halt_before": evidence.operator_halt_before,
        "operator_halt_after": evidence.operator_halt_after,
        "halt_changed": False,
        "keep_outbound_disabled": evidence.keep_outbound_disabled,
        "command_name": evidence.command_name,
        "route_name": evidence.route_name,
    }


def _live_defaults_payload(evidence: LiveProviderDefaultEvidence) -> dict[str, Any]:
    return {
        "live_providers_enabled": evidence.live_providers_enabled,
        "live_provider_flags": dict(evidence.live_provider_flags),
        "closed_provider_flag_names": list(evidence.closed_provider_flag_names),
        "required_flag_names": list(evidence.required_flag_names),
        "env_example_defaults_present": evidence.env_example_defaults_present,
        "dockerfile_defaults_present": evidence.dockerfile_defaults_present,
        "compose_defaults_present": evidence.compose_defaults_present,
    }


def _no_execution_payload(evidence: NoExecutionEvidence) -> dict[str, Any]:
    return {
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
        "live_action": False,
        "execution_allowed": False,
        "go_live_permitted": False,
        "future_execution_phase_exists": False,
        "live_calendar_events": evidence.live_calendar_events,
        "live_meet_links": evidence.live_meet_links,
        "live_phone_calls": evidence.live_phone_calls,
        "live_send_attempted_enrollments": evidence.live_send_attempted_enrollments,
        "outbound_attempted_classifications": evidence.outbound_attempted_classifications,
        "undeployed_outbound_jobs": list(evidence.undeployed_outbound_jobs),
    }


def _redaction_payload(evidence: RedactionEvidence) -> dict[str, Any]:
    return {
        "phi_fields_present": evidence.phi_fields_present,
        "secret_values_included": False,
        "message_bodies_included": False,
        "evidence_snippets_included": False,
        "emails_included": False,
        "phones_included": False,
        "redaction_applied": True,
        "missing_credential_names": list(evidence.missing_credential_names),
        "secret_inventory": [
            {
                "name": item.name,
                "present": item.present,
                "status": item.status,
                "required": item.required,
            }
            for item in evidence.secret_inventory
        ],
    }


def _consent_payload(evidence: ConsentPhoneEvidence) -> dict[str, Any]:
    return {
        "voice_live_enabled": evidence.voice_live_enabled,
        "consent_to_call_required": True,
        "cold_calling_disabled": True,
        "no_live_dialer": True,
        "undeployed_callback_job": evidence.undeployed_callback_job,
        "live_phone_calls": evidence.live_phone_calls,
        "voice_calls_placed": evidence.voice_calls_placed,
    }


def _ci_gates_payload(evidence: CiGateEvidence) -> dict[str, Any]:
    return {
        "smoke_gate": {
            "present": evidence.smoke_gate.present,
            "documented": evidence.smoke_gate.documented,
            "job_name": evidence.smoke_gate.job_name,
            "command_name": evidence.smoke_gate.command_name,
        },
        "deploy_config_gate": {
            "present": evidence.deploy_config_gate.present,
            "documented": evidence.deploy_config_gate.documented,
            "job_name": evidence.deploy_config_gate.job_name,
            "command_name": evidence.deploy_config_gate.command_name,
        },
        "smoke_run_command": evidence.smoke_run_command,
        "smoke_check_command": evidence.smoke_check_command,
    }


def _audit_payload(evidence: AuditTimelineEvidence) -> dict[str, Any]:
    return {
        "matching_count": evidence.matching_count,
        "shown_count": evidence.shown_count,
        "truncated": evidence.truncated,
        "available_event_types": list(evidence.available_event_types),
        "available_sources": list(evidence.available_sources),
        "by_event_type": dict(evidence.by_event_type),
        "route_name": evidence.route_name,
        "entries": [
            {
                "event_type": item.event_type,
                "source_surface": item.source_surface,
                "occurred_at": item.occurred_at.isoformat(),
                "status": item.status,
                "decision_status": item.decision_status,
                "no_execution": True,
                "executed": False,
                "live_action": False,
                "owner_approved": False,
                "settings_applied": False,
                "halt_changed": False,
            }
            for item in evidence.entries
        ],
    }


def _reused_payload(evidence: ReusedSummaryEvidence) -> dict[str, Any]:
    return {
        "launch_readiness_overall_status": evidence.launch_readiness_overall_status,
        "launch_readiness_blocker_codes": list(evidence.launch_readiness_blocker_codes),
        "launch_readiness_next_action_codes": list(evidence.launch_readiness_next_action_codes),
        "settings_preflight_overall_status": evidence.settings_preflight_overall_status,
        "settings_preflight_blocked_count": evidence.settings_preflight_blocked_count,
        "settings_preflight_executable_count": 0,
        "settings_preflight_execution_allowed": False,
        "owner_handoff_command": evidence.owner_handoff_command,
        "owner_handoff_route": evidence.owner_handoff_route,
        "owner_handoff_go_live_permitted": False,
        "owner_handoff_execution_allowed": False,
    }


def _format_markdown(binder: ComplianceEvidenceBinder, payload: dict[str, Any]) -> str:
    lines = [
        "# Compliance evidence binder",
        "",
        "This binder is for manual owner review only. It is not permission or "
        "machinery for going live.",
        "",
        f"- overall: {payload['overall_status']}",
        f"- packet_kind: {payload['packet_kind']}",
        f"- purpose: {payload['purpose']}",
        f"- read_only: {_bool_text(payload['read_only'])}",
        f"- no_execution: {_bool_text(payload['no_execution'])}",
        f"- dry_run_only: {_bool_text(payload['dry_run_only'])}",
        f"- executed: {payload['executed']}",
        f"- owner_approved: {_bool_text(payload['owner_approved'])}",
        f"- settings_applied: {_bool_text(payload['settings_applied'])}",
        f"- halt_changed: {_bool_text(payload['halt_changed'])}",
        f"- live_action: {_bool_text(payload['live_action'])}",
        f"- execution_allowed: {_bool_text(payload['execution_allowed'])}",
        f"- go_live_permitted: {_bool_text(payload['go_live_permitted'])}",
        f"- binder_is_not_go_live: {_bool_text(payload['binder_is_not_go_live'])}",
        (
            "- operator_halt: "
            f"status={payload['operator_halt_status']} "
            f"before={payload['operator_halt_before']} "
            f"after={payload['operator_halt_after']}"
        ),
        f"- outbound_enabled: {_bool_text(payload['outbound_enabled'])}",
        f"- live_providers_enabled: {_bool_text(payload['live_providers_enabled'])}",
        f"- cli_command: {payload['cli_command']}",
        f"- http_route: {payload['http_route']}",
        f"- blocker_codes: {_format_codes(binder.blocker_codes)}",
        f"- missing_credential_names: {_format_codes(binder.missing_credential_names)}",
        f"- closed_provider_flag_names: {_format_codes(binder.closed_provider_flag_names)}",
        "",
        "## Outbound disabled and operator halt evidence",
        f"- outbound_enabled: {_bool_text(binder.outbound_and_halt.outbound_enabled)}",
        (
            "- outbound_halted_settings: "
            f"{_bool_text(binder.outbound_and_halt.outbound_halted_settings)}"
        ),
        f"- operator_halt: {binder.outbound_and_halt.operator_halt_status}",
        f"- halt_changed: {_bool_text(binder.outbound_and_halt.halt_changed)}",
        (
            "- keep_outbound_disabled: "
            f"{_bool_text(binder.outbound_and_halt.keep_outbound_disabled)}"
        ),
        "",
        "## No-live-provider default config evidence",
        (
            "- live_providers_enabled: "
            f"{_bool_text(binder.live_provider_defaults.live_providers_enabled)}"
        ),
        (
            "- closed_provider_flag_names: "
            f"{_format_codes(binder.live_provider_defaults.closed_provider_flag_names)}"
        ),
        (
            "- env_example_defaults_present: "
            f"{_bool_text(binder.live_provider_defaults.env_example_defaults_present)}"
        ),
        (
            "- dockerfile_defaults_present: "
            f"{_bool_text(binder.live_provider_defaults.dockerfile_defaults_present)}"
        ),
        (
            "- compose_defaults_present: "
            f"{_bool_text(binder.live_provider_defaults.compose_defaults_present)}"
        ),
        "",
        "## No-execution side-effect evidence",
        f"- executed: {binder.no_execution_side_effects.executed}",
        f"- live_action: {_bool_text(binder.no_execution_side_effects.live_action)}",
        (
            "- execution_allowed: "
            f"{_bool_text(binder.no_execution_side_effects.execution_allowed)}"
        ),
        (
            "- go_live_permitted: "
            f"{_bool_text(binder.no_execution_side_effects.go_live_permitted)}"
        ),
        f"- live_calendar_events: {binder.no_execution_side_effects.live_calendar_events}",
        f"- live_meet_links: {binder.no_execution_side_effects.live_meet_links}",
        f"- live_phone_calls: {binder.no_execution_side_effects.live_phone_calls}",
        (
            "- live_send_attempted_enrollments: "
            f"{binder.no_execution_side_effects.live_send_attempted_enrollments}"
        ),
        (
            "- undeployed_outbound_jobs: "
            f"{_format_codes(binder.no_execution_side_effects.undeployed_outbound_jobs)}"
        ),
        "",
        "## PHI, secrets, and redaction evidence",
        (
            "- phi_fields_present: "
            f"{_bool_text(binder.phi_secrets_redaction.phi_fields_present)}"
        ),
        (
            "- secret_values_included: "
            f"{_bool_text(binder.phi_secrets_redaction.secret_values_included)}"
        ),
        (
            "- message_bodies_included: "
            f"{_bool_text(binder.phi_secrets_redaction.message_bodies_included)}"
        ),
        f"- redaction_applied: {_bool_text(binder.phi_secrets_redaction.redaction_applied)}",
        (
            "- missing_credential_names: "
            f"{_format_codes(binder.phi_secrets_redaction.missing_credential_names)}"
        ),
        "",
        "## Consent-based phone-only boundary evidence",
        (
            "- voice_live_enabled: "
            f"{_bool_text(binder.consent_phone_boundary.voice_live_enabled)}"
        ),
        (
            "- consent_to_call_required: "
            f"{_bool_text(binder.consent_phone_boundary.consent_to_call_required)}"
        ),
        (
            "- cold_calling_disabled: "
            f"{_bool_text(binder.consent_phone_boundary.cold_calling_disabled)}"
        ),
        f"- no_live_dialer: {_bool_text(binder.consent_phone_boundary.no_live_dialer)}",
        f"- undeployed_callback_job: {binder.consent_phone_boundary.undeployed_callback_job}",
        f"- live_phone_calls: {binder.consent_phone_boundary.live_phone_calls}",
        "",
        "## CI dry-run smoke and deploy-config gates",
        (
            "- smoke_gate: "
            f"present={_bool_text(binder.ci_gates.smoke_gate.present)} "
            f"documented={_bool_text(binder.ci_gates.smoke_gate.documented)} "
            f"job={binder.ci_gates.smoke_gate.job_name}"
        ),
        (
            "- deploy_config_gate: "
            f"present={_bool_text(binder.ci_gates.deploy_config_gate.present)} "
            f"documented={_bool_text(binder.ci_gates.deploy_config_gate.documented)} "
            f"job={binder.ci_gates.deploy_config_gate.job_name}"
        ),
        f"- smoke_run_command: {binder.ci_gates.smoke_run_command}",
        f"- smoke_check_command: {binder.ci_gates.smoke_check_command}",
        "",
        "## Documented compliance guardrails",
    ]
    for doc in binder.documented_guardrails:
        lines.append(
            f"- doc: path={doc.path} present={_bool_text(doc.present)} "
            f"codes={_format_codes(doc.documented_codes)}"
        )
    lines.extend(
        [
            "",
            "## Operator audit timeline",
            f"- matching: {binder.operator_audit_timeline.matching_count}",
            f"- shown: {binder.operator_audit_timeline.shown_count}",
            f"- truncated: {_bool_text(binder.operator_audit_timeline.truncated)}",
            (
                "- event_types: "
                f"{_format_codes(binder.operator_audit_timeline.available_event_types)}"
            ),
            f"- route: {binder.operator_audit_timeline.route_name}",
        ]
    )
    for entry in binder.operator_audit_timeline.entries:
        lines.append(
            "- entry: "
            f"event={entry.event_type} "
            f"source={entry.source_surface} "
            f"status={entry.status or '-'} "
            f"decision={entry.decision_status or '-'} "
            f"no_execution={_bool_text(entry.no_execution)}"
        )
    lines.extend(
        [
            "",
            "## Reused read-only summaries",
            f"- launch_readiness: {binder.reused_summaries.launch_readiness_overall_status}",
            (
                "- launch_readiness_blockers: "
                f"{_format_codes(binder.reused_summaries.launch_readiness_blocker_codes)}"
            ),
            (
                "- settings_preflight: "
                f"{binder.reused_summaries.settings_preflight_overall_status} "
                f"blocked={binder.reused_summaries.settings_preflight_blocked_count} "
                f"executable={binder.reused_summaries.settings_preflight_executable_count} "
                "execution_allowed="
                f"{_bool_text(binder.reused_summaries.settings_preflight_execution_allowed)}"
            ),
            (
                "- owner_handoff: "
                f"command={binder.reused_summaries.owner_handoff_command} "
                f"route={binder.reused_summaries.owner_handoff_route} "
                "go_live_permitted="
                f"{_bool_text(binder.reused_summaries.owner_handoff_go_live_permitted)}"
            ),
            "",
            "## Remaining manual owner checklist",
        ]
    )
    for checklist_item in binder.remaining_manual_owner_checklist:
        lines.append(
            f"- [{checklist_item.status}] {checklist_item.code} "
            f"severity={checklist_item.severity} source={checklist_item.source_section}"
        )
    return "\n".join(lines)


def _flags_disabled_in_text(text: str, *, assignment: str) -> bool:
    if not text:
        return False
    if assignment == ": ":
        return all(
            f'{name}: "false"' in text or f"{name}=false" in text for name in REQUIRED_FLAG_NAMES
        )
    return all(f"{name}=false" in text for name in REQUIRED_FLAG_NAMES)


def _read_text(path: Path) -> str:
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8")


def _format_codes(values: Sequence[str]) -> str:
    return ",".join(values) if values else "-"


def _unique_sorted(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(sorted(set(values)))


def _bool_text(value: object) -> str:
    return "true" if value else "false"


def _unreachable(value: object) -> Never:
    raise RuntimeError(f"unhandled compliance evidence binder variant: {value!r}")
