"""Read-only release-candidate deployment runbook export.

Phase 37 consolidates existing safety evidence into one sanitized
Markdown/JSON packet that describes future manual deployment steps and
rollback checks. It never deploys, applies settings, lifts halt, enables
outbound, calls providers, publishes, spends, executes approved items,
executes owner approval packets, executes settings requests, creates
campaigns, books meetings, places calls, or contacts anyone.
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

from vyro_growth.config import Settings, any_live_provider_enabled
from vyro_growth.domain import FindingSeverity, NextActionCode
from vyro_growth.observability import sanitize_mapping
from vyro_growth.services.compliance_evidence_binder import (
    ComplianceEvidenceBinder,
    ComplianceEvidenceBinderService,
)
from vyro_growth.services.operator_halt import HaltStatus, read_operator_halt

logger = structlog.get_logger(__name__)

PACKET_KIND = "release_candidate_deployment_runbook"
PACKET_PURPOSE = "future_manual_owner_review_only"
CLI_COMMAND = "release-candidate-runbook"
HTTP_ROUTE = "/internal/release-candidate-runbook"
RUNBOOK_NOT_DEPLOYMENT_CODE = NextActionCode.RUNBOOK_IS_NOT_DEPLOYMENT.value
EXECUTION_DISABLED_CODE = "execution_disabled_in_this_phase"
RESTORE_CI_DEPLOY_CONFIG_CODE = "restore_ci_deploy_config_gate"
SECTION_RUNBOOK = "release_candidate_runbook"
SECTION_CI = "ci_gates_and_local_verification"
SECTION_DEFAULTS = "safe_environment_defaults"
SECTION_HALT = "operator_halt_and_outbound_verification"
EXPECTED_BASE_BRANCH = "main"
EXPECTED_WORKFLOW_PATH = ".github/workflows/ci.yml"
EXPECTED_RELEASE_CHANNEL = "owner_reviewed_manual_deploy"
REQUIRED_CI_JOB_NAMES: tuple[str, ...] = ("test", "smoke-dry-run", "deploy-config")
LOCAL_VERIFICATION_COMMANDS: tuple[str, ...] = (
    "ruff check .",
    "mypy src",
    "pytest -q",
    "vyro-growth smoke-dry-run --local-only --json",
    "vyro-growth check-smoke-output --file",
    "vyro-growth check-config",
    "docker compose config --quiet",
)
HALT_VERIFICATION_COMMANDS: tuple[str, ...] = (
    "launch-readiness",
    "system-status",
    "check-config",
    CLI_COMMAND,
)
HALT_VERIFICATION_ROUTES: tuple[str, ...] = (
    "/internal/launch-readiness",
    "/internal/monitoring/status",
    HTTP_ROUTE,
)
RELATED_COMMANDS: tuple[str, ...] = (
    "check-config",
    "smoke-dry-run",
    "check-smoke-output",
    "launch-readiness",
    "settings-execution-preflight",
    "owner-handoff-packet",
    "compliance-evidence-binder",
    "system-status",
    CLI_COMMAND,
)
RELATED_ROUTES: tuple[str, ...] = (
    "/health",
    "/ready",
    "/internal/launch-readiness",
    "/internal/settings-execution-preflight",
    "/internal/owner-handoff-packet",
    "/internal/compliance-evidence-binder",
    "/internal/operator-dashboard",
    "/internal/operator-audit-timeline",
    "/internal/operator-compliance-evidence-binder",
    HTTP_ROUTE,
    "/internal/operator-release-candidate-runbook",
)
_SEVERITY_RANK = {
    FindingSeverity.INFO.value: 0,
    FindingSeverity.WARNING.value: 1,
    FindingSeverity.BLOCKED.value: 2,
}


@dataclass(frozen=True)
class RunbookChecklistItem:
    code: str
    severity: str
    source_section: str
    status: str


@dataclass(frozen=True)
class RunbookInstructionStep:
    code: str
    instruction: str
    command_name: str | None
    route_name: str | None


@dataclass(frozen=True)
class RunbookIdentity:
    expected_base_branch: str
    expected_workflow_path: str
    expected_release_channel: str
    git_provider_called: bool
    deployment_from_runbook: bool


@dataclass(frozen=True)
class RunbookCiGate:
    present: bool
    documented: bool
    job_name: str
    command_name: str


@dataclass(frozen=True)
class RunbookCiAndLocalVerification:
    required_ci_job_names: tuple[str, ...]
    smoke_gate: RunbookCiGate
    deploy_config_gate: RunbookCiGate
    local_verification_commands: tuple[str, ...]
    github_actions_called: bool


@dataclass(frozen=True)
class RunbookSafeDefaults:
    outbound_enabled_required: bool
    outbound_enabled: bool
    live_providers_enabled: bool
    required_flag_names: tuple[str, ...]
    closed_provider_flag_names: tuple[str, ...]
    missing_credential_names: tuple[str, ...]
    env_example_defaults_present: bool
    dockerfile_defaults_present: bool
    compose_defaults_present: bool
    secret_values_included: bool


@dataclass(frozen=True)
class RunbookHaltVerification:
    outbound_enabled: bool
    operator_halt_status: str
    operator_halt_before: str
    operator_halt_after: str
    halt_changed: bool
    keep_outbound_disabled: bool
    verification_commands: tuple[str, ...]
    verification_routes: tuple[str, ...]


@dataclass(frozen=True)
class RunbookGuardrailDoc:
    path: str
    present: bool
    documented_codes: tuple[str, ...]


@dataclass(frozen=True)
class RunbookReusedSummaries:
    launch_readiness_overall_status: str
    launch_readiness_blocker_codes: tuple[str, ...]
    settings_preflight_overall_status: str
    settings_preflight_blocked_count: int
    settings_preflight_execution_allowed: bool
    owner_handoff_go_live_permitted: bool
    owner_handoff_execution_allowed: bool
    binder_is_not_go_live: bool
    binder_command: str
    binder_route: str
    audit_timeline_matching_count: int
    audit_timeline_route: str


@dataclass(frozen=True)
class ReleaseCandidateRunbook:
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
    future_deployment_phase_exists: bool
    go_live_permitted: bool
    deployment_allowed: bool
    deployment_attempted: bool
    deployed: bool
    manual_review_only: bool
    runbook_is_not_deployment: bool
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
    release_candidate_identity: RunbookIdentity
    ci_gates_and_local_verification: RunbookCiAndLocalVerification
    safe_environment_defaults: RunbookSafeDefaults
    operator_halt_and_outbound: RunbookHaltVerification
    manual_deployment_sequence: tuple[RunbookInstructionStep, ...]
    rollback_checklist: tuple[RunbookInstructionStep, ...]
    post_deploy_verification: tuple[RunbookInstructionStep, ...]
    documented_guardrails: tuple[RunbookGuardrailDoc, ...]
    reused_summaries: RunbookReusedSummaries
    remaining_manual_owner_checklist: tuple[RunbookChecklistItem, ...]


class ReleaseCandidateRunbookService:
    """Compose existing read-only evidence into a future-manual deploy runbook."""

    def __init__(
        self,
        *,
        binder: ComplianceEvidenceBinderService | None = None,
    ) -> None:
        self.binder = binder or ComplianceEvidenceBinderService()

    def build(
        self,
        db: Session,
        settings: Settings,
        *,
        repo_root: Path | None = None,
    ) -> ReleaseCandidateRunbook:
        root = repo_root or Path.cwd()
        halt_before = read_operator_halt(db)
        evidence = self.binder.build(db, settings, repo_root=root)
        halt_after = read_operator_halt(db)
        if halt_after is not halt_before:
            raise RuntimeError("release candidate runbook must not change operator halt status")
        identity = _identity()
        ci_and_local = _ci_and_local(evidence)
        defaults = _safe_defaults(settings, evidence)
        halt = _halt_verification(settings, halt_before, halt_after)
        reused = _reused_summaries(evidence)
        items = _remaining_checklist(
            evidence=evidence,
            outbound_enabled=settings.outbound_enabled,
            live_providers_enabled=any_live_provider_enabled(settings),
            halt=halt_after,
            ci_and_local=ci_and_local,
        )
        runbook = ReleaseCandidateRunbook(
            generated_at=datetime.now(tz=UTC),
            packet_kind=PACKET_KIND,
            purpose=PACKET_PURPOSE,
            overall_status=evidence.overall_status,
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
            future_deployment_phase_exists=False,
            go_live_permitted=False,
            deployment_allowed=False,
            deployment_attempted=False,
            deployed=False,
            manual_review_only=True,
            runbook_is_not_deployment=True,
            operator_halt_status=halt_after.value,
            operator_halt_before=halt_before.value,
            operator_halt_after=halt_after.value,
            outbound_enabled=settings.outbound_enabled,
            live_providers_enabled=any_live_provider_enabled(settings),
            cli_command=CLI_COMMAND,
            http_route=HTTP_ROUTE,
            related_commands=RELATED_COMMANDS,
            related_routes=RELATED_ROUTES,
            blocker_codes=_unique_sorted(evidence.blocker_codes),
            missing_credential_names=tuple(evidence.missing_credential_names),
            closed_provider_flag_names=tuple(evidence.closed_provider_flag_names),
            release_candidate_identity=identity,
            ci_gates_and_local_verification=ci_and_local,
            safe_environment_defaults=defaults,
            operator_halt_and_outbound=halt,
            manual_deployment_sequence=_deployment_sequence(),
            rollback_checklist=_rollback_checklist(),
            post_deploy_verification=_post_deploy_verification(),
            documented_guardrails=tuple(
                RunbookGuardrailDoc(
                    path=item.path,
                    present=item.present,
                    documented_codes=item.documented_codes,
                )
                for item in evidence.documented_guardrails
            ),
            reused_summaries=reused,
            remaining_manual_owner_checklist=items,
        )
        logger.info(
            "release_candidate_runbook_built",
            packet_kind=PACKET_KIND,
            purpose=PACKET_PURPOSE,
            overall_status=runbook.overall_status,
            read_only=True,
            no_execution=True,
            executed=0,
            settings_applied=False,
            owner_approved=False,
            live_action=False,
            execution_allowed=False,
            go_live_permitted=False,
            deployment_allowed=False,
            deployment_attempted=False,
            runbook_is_not_deployment=True,
            future_execution_phase_exists=False,
            future_deployment_phase_exists=False,
        )
        return runbook


def format_release_candidate_runbook(
    runbook: ReleaseCandidateRunbook,
    *,
    as_json: bool = False,
) -> str:
    payload = sanitize_mapping(runbook_payload(runbook))
    if as_json:
        return json.dumps(payload, sort_keys=True)
    return _format_markdown(runbook, payload)


def runbook_payload(runbook: ReleaseCandidateRunbook) -> dict[str, Any]:
    return {
        "generated_at": runbook.generated_at.isoformat(),
        "packet_kind": PACKET_KIND,
        "purpose": PACKET_PURPOSE,
        "overall_status": runbook.overall_status,
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
        "future_deployment_phase_exists": False,
        "go_live_permitted": False,
        "deployment_allowed": False,
        "deployment_attempted": False,
        "deployed": False,
        "manual_review_only": True,
        "runbook_is_not_deployment": True,
        "operator_halt_status": runbook.operator_halt_status,
        "operator_halt_before": runbook.operator_halt_before,
        "operator_halt_after": runbook.operator_halt_after,
        "outbound_enabled": runbook.outbound_enabled,
        "live_providers_enabled": runbook.live_providers_enabled,
        "cli_command": CLI_COMMAND,
        "http_route": HTTP_ROUTE,
        "related_commands": list(RELATED_COMMANDS),
        "related_routes": list(RELATED_ROUTES),
        "blocker_codes": list(runbook.blocker_codes),
        "missing_credential_names": list(runbook.missing_credential_names),
        "closed_provider_flag_names": list(runbook.closed_provider_flag_names),
        "release_candidate_identity": _identity_payload(runbook.release_candidate_identity),
        "ci_gates_and_local_verification": _ci_payload(runbook.ci_gates_and_local_verification),
        "safe_environment_defaults": _defaults_payload(runbook.safe_environment_defaults),
        "operator_halt_and_outbound": _halt_payload(runbook.operator_halt_and_outbound),
        "manual_deployment_sequence": [
            _step_payload(item) for item in runbook.manual_deployment_sequence
        ],
        "rollback_checklist": [_step_payload(item) for item in runbook.rollback_checklist],
        "post_deploy_verification": [
            _step_payload(item) for item in runbook.post_deploy_verification
        ],
        "documented_guardrails": [
            {
                "path": item.path,
                "present": item.present,
                "documented_codes": list(item.documented_codes),
            }
            for item in runbook.documented_guardrails
        ],
        "reused_summaries": _reused_payload(runbook.reused_summaries),
        "remaining_manual_owner_checklist": [
            {
                "code": item.code,
                "severity": item.severity,
                "source_section": item.source_section,
                "status": item.status,
            }
            for item in runbook.remaining_manual_owner_checklist
        ],
    }


def _identity() -> RunbookIdentity:
    return RunbookIdentity(
        expected_base_branch=EXPECTED_BASE_BRANCH,
        expected_workflow_path=EXPECTED_WORKFLOW_PATH,
        expected_release_channel=EXPECTED_RELEASE_CHANNEL,
        git_provider_called=False,
        deployment_from_runbook=False,
    )


def _ci_and_local(evidence: ComplianceEvidenceBinder) -> RunbookCiAndLocalVerification:
    smoke = evidence.ci_gates.smoke_gate
    deploy = evidence.ci_gates.deploy_config_gate
    return RunbookCiAndLocalVerification(
        required_ci_job_names=REQUIRED_CI_JOB_NAMES,
        smoke_gate=RunbookCiGate(
            present=smoke.present,
            documented=smoke.documented,
            job_name=smoke.job_name,
            command_name=smoke.command_name,
        ),
        deploy_config_gate=RunbookCiGate(
            present=deploy.present,
            documented=deploy.documented,
            job_name=deploy.job_name,
            command_name=deploy.command_name,
        ),
        local_verification_commands=LOCAL_VERIFICATION_COMMANDS,
        github_actions_called=False,
    )


def _safe_defaults(settings: Settings, evidence: ComplianceEvidenceBinder) -> RunbookSafeDefaults:
    defaults = evidence.live_provider_defaults
    return RunbookSafeDefaults(
        outbound_enabled_required=False,
        outbound_enabled=settings.outbound_enabled,
        live_providers_enabled=defaults.live_providers_enabled,
        required_flag_names=defaults.required_flag_names,
        closed_provider_flag_names=defaults.closed_provider_flag_names,
        missing_credential_names=evidence.missing_credential_names,
        env_example_defaults_present=defaults.env_example_defaults_present,
        dockerfile_defaults_present=defaults.dockerfile_defaults_present,
        compose_defaults_present=defaults.compose_defaults_present,
        secret_values_included=False,
    )


def _halt_verification(
    settings: Settings,
    halt_before: HaltStatus,
    halt_after: HaltStatus,
) -> RunbookHaltVerification:
    return RunbookHaltVerification(
        outbound_enabled=settings.outbound_enabled,
        operator_halt_status=halt_after.value,
        operator_halt_before=halt_before.value,
        operator_halt_after=halt_after.value,
        halt_changed=False,
        keep_outbound_disabled=not settings.outbound_enabled,
        verification_commands=HALT_VERIFICATION_COMMANDS,
        verification_routes=HALT_VERIFICATION_ROUTES,
    )


def _reused_summaries(evidence: ComplianceEvidenceBinder) -> RunbookReusedSummaries:
    summaries = evidence.reused_summaries
    return RunbookReusedSummaries(
        launch_readiness_overall_status=summaries.launch_readiness_overall_status,
        launch_readiness_blocker_codes=summaries.launch_readiness_blocker_codes,
        settings_preflight_overall_status=summaries.settings_preflight_overall_status,
        settings_preflight_blocked_count=summaries.settings_preflight_blocked_count,
        settings_preflight_execution_allowed=False,
        owner_handoff_go_live_permitted=False,
        owner_handoff_execution_allowed=False,
        binder_is_not_go_live=True,
        binder_command=evidence.cli_command,
        binder_route=evidence.http_route,
        audit_timeline_matching_count=evidence.operator_audit_timeline.matching_count,
        audit_timeline_route=evidence.operator_audit_timeline.route_name,
    )


def _deployment_sequence() -> tuple[RunbookInstructionStep, ...]:
    return (
        RunbookInstructionStep(
            code="provision_database_and_named_secrets",
            instruction=(
                "Provision PostgreSQL/Supabase and inject DATABASE_URL plus "
                "INTERNAL_API_KEY from a secret store. Names only; never print values."
            ),
            command_name=None,
            route_name=None,
        ),
        RunbookInstructionStep(
            code="confirm_safe_environment_defaults",
            instruction=(
                "Confirm OUTBOUND_ENABLED=false and every live-provider flag remains "
                "false before starting API or worker processes."
            ),
            command_name="check-config",
            route_name=None,
        ),
        RunbookInstructionStep(
            code="validate_runtime_config",
            instruction="Run vyro-growth check-config. Do not print secret values.",
            command_name="check-config",
            route_name=None,
        ),
        RunbookInstructionStep(
            code="apply_forward_migrations",
            instruction="Apply forward migrations before starting API or worker processes.",
            command_name="alembic upgrade head",
            route_name=None,
        ),
        RunbookInstructionStep(
            code="start_api_process",
            instruction=(
                "Start the API process after migrations. This runbook does not start "
                "or deploy the process."
            ),
            command_name="uvicorn vyro_growth.main:app --host 0.0.0.0 --port 8000",
            route_name=None,
        ),
        RunbookInstructionStep(
            code="probe_health",
            instruction="Probe liveness. Does not query the database or providers.",
            command_name=None,
            route_name="/health",
        ),
        RunbookInstructionStep(
            code="probe_ready",
            instruction=(
                "Probe readiness. Requires DATABASE_URL connectivity plus runtime "
                "config validation. Does not call live providers."
            ),
            command_name=None,
            route_name="/ready",
        ),
        RunbookInstructionStep(
            code="review_read_only_operator_surfaces",
            instruction=(
                "Review sanitized read-only operator surfaces and this runbook. "
                "Recording a decision does not execute. This is not permission to go live."
            ),
            command_name=CLI_COMMAND,
            route_name=HTTP_ROUTE,
        ),
        RunbookInstructionStep(
            code="keep_outbound_disabled",
            instruction=(
                "Leave OUTBOUND_ENABLED=false. Do not lift operator halt, enable "
                "live providers, or treat this runbook as a deploy."
            ),
            command_name=None,
            route_name=None,
        ),
    )


def _rollback_checklist() -> tuple[RunbookInstructionStep, ...]:
    return (
        RunbookInstructionStep(
            code="halt_api_worker_traffic",
            instruction="Halt traffic to the API/worker processes. Leave OUTBOUND_ENABLED=false.",
            command_name=None,
            route_name=None,
        ),
        RunbookInstructionStep(
            code="restore_previous_revision",
            instruction=(
                "Restore the previous application image or git revision. "
                "Do not deploy from this runbook."
            ),
            command_name=None,
            route_name=None,
        ),
        RunbookInstructionStep(
            code="restore_from_backup_if_needed",
            instruction=(
                "If a migration must be reversed, prefer restore-from-backup. "
                "alembic downgrade -1 is one step at a time only when backward-compatible."
            ),
            command_name="alembic downgrade -1",
            route_name=None,
        ),
        RunbookInstructionStep(
            code="confirm_health_ready_and_config",
            instruction=(
                "Confirm /health, /ready, vyro-growth check-config, and "
                "vyro-growth system-status."
            ),
            command_name="check-config",
            route_name="/health",
        ),
        RunbookInstructionStep(
            code="keep_operator_halt",
            instruction=(
                "Persistent operator halt should remain halted unless the owner "
                "later lifts it."
            ),
            command_name="system-status",
            route_name=None,
        ),
        RunbookInstructionStep(
            code="do_not_enable_live_providers",
            instruction=(
                "Do not roll forward by enabling live providers, outbound, or this runbook."
            ),
            command_name=None,
            route_name=None,
        ),
    )


def _post_deploy_verification() -> tuple[RunbookInstructionStep, ...]:
    return (
        RunbookInstructionStep(
            code="verify_health",
            instruction=(
                "Confirm GET /health reports outbound_enabled=false with default configuration."
            ),
            command_name=None,
            route_name="/health",
        ),
        RunbookInstructionStep(
            code="verify_ready",
            instruction="Confirm GET /ready without calling live providers.",
            command_name=None,
            route_name="/ready",
        ),
        RunbookInstructionStep(
            code="verify_check_config",
            instruction="Confirm vyro-growth check-config with OUTBOUND_ENABLED=false.",
            command_name="check-config",
            route_name=None,
        ),
        RunbookInstructionStep(
            code="verify_system_status",
            instruction="Confirm vyro-growth system-status remains halted and dry-run.",
            command_name="system-status",
            route_name="/internal/monitoring/status",
        ),
        RunbookInstructionStep(
            code="verify_launch_readiness",
            instruction=(
                "Confirm vyro-growth launch-readiness. ready_for_owner_review is not "
                "permission to go live."
            ),
            command_name="launch-readiness",
            route_name="/internal/launch-readiness",
        ),
        RunbookInstructionStep(
            code="verify_owner_handoff",
            instruction="Confirm owner-handoff-packet go_live_permitted=false.",
            command_name="owner-handoff-packet",
            route_name="/internal/owner-handoff-packet",
        ),
        RunbookInstructionStep(
            code="verify_compliance_binder",
            instruction="Confirm compliance-evidence-binder binder_is_not_go_live=true.",
            command_name="compliance-evidence-binder",
            route_name="/internal/compliance-evidence-binder",
        ),
        RunbookInstructionStep(
            code="verify_runbook_not_deployment",
            instruction=(
                "Re-export this runbook. runbook_is_not_deployment remains true and "
                "no deploy occurred."
            ),
            command_name=CLI_COMMAND,
            route_name=HTTP_ROUTE,
        ),
    )


def _remaining_checklist(
    *,
    evidence: ComplianceEvidenceBinder,
    outbound_enabled: bool,
    live_providers_enabled: bool,
    halt: HaltStatus,
    ci_and_local: RunbookCiAndLocalVerification,
) -> tuple[RunbookChecklistItem, ...]:
    selected: dict[str, RunbookChecklistItem] = {}

    def add(code: str, severity: str, source_section: str, status: str = "open") -> None:
        current = selected.get(code)
        if current is not None and _SEVERITY_RANK.get(current.severity, 0) >= _SEVERITY_RANK.get(
            severity, 0
        ):
            return
        selected[code] = RunbookChecklistItem(
            code=code,
            severity=severity,
            source_section=source_section,
            status=status,
        )

    add(RUNBOOK_NOT_DEPLOYMENT_CODE, FindingSeverity.INFO.value, SECTION_RUNBOOK)
    add(EXECUTION_DISABLED_CODE, FindingSeverity.INFO.value, SECTION_RUNBOOK)
    add(NextActionCode.HANDOFF_IS_NOT_GO_LIVE.value, FindingSeverity.INFO.value, SECTION_RUNBOOK)
    add(NextActionCode.BINDER_IS_NOT_GO_LIVE.value, FindingSeverity.INFO.value, SECTION_RUNBOOK)
    for item in evidence.remaining_manual_owner_checklist:
        add(item.code, item.severity, item.source_section, item.status)
    if not ci_and_local.smoke_gate.documented:
        add(
            NextActionCode.RESTORE_CI_SMOKE_GATE.value,
            FindingSeverity.BLOCKED.value,
            SECTION_CI,
        )
    if not ci_and_local.deploy_config_gate.documented:
        add(RESTORE_CI_DEPLOY_CONFIG_CODE, FindingSeverity.BLOCKED.value, SECTION_CI)
    if outbound_enabled:
        add(NextActionCode.DISABLE_OUTBOUND.value, FindingSeverity.BLOCKED.value, SECTION_HALT)
    else:
        add(NextActionCode.KEEP_OUTBOUND_DISABLED.value, FindingSeverity.INFO.value, SECTION_HALT)
    if live_providers_enabled:
        add(
            NextActionCode.DISABLE_LIVE_PROVIDERS.value,
            FindingSeverity.BLOCKED.value,
            SECTION_DEFAULTS,
        )
    else:
        add(
            NextActionCode.KEEP_LIVE_PROVIDERS_DISABLED.value,
            FindingSeverity.INFO.value,
            SECTION_DEFAULTS,
        )
    match halt:
        case HaltStatus.HALTED:
            add(
                NextActionCode.KEEP_OPERATOR_HALT.value,
                FindingSeverity.WARNING.value,
                SECTION_HALT,
            )
        case HaltStatus.UNAVAILABLE:
            add(
                NextActionCode.RECORD_OPERATOR_HALT.value,
                FindingSeverity.BLOCKED.value,
                SECTION_HALT,
            )
        case HaltStatus.CLEARED:
            pass
        case _:
            _unreachable(halt)
    return tuple(
        sorted(
            selected.values(),
            key=lambda item: (-_SEVERITY_RANK.get(item.severity, 0), item.code),
        )
    )


def _identity_payload(identity: RunbookIdentity) -> dict[str, Any]:
    return {
        "expected_base_branch": identity.expected_base_branch,
        "expected_workflow_path": identity.expected_workflow_path,
        "expected_release_channel": identity.expected_release_channel,
        "git_provider_called": False,
        "deployment_from_runbook": False,
    }


def _ci_payload(evidence: RunbookCiAndLocalVerification) -> dict[str, Any]:
    return {
        "required_ci_job_names": list(evidence.required_ci_job_names),
        "smoke_gate": _gate_payload(evidence.smoke_gate),
        "deploy_config_gate": _gate_payload(evidence.deploy_config_gate),
        "local_verification_commands": list(evidence.local_verification_commands),
        "github_actions_called": False,
    }


def _gate_payload(gate: RunbookCiGate) -> dict[str, Any]:
    return {
        "present": gate.present,
        "documented": gate.documented,
        "job_name": gate.job_name,
        "command_name": gate.command_name,
    }


def _defaults_payload(defaults: RunbookSafeDefaults) -> dict[str, Any]:
    return {
        "outbound_enabled_required": False,
        "outbound_enabled": defaults.outbound_enabled,
        "live_providers_enabled": defaults.live_providers_enabled,
        "required_flag_names": list(defaults.required_flag_names),
        "closed_provider_flag_names": list(defaults.closed_provider_flag_names),
        "missing_credential_names": list(defaults.missing_credential_names),
        "env_example_defaults_present": defaults.env_example_defaults_present,
        "dockerfile_defaults_present": defaults.dockerfile_defaults_present,
        "compose_defaults_present": defaults.compose_defaults_present,
        "secret_values_included": False,
    }


def _halt_payload(halt: RunbookHaltVerification) -> dict[str, Any]:
    return {
        "outbound_enabled": halt.outbound_enabled,
        "operator_halt_status": halt.operator_halt_status,
        "operator_halt_before": halt.operator_halt_before,
        "operator_halt_after": halt.operator_halt_after,
        "halt_changed": False,
        "keep_outbound_disabled": halt.keep_outbound_disabled,
        "verification_commands": list(halt.verification_commands),
        "verification_routes": list(halt.verification_routes),
    }


def _step_payload(item: RunbookInstructionStep) -> dict[str, Any]:
    return {
        "code": item.code,
        "instruction": item.instruction,
        "command_name": item.command_name,
        "route_name": item.route_name,
    }


def _reused_payload(summary: RunbookReusedSummaries) -> dict[str, Any]:
    return {
        "launch_readiness_overall_status": summary.launch_readiness_overall_status,
        "launch_readiness_blocker_codes": list(summary.launch_readiness_blocker_codes),
        "settings_preflight_overall_status": summary.settings_preflight_overall_status,
        "settings_preflight_blocked_count": summary.settings_preflight_blocked_count,
        "settings_preflight_execution_allowed": False,
        "owner_handoff_go_live_permitted": False,
        "owner_handoff_execution_allowed": False,
        "binder_is_not_go_live": True,
        "binder_command": summary.binder_command,
        "binder_route": summary.binder_route,
        "audit_timeline_matching_count": summary.audit_timeline_matching_count,
        "audit_timeline_route": summary.audit_timeline_route,
    }


def _format_markdown(runbook: ReleaseCandidateRunbook, payload: dict[str, Any]) -> str:
    lines = [
        "# Release-candidate deployment runbook",
        "",
        "This runbook is for future manual owner review only. It is not a "
        "deployment mechanism or permission to go live.",
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
        f"- deployment_allowed: {_bool_text(payload['deployment_allowed'])}",
        f"- deployment_attempted: {_bool_text(payload['deployment_attempted'])}",
        f"- deployed: {_bool_text(payload['deployed'])}",
        f"- runbook_is_not_deployment: {_bool_text(payload['runbook_is_not_deployment'])}",
        (
            "- future_execution_phase_exists: "
            f"{_bool_text(payload['future_execution_phase_exists'])}"
        ),
        (
            "- future_deployment_phase_exists: "
            f"{_bool_text(payload['future_deployment_phase_exists'])}"
        ),
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
        f"- blocker_codes: {_format_codes(runbook.blocker_codes)}",
        f"- missing_credential_names: {_format_codes(runbook.missing_credential_names)}",
        f"- closed_provider_flag_names: {_format_codes(runbook.closed_provider_flag_names)}",
        "",
        "## Release candidate identity and repo branch expectations",
        f"- expected_base_branch: {runbook.release_candidate_identity.expected_base_branch}",
        f"- expected_workflow_path: {runbook.release_candidate_identity.expected_workflow_path}",
        (
            "- expected_release_channel: "
            f"{runbook.release_candidate_identity.expected_release_channel}"
        ),
        (
            "- git_provider_called: "
            f"{_bool_text(runbook.release_candidate_identity.git_provider_called)}"
        ),
        (
            "- deployment_from_runbook: "
            f"{_bool_text(runbook.release_candidate_identity.deployment_from_runbook)}"
        ),
        "",
        "## Required CI gates and local dry-run verification commands",
        (
            "- required_ci_job_names: "
            f"{_format_codes(runbook.ci_gates_and_local_verification.required_ci_job_names)}"
        ),
        (
            "- smoke_gate: "
            f"present={_bool_text(runbook.ci_gates_and_local_verification.smoke_gate.present)} "
            "documented="
            f"{_bool_text(runbook.ci_gates_and_local_verification.smoke_gate.documented)} "
            f"job={runbook.ci_gates_and_local_verification.smoke_gate.job_name} "
            f"command={runbook.ci_gates_and_local_verification.smoke_gate.command_name}"
        ),
        (
            "- deploy_config_gate: "
            "present="
            f"{_bool_text(runbook.ci_gates_and_local_verification.deploy_config_gate.present)} "
            "documented="
            f"{_bool_text(runbook.ci_gates_and_local_verification.deploy_config_gate.documented)} "
            f"job={runbook.ci_gates_and_local_verification.deploy_config_gate.job_name} "
            f"command={runbook.ci_gates_and_local_verification.deploy_config_gate.command_name}"
        ),
        (
            "- local_verification_commands: "
            f"{_format_codes(runbook.ci_gates_and_local_verification.local_verification_commands)}"
        ),
        (
            "- github_actions_called: "
            f"{_bool_text(runbook.ci_gates_and_local_verification.github_actions_called)}"
        ),
        "",
        "## Required safe environment defaults",
        (
            "- outbound_enabled_required: "
            f"{_bool_text(runbook.safe_environment_defaults.outbound_enabled_required)}"
        ),
        f"- outbound_enabled: {_bool_text(runbook.safe_environment_defaults.outbound_enabled)}",
        (
            "- live_providers_enabled: "
            f"{_bool_text(runbook.safe_environment_defaults.live_providers_enabled)}"
        ),
        (
            "- required_flag_names: "
            f"{_format_codes(runbook.safe_environment_defaults.required_flag_names)}"
        ),
        (
            "- missing_credential_names: "
            f"{_format_codes(runbook.safe_environment_defaults.missing_credential_names)}"
        ),
        (
            "- closed_provider_flag_names: "
            f"{_format_codes(runbook.safe_environment_defaults.closed_provider_flag_names)}"
        ),
        (
            "- env_example_defaults_present: "
            f"{_bool_text(runbook.safe_environment_defaults.env_example_defaults_present)}"
        ),
        (
            "- dockerfile_defaults_present: "
            f"{_bool_text(runbook.safe_environment_defaults.dockerfile_defaults_present)}"
        ),
        (
            "- compose_defaults_present: "
            f"{_bool_text(runbook.safe_environment_defaults.compose_defaults_present)}"
        ),
        (
            "- secret_values_included: "
            f"{_bool_text(runbook.safe_environment_defaults.secret_values_included)}"
        ),
        "",
        "## Operator halt and outbound-disabled verification",
        f"- outbound_enabled: {_bool_text(runbook.operator_halt_and_outbound.outbound_enabled)}",
        f"- operator_halt: {runbook.operator_halt_and_outbound.operator_halt_status}",
        f"- halt_changed: {_bool_text(runbook.operator_halt_and_outbound.halt_changed)}",
        (
            "- keep_outbound_disabled: "
            f"{_bool_text(runbook.operator_halt_and_outbound.keep_outbound_disabled)}"
        ),
        (
            "- verification_commands: "
            f"{_format_codes(runbook.operator_halt_and_outbound.verification_commands)}"
        ),
        (
            "- verification_routes: "
            f"{_format_codes(runbook.operator_halt_and_outbound.verification_routes)}"
        ),
        "",
        "## Manual deployment sequence (instructions only)",
    ]
    for step in runbook.manual_deployment_sequence:
        lines.append(_format_step_line(step))
    lines.extend(["", "## Rollback checklist (instructions only)"])
    for step in runbook.rollback_checklist:
        lines.append(_format_step_line(step))
    lines.extend(["", "## Post-deploy read-only verification"])
    for step in runbook.post_deploy_verification:
        lines.append(_format_step_line(step))
    lines.extend(
        [
            "",
            "## Reused read-only summaries",
            (
                "- launch_readiness: "
                f"overall={runbook.reused_summaries.launch_readiness_overall_status} "
                f"blockers={_format_codes(runbook.reused_summaries.launch_readiness_blocker_codes)}"
            ),
            (
                "- settings_execution_preflight: "
                f"overall={runbook.reused_summaries.settings_preflight_overall_status} "
                f"blocked={runbook.reused_summaries.settings_preflight_blocked_count} "
                "execution_allowed="
                f"{_bool_text(runbook.reused_summaries.settings_preflight_execution_allowed)}"
            ),
            (
                "- owner_handoff: "
                "go_live_permitted="
                f"{_bool_text(runbook.reused_summaries.owner_handoff_go_live_permitted)} "
                "execution_allowed="
                f"{_bool_text(runbook.reused_summaries.owner_handoff_execution_allowed)}"
            ),
            (
                "- compliance_evidence_binder: "
                f"binder_is_not_go_live="
                f"{_bool_text(runbook.reused_summaries.binder_is_not_go_live)} "
                f"command={runbook.reused_summaries.binder_command} "
                f"route={runbook.reused_summaries.binder_route}"
            ),
            (
                "- operator_audit_timeline: "
                f"matching={runbook.reused_summaries.audit_timeline_matching_count} "
                f"route={runbook.reused_summaries.audit_timeline_route}"
            ),
            "",
            "## Remaining unresolved blockers and manual owner checklist",
        ]
    )
    for checklist_item in runbook.remaining_manual_owner_checklist:
        lines.append(
            f"- [{checklist_item.status}] {checklist_item.code} "
            f"severity={checklist_item.severity} source={checklist_item.source_section}"
        )
    return "\n".join(lines)


def _format_step_line(item: RunbookInstructionStep) -> str:
    command = item.command_name or "-"
    route = item.route_name or "-"
    return (
        f"- [{item.code}] {item.instruction} "
        f"command={command} route={route}"
    )


def _format_codes(values: Sequence[str]) -> str:
    return ",".join(values) if values else "-"


def _unique_sorted(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(sorted(set(values)))


def _bool_text(value: object) -> str:
    return "true" if value else "false"


def _unreachable(value: object) -> Never:
    raise RuntimeError(f"unhandled release candidate runbook variant: {value!r}")
