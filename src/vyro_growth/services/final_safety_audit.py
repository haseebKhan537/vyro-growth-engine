"""Read-only final repository and safety audit packet.

Phase 75 consolidates existing launch-readiness, contact-validation,
provider-setup, manifest, runbook, and dossier surfaces into one
sanitized pre-validation audit. It reuses those services as source
material and never recalculates readiness. It never executes
validation, grants approval, writes state, runs migrations, calls
providers, sends email, enrolls campaigns, places calls, autodials,
uses AI voice, books meetings, creates Meet links, launches ads,
spends, publishes, deploys, applies settings, lifts halt, or enables
outbound. This audit is not permission to run real-world validation
and is not an execution surface.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Never

from sqlalchemy.orm import Session

from vyro_growth.config import Settings, live_provider_flags
from vyro_growth.observability import sanitize_mapping
from vyro_growth.services.contact_validation import (
    BLOCKED_STATUS,
    INFO_STATUS,
    OVERALL_STATUSES,
    PLAN_CLI_COMMAND,
    PLAN_HTTP_ROUTE,
    READY_STATUS,
    REPORT_CLI_COMMAND,
    REPORT_HTTP_ROUTE,
    WARNING_STATUS,
    ContactValidationReport,
    ContactValidationService,
)
from vyro_growth.services.contact_validation import HTML_ROUTE as CONTACT_VALIDATION_HTML_ROUTE
from vyro_growth.services.launch_readiness import (
    CI_WORKFLOW_RELATIVE,
    REQUIRED_FLAG_NAMES,
    LaunchReadinessChecklist,
    LaunchReadinessService,
    default_repo_root,
    inspect_ci_smoke_gate,
)
from vyro_growth.services.operator_halt import HaltStatus, read_operator_halt
from vyro_growth.services.owner_launch_dossier import CLI_COMMAND as DOSSIER_CLI_COMMAND
from vyro_growth.services.owner_launch_dossier import HTTP_ROUTE as DOSSIER_HTTP_ROUTE
from vyro_growth.services.provider_setup_checklist import CLI_COMMAND as PROVIDER_SETUP_CLI_COMMAND
from vyro_growth.services.provider_setup_checklist import HTTP_ROUTE as PROVIDER_SETUP_HTTP_ROUTE
from vyro_growth.services.release_artifact_manifest import (
    CLI_COMMAND as MANIFEST_CLI_COMMAND,
)
from vyro_growth.services.release_artifact_manifest import (
    HTTP_ROUTE as MANIFEST_HTTP_ROUTE,
)
from vyro_growth.services.release_artifact_manifest import (
    LocalGitMetadata,
    _migration_inventory,
    inspect_local_git,
)
from vyro_growth.services.release_candidate_runbook import (
    CLI_COMMAND as RUNBOOK_CLI_COMMAND,
)
from vyro_growth.services.release_candidate_runbook import (
    HTTP_ROUTE as RUNBOOK_HTTP_ROUTE,
)
from vyro_growth.services.release_candidate_runbook import (
    LOCAL_VERIFICATION_COMMANDS,
    REQUIRED_CI_JOB_NAMES,
)
from vyro_growth.services.supervised_validation_run_packet import (
    CLI_COMMAND as VALIDATION_PACKET_CLI_COMMAND,
)
from vyro_growth.services.supervised_validation_run_packet import (
    HTML_ROUTE as VALIDATION_PACKET_HTML_ROUTE,
)
from vyro_growth.services.supervised_validation_run_packet import (
    HTTP_ROUTE as VALIDATION_PACKET_HTTP_ROUTE,
)
from vyro_growth.services.supervised_validation_run_packet import (
    OWNER_DECISION_SPECS,
)

PACKET_KIND = "final_safety_repository_audit"
PACKET_PURPOSE = "manual_owner_pre_validation_repository_audit_only"
CLI_COMMAND = "final-safety-audit"
HTTP_ROUTE = "/internal/final-safety-audit"
LAUNCH_READINESS_COMMAND = "launch-readiness"
LAUNCH_READINESS_ROUTE = "/internal/launch-readiness"
PROVIDER_SETUP_HTML_ROUTE = "/internal/operator-provider-setup-checklist"
DOSSIER_HTML_ROUTE = "/internal/operator-owner-launch-dossier"
MANIFEST_HTML_ROUTE = "/internal/operator-release-artifact-manifest"
RUNBOOK_HTML_ROUTE = "/internal/operator-release-candidate-runbook"
PHASE_HEADING_RE = re.compile(
    r"^## Phase (\d+)\s+[—-]\s+(.+?)(?:\s+\(current\))?\s*$",
    re.MULTILINE,
)
CLI_PARSER_RE = re.compile(r'subparsers\.add_parser\(\s*"([^"]+)"')
CONTACT_PARSER_RE = re.compile(
    r'_add_contact_validation_parser\(\s*subparsers,\s*"([^"]+)"'
)
ROUTE_RE = re.compile(r'@app\.(?:get|post|put|patch|delete)\("([^"]+)"')
DOC_SPECS: tuple[tuple[str, str], ...] = (
    ("readme", "README.md"),
    ("roadmap", "docs/ROADMAP.md"),
    ("architecture", "docs/ARCHITECTURE.md"),
    ("security", "docs/SECURITY.md"),
    ("deployment", "docs/DEPLOYMENT.md"),
    ("operator_health", "docs/OPERATOR_HEALTH.md"),
)
OPEN_ISSUES: tuple[tuple[str, str], ...] = (
    ("P75-001", "Owner approval for a bounded 200-practice validation segment"),
    ("P75-002", "Owner approval for live decision-maker credentials"),
    ("P75-003", "Owner approval for live email-verification credentials"),
    ("P75-004", "Owner permission for a supervised validation run"),
    ("P75-005", "Owner decision to enable outbound"),
    ("P75-006", "Owner decision to lift operator halt"),
    ("P75-007", "Owner approval to execute settings or approval packets"),
    ("P75-008", "Owner approval to deploy, publish, or call Actions"),
)
EXTRA_OWNER_DECISIONS: tuple[tuple[str, str], ...] = (
    (
        "execute_approval_packets",
        "Execute owner approval packets later. This audit does not execute them.",
    ),
    (
        "execute_settings_requests",
        "Execute live settings requests later. This audit does not apply settings.",
    ),
    (
        "deploy_or_publish",
        "Deploy or publish later. This audit is not a deploy.",
    ),
    (
        "call_github_actions",
        "Call GitHub Actions later. This audit does not call Actions.",
    ),
)
RELATED_COMMANDS: tuple[str, ...] = tuple(
    dict.fromkeys(
        (
            LAUNCH_READINESS_COMMAND,
            PLAN_CLI_COMMAND,
            REPORT_CLI_COMMAND,
            VALIDATION_PACKET_CLI_COMMAND,
            PROVIDER_SETUP_CLI_COMMAND,
            MANIFEST_CLI_COMMAND,
            RUNBOOK_CLI_COMMAND,
            DOSSIER_CLI_COMMAND,
            "check-config",
            "smoke-dry-run",
            "check-smoke-output",
            CLI_COMMAND,
        )
    )
)
RELATED_ROUTES: tuple[str, ...] = tuple(
    dict.fromkeys(
        (
            LAUNCH_READINESS_ROUTE,
            PLAN_HTTP_ROUTE,
            REPORT_HTTP_ROUTE,
            CONTACT_VALIDATION_HTML_ROUTE,
            VALIDATION_PACKET_HTTP_ROUTE,
            VALIDATION_PACKET_HTML_ROUTE,
            PROVIDER_SETUP_HTTP_ROUTE,
            PROVIDER_SETUP_HTML_ROUTE,
            MANIFEST_HTTP_ROUTE,
            MANIFEST_HTML_ROUTE,
            RUNBOOK_HTTP_ROUTE,
            RUNBOOK_HTML_ROUTE,
            DOSSIER_HTTP_ROUTE,
            DOSSIER_HTML_ROUTE,
            HTTP_ROUTE,
        )
    )
)
SAFE_LOCAL_COMMANDS: tuple[str, ...] = (
    *LOCAL_VERIFICATION_COMMANDS,
    f"vyro-growth {CLI_COMMAND} --json",
)


@dataclass(frozen=True)
class NamedItem:
    name: str


@dataclass(frozen=True)
class PhaseInventoryItem:
    phase_number: int
    title: str


@dataclass(frozen=True)
class MigrationInventoryItem:
    filename: str
    revision_id: str


@dataclass(frozen=True)
class LiveFlagItem:
    name: str
    enabled: bool


@dataclass(frozen=True)
class CiJobItem:
    name: str
    present: bool


@dataclass(frozen=True)
class DocCoverageItem:
    key: str
    path: str
    present: bool
    mentioned: bool


@dataclass(frozen=True)
class OpenIssueItem:
    issue_number: str
    title: str


@dataclass(frozen=True)
class OwnerApprovalItem:
    code: str
    name: str
    granted: bool


@dataclass(frozen=True)
class StatusCount:
    key: str
    count: int


@dataclass(frozen=True)
class FindingCodeItem:
    code: str
    severity: str


@dataclass(frozen=True)
class OwnerNextStep:
    code: str
    status: str
    label: str
    command_name: str | None
    json_route: str | None


@dataclass(frozen=True)
class FinalSafetyAuditPacket:
    generated_at: datetime
    packet_kind: str
    purpose: str
    overall_status: str
    read_only: bool
    export_only: bool
    dry_run_only: bool
    no_execution: bool
    no_outbound: bool
    no_provider_calls: bool
    no_send: bool
    no_call: bool
    no_book: bool
    no_spend: bool
    no_deploy: bool
    no_autodial: bool
    no_ai_voice: bool
    no_migrations: bool
    no_github_actions: bool
    manual_review_only: bool
    outbound_attempted: bool
    live_call_attempted: bool
    live_provider_calls_attempted: bool
    smtp_attempted: bool
    autodial_attempted: bool
    campaign_enrolled: bool
    booking_attempted: bool
    meet_link_created: bool
    ads_launched: bool
    execution_allowed: bool
    owner_approved: bool
    spend_attempted: bool
    campaign_launched: bool
    halt_changed: bool
    settings_applied: bool
    scoring_thresholds_changed: bool
    github_actions_called: bool
    git_provider_called: bool
    outbound_enabled: bool
    operator_halt_status: str
    operator_halt_before: str
    operator_halt_after: str
    operator_halt_unchanged: bool
    kill_switch_outbound_disabled: bool
    kill_switch_operator_halt_honored: bool
    dual_kill_switch_proof: bool
    live_providers_enabled: bool
    live_providers: dict[str, bool]
    live_flag_inventory: tuple[LiveFlagItem, ...]
    source_launch_readiness_overall_status: str
    source_contact_validation_overall_status: str
    launch_readiness_is_not_execution: bool
    contact_validation_is_not_outbound: bool
    contact_validation_is_not_live_send: bool
    final_safety_audit_is_not_execution: bool
    export_is_not_permission_to_validate: bool
    supervised_validation_run_permitted: bool
    phases: tuple[PhaseInventoryItem, ...]
    commands: tuple[NamedItem, ...]
    routes: tuple[NamedItem, ...]
    migrations: tuple[MigrationInventoryItem, ...]
    ci_jobs: tuple[CiJobItem, ...]
    safe_local_commands: tuple[str, ...]
    ci_smoke_gate_present: bool
    ci_smoke_gate_documented: bool
    finding_codes: tuple[FindingCodeItem, ...]
    blocked_code_count: int
    warning_code_count: int
    info_code_count: int
    status_counts: tuple[StatusCount, ...]
    documentation_coverage: tuple[DocCoverageItem, ...]
    open_issues: tuple[OpenIssueItem, ...]
    owner_approvals_required: tuple[OwnerApprovalItem, ...]
    related_commands: tuple[str, ...]
    related_routes: tuple[str, ...]
    local_git: LocalGitMetadata
    cli_command: str
    http_route: str
    next_actions: tuple[OwnerNextStep, ...]


class FinalSafetyAuditService:
    """Repository/safety audit over existing read-only surfaces. Never executes."""

    def build(
        self,
        db: Session,
        settings: Settings,
        *,
        repo_root: Path | None = None,
        launch_readiness: LaunchReadinessService | None = None,
        contact_validation: ContactValidationService | None = None,
    ) -> FinalSafetyAuditPacket:
        halt_before = read_operator_halt(db)
        root = repo_root or default_repo_root()
        readiness = (launch_readiness or LaunchReadinessService()).assess(
            db,
            settings,
            repo_root=root,
        )
        report = (contact_validation or ContactValidationService()).build_report(
            db,
            settings,
            repo_root=root,
        )
        local_git = inspect_local_git(root)
        halt_after = read_operator_halt(db)
        _assert_halt_unchanged(halt_before, halt_after)
        flags = _live_flag_inventory(settings)
        findings = _finding_codes(readiness, report)
        status_counts = _status_counts(findings)
        counts_by_key = {item.key: item.count for item in status_counts}
        approvals = _owner_approvals()
        next_actions = _next_actions(readiness, report)
        smoke = inspect_ci_smoke_gate(root)
        return FinalSafetyAuditPacket(
            generated_at=datetime.now(tz=UTC),
            packet_kind=PACKET_KIND,
            purpose=PACKET_PURPOSE,
            overall_status=_checked_status(readiness.overall_status),
            read_only=True,
            export_only=True,
            dry_run_only=True,
            no_execution=True,
            no_outbound=True,
            no_provider_calls=True,
            no_send=True,
            no_call=True,
            no_book=True,
            no_spend=True,
            no_deploy=True,
            no_autodial=True,
            no_ai_voice=True,
            no_migrations=True,
            no_github_actions=True,
            manual_review_only=True,
            outbound_attempted=False,
            live_call_attempted=False,
            live_provider_calls_attempted=False,
            smtp_attempted=False,
            autodial_attempted=False,
            campaign_enrolled=False,
            booking_attempted=False,
            meet_link_created=False,
            ads_launched=False,
            execution_allowed=False,
            owner_approved=False,
            spend_attempted=False,
            campaign_launched=False,
            halt_changed=False,
            settings_applied=False,
            scoring_thresholds_changed=False,
            github_actions_called=False,
            git_provider_called=False,
            outbound_enabled=readiness.outbound_enabled,
            operator_halt_status=halt_after.value,
            operator_halt_before=halt_before.value,
            operator_halt_after=halt_after.value,
            operator_halt_unchanged=halt_before is halt_after,
            kill_switch_outbound_disabled=not readiness.outbound_enabled,
            kill_switch_operator_halt_honored=halt_before is halt_after,
            dual_kill_switch_proof=(
                (not readiness.outbound_enabled) and halt_before is halt_after
            ),
            live_providers_enabled=readiness.live_providers_enabled,
            live_providers=dict(readiness.live_providers),
            live_flag_inventory=flags,
            source_launch_readiness_overall_status=readiness.overall_status,
            source_contact_validation_overall_status=report.overall_status,
            launch_readiness_is_not_execution=True,
            contact_validation_is_not_outbound=True,
            contact_validation_is_not_live_send=True,
            final_safety_audit_is_not_execution=True,
            export_is_not_permission_to_validate=True,
            supervised_validation_run_permitted=False,
            phases=_phase_inventory(root),
            commands=_command_inventory(root),
            routes=_route_inventory(root),
            migrations=_migrations(root),
            ci_jobs=_ci_jobs(root),
            safe_local_commands=SAFE_LOCAL_COMMANDS,
            ci_smoke_gate_present=smoke.present,
            ci_smoke_gate_documented=smoke.documented,
            finding_codes=findings,
            blocked_code_count=counts_by_key.get(BLOCKED_STATUS, 0),
            warning_code_count=counts_by_key.get(WARNING_STATUS, 0),
            info_code_count=counts_by_key.get(INFO_STATUS, 0),
            status_counts=status_counts,
            documentation_coverage=_documentation_coverage(root),
            open_issues=_open_issues(),
            owner_approvals_required=approvals,
            related_commands=RELATED_COMMANDS,
            related_routes=RELATED_ROUTES,
            local_git=local_git,
            cli_command=CLI_COMMAND,
            http_route=HTTP_ROUTE,
            next_actions=next_actions,
        )


def final_safety_audit_payload(packet: FinalSafetyAuditPacket) -> dict[str, Any]:
    return {
        "generated_at": packet.generated_at.isoformat(),
        "packet_kind": packet.packet_kind,
        "purpose": packet.purpose,
        "overall_status": packet.overall_status,
        "read_only": packet.read_only,
        "export_only": packet.export_only,
        "dry_run_only": packet.dry_run_only,
        "no_execution": packet.no_execution,
        "no_outbound": packet.no_outbound,
        "no_provider_calls": packet.no_provider_calls,
        "no_send": packet.no_send,
        "no_call": packet.no_call,
        "no_book": packet.no_book,
        "no_spend": packet.no_spend,
        "no_deploy": packet.no_deploy,
        "no_autodial": packet.no_autodial,
        "no_ai_voice": packet.no_ai_voice,
        "no_migrations": packet.no_migrations,
        "no_github_actions": packet.no_github_actions,
        "manual_review_only": packet.manual_review_only,
        "outbound_attempted": packet.outbound_attempted,
        "live_call_attempted": packet.live_call_attempted,
        "live_provider_calls_attempted": packet.live_provider_calls_attempted,
        "smtp_attempted": packet.smtp_attempted,
        "autodial_attempted": packet.autodial_attempted,
        "campaign_enrolled": packet.campaign_enrolled,
        "booking_attempted": packet.booking_attempted,
        "meet_link_created": packet.meet_link_created,
        "ads_launched": packet.ads_launched,
        "execution_allowed": packet.execution_allowed,
        "owner_approved": packet.owner_approved,
        "spend_attempted": packet.spend_attempted,
        "campaign_launched": packet.campaign_launched,
        "halt_changed": packet.halt_changed,
        "settings_applied": packet.settings_applied,
        "scoring_thresholds_changed": packet.scoring_thresholds_changed,
        "github_actions_called": packet.github_actions_called,
        "git_provider_called": packet.git_provider_called,
        "outbound_enabled": packet.outbound_enabled,
        "operator_halt_status": packet.operator_halt_status,
        "operator_halt_before": packet.operator_halt_before,
        "operator_halt_after": packet.operator_halt_after,
        "operator_halt_unchanged": packet.operator_halt_unchanged,
        "kill_switch_outbound_disabled": packet.kill_switch_outbound_disabled,
        "kill_switch_operator_halt_honored": packet.kill_switch_operator_halt_honored,
        "dual_kill_switch_proof": packet.dual_kill_switch_proof,
        "live_providers_enabled": packet.live_providers_enabled,
        "live_providers": dict(packet.live_providers),
        "live_flag_inventory": [_flag_payload(item) for item in packet.live_flag_inventory],
        "source_launch_readiness_overall_status": (
            packet.source_launch_readiness_overall_status
        ),
        "source_contact_validation_overall_status": (
            packet.source_contact_validation_overall_status
        ),
        "launch_readiness_is_not_execution": packet.launch_readiness_is_not_execution,
        "contact_validation_is_not_outbound": packet.contact_validation_is_not_outbound,
        "contact_validation_is_not_live_send": packet.contact_validation_is_not_live_send,
        "final_safety_audit_is_not_execution": packet.final_safety_audit_is_not_execution,
        "export_is_not_permission_to_validate": packet.export_is_not_permission_to_validate,
        "supervised_validation_run_permitted": packet.supervised_validation_run_permitted,
        "phases": [_phase_payload(item) for item in packet.phases],
        "commands": [_named_payload(item) for item in packet.commands],
        "routes": [_named_payload(item) for item in packet.routes],
        "migrations": [_migration_payload(item) for item in packet.migrations],
        "ci_jobs": [_ci_job_payload(item) for item in packet.ci_jobs],
        "safe_local_commands": list(packet.safe_local_commands),
        "ci_smoke_gate_present": packet.ci_smoke_gate_present,
        "ci_smoke_gate_documented": packet.ci_smoke_gate_documented,
        "finding_codes": [_finding_payload(item) for item in packet.finding_codes],
        "blocked_code_count": packet.blocked_code_count,
        "warning_code_count": packet.warning_code_count,
        "info_code_count": packet.info_code_count,
        "status_counts": [_count_payload(item) for item in packet.status_counts],
        "documentation_coverage": [
            _doc_payload(item) for item in packet.documentation_coverage
        ],
        "open_issues": [_issue_payload(item) for item in packet.open_issues],
        "owner_approvals_required": [
            _approval_payload(item) for item in packet.owner_approvals_required
        ],
        "related_commands": list(packet.related_commands),
        "related_routes": list(packet.related_routes),
        "local_git": {
            "available": packet.local_git.available,
            "current_branch": packet.local_git.current_branch,
            "current_sha": packet.local_git.current_sha,
            "working_tree_status": packet.local_git.working_tree_status,
            "git_provider_called": False,
            "github_actions_called": False,
        },
        "cli_command": packet.cli_command,
        "http_route": packet.http_route,
        "next_actions": [_action_payload(item) for item in packet.next_actions],
    }


def format_final_safety_audit(
    packet: FinalSafetyAuditPacket,
    *,
    as_json: bool = False,
) -> str:
    payload = sanitize_mapping(final_safety_audit_payload(packet))
    if as_json:
        return json.dumps(payload, sort_keys=True)
    return _format_markdown(packet, payload)


def _live_flag_inventory(settings: Settings) -> tuple[LiveFlagItem, ...]:
    mapped = {
        _live_flag_env_name(key): enabled
        for key, enabled in live_provider_flags(settings).items()
    }
    mapped["EMAIL_VERIFICATION_SMTP_ENABLED"] = settings.email_verification_smtp_enabled
    mapped["OUTBOUND_ENABLED"] = settings.outbound_enabled
    expected = set(REQUIRED_FLAG_NAMES) | {"EMAIL_VERIFICATION_SMTP_ENABLED"}
    present = set(mapped)
    if present != expected:
        raise RuntimeError(
            f"unhandled live flag inventory names extra={sorted(present - expected)!r} "
            f"missing={sorted(expected - present)!r}"
        )
    return tuple(
        LiveFlagItem(name=name, enabled=mapped[name]) for name in sorted(mapped)
    )


def _live_flag_env_name(key: str) -> str:
    upper = key.upper()
    enabled_name = f"{upper}_ENABLED"
    live_name = f"{upper}_LIVE_ENABLED"
    if enabled_name in REQUIRED_FLAG_NAMES:
        return enabled_name
    if live_name in REQUIRED_FLAG_NAMES:
        return live_name
    raise RuntimeError(f"unhandled live provider flag key={key!r}")


def _phase_inventory(repo_root: Path) -> tuple[PhaseInventoryItem, ...]:
    path = repo_root / "docs" / "ROADMAP.md"
    if not path.is_file():
        return ()
    items: list[PhaseInventoryItem] = []
    seen: set[int] = set()
    for match in PHASE_HEADING_RE.finditer(path.read_text(encoding="utf-8")):
        number = int(match.group(1))
        if number in seen:
            continue
        seen.add(number)
        title = match.group(2).strip()
        items.append(PhaseInventoryItem(phase_number=number, title=title))
    items.sort(key=lambda item: item.phase_number)
    return tuple(items)


def _command_inventory(repo_root: Path) -> tuple[NamedItem, ...]:
    path = repo_root / "src" / "vyro_growth" / "cli.py"
    if not path.is_file():
        return ()
    text = path.read_text(encoding="utf-8")
    names = set(CLI_PARSER_RE.findall(text))
    names.update(CONTACT_PARSER_RE.findall(text))
    return tuple(NamedItem(name=name) for name in sorted(names))


def _route_inventory(repo_root: Path) -> tuple[NamedItem, ...]:
    path = repo_root / "src" / "vyro_growth" / "main.py"
    if not path.is_file():
        return ()
    names = set(ROUTE_RE.findall(path.read_text(encoding="utf-8")))
    return tuple(NamedItem(name=name) for name in sorted(names))


def _migrations(repo_root: Path) -> tuple[MigrationInventoryItem, ...]:
    return tuple(
        MigrationInventoryItem(filename=item.filename, revision_id=item.revision_id)
        for item in _migration_inventory(repo_root)
    )


def _ci_jobs(repo_root: Path) -> tuple[CiJobItem, ...]:
    path = repo_root / CI_WORKFLOW_RELATIVE
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    return tuple(
        CiJobItem(name=name, present=f"  {name}:" in text or f"{name}:" in text)
        for name in REQUIRED_CI_JOB_NAMES
    )


def _documentation_coverage(repo_root: Path) -> tuple[DocCoverageItem, ...]:
    needles = (CLI_COMMAND, HTTP_ROUTE)
    items: list[DocCoverageItem] = []
    for key, relative in DOC_SPECS:
        path = repo_root / relative
        present = path.is_file()
        text = path.read_text(encoding="utf-8") if present else ""
        mentioned = all(needle in text for needle in needles)
        items.append(
            DocCoverageItem(
                key=key,
                path=relative,
                present=present,
                mentioned=mentioned,
            )
        )
    return tuple(items)


def _open_issues() -> tuple[OpenIssueItem, ...]:
    return tuple(
        OpenIssueItem(issue_number=number, title=title) for number, title in OPEN_ISSUES
    )


def _owner_approvals() -> tuple[OwnerApprovalItem, ...]:
    specs = tuple(dict.fromkeys((*OWNER_DECISION_SPECS, *EXTRA_OWNER_DECISIONS)))
    return tuple(
        OwnerApprovalItem(code=code, name=name, granted=False) for code, name in specs
    )


def _finding_codes(
    readiness: LaunchReadinessChecklist,
    report: ContactValidationReport,
) -> tuple[FindingCodeItem, ...]:
    items: list[FindingCodeItem] = []
    seen: set[tuple[str, str]] = set()
    for finding in readiness.findings:
        severity = _bucket_status(finding.severity)
        key = (finding.code, severity)
        if key in seen:
            continue
        seen.add(key)
        items.append(FindingCodeItem(code=finding.code, severity=severity))
    for comparison in report.threshold_comparisons:
        if comparison.blocking and not comparison.passed:
            severity = BLOCKED_STATUS
        elif comparison.passed:
            severity = INFO_STATUS
        else:
            severity = WARNING_STATUS
        key = (comparison.code, severity)
        if key in seen:
            continue
        seen.add(key)
        items.append(FindingCodeItem(code=comparison.code, severity=severity))
    return tuple(items)


def _status_counts(findings: Sequence[FindingCodeItem]) -> tuple[StatusCount, ...]:
    counts: Counter[str] = Counter()
    for item in findings:
        counts[_bucket_status(item.severity)] += 1
    return (
        StatusCount(key=BLOCKED_STATUS, count=counts.get(BLOCKED_STATUS, 0)),
        StatusCount(key=WARNING_STATUS, count=counts.get(WARNING_STATUS, 0)),
        StatusCount(key=INFO_STATUS, count=counts.get(INFO_STATUS, 0)),
    )


def _next_actions(
    readiness: LaunchReadinessChecklist,
    report: ContactValidationReport,
) -> tuple[OwnerNextStep, ...]:
    outbound_status = BLOCKED_STATUS if readiness.outbound_enabled else INFO_STATUS
    halt_unchanged = readiness.operator_halt_before == readiness.operator_halt_after
    halt_status = INFO_STATUS if halt_unchanged else BLOCKED_STATUS
    live_status = BLOCKED_STATUS if readiness.live_providers_enabled else INFO_STATUS
    return (
        OwnerNextStep(
            code="keep_outbound_disabled",
            status=_bucket_status(outbound_status),
            label="Keep OUTBOUND_ENABLED=false. This audit is not permission to enable outbound.",
            command_name=LAUNCH_READINESS_COMMAND,
            json_route=LAUNCH_READINESS_ROUTE,
        ),
        OwnerNextStep(
            code="keep_operator_halt_unchanged",
            status=_bucket_status(halt_status),
            label="Keep operator halt unchanged. This audit never lifts halt or applies settings.",
            command_name=LAUNCH_READINESS_COMMAND,
            json_route=LAUNCH_READINESS_ROUTE,
        ),
        OwnerNextStep(
            code="keep_live_providers_disabled_until_owner_approval",
            status=_bucket_status(live_status),
            label=(
                "Keep live provider flags false until a later owner-approved step. "
                "This audit does not call providers."
            ),
            command_name=PROVIDER_SETUP_CLI_COMMAND,
            json_route=PROVIDER_SETUP_HTTP_ROUTE,
        ),
        OwnerNextStep(
            code="review_launch_readiness",
            status=_bucket_status(readiness.overall_status),
            label=(
                "Review the sanitized launch-readiness checklist. "
                "That export is not an execution surface."
            ),
            command_name=LAUNCH_READINESS_COMMAND,
            json_route=LAUNCH_READINESS_ROUTE,
        ),
        OwnerNextStep(
            code="review_contact_validation_report",
            status=_bucket_status(report.overall_status),
            label=(
                "Review aggregate contact-validation status from stored local data. "
                "This audit does not call providers."
            ),
            command_name=REPORT_CLI_COMMAND,
            json_route=REPORT_HTTP_ROUTE,
        ),
        OwnerNextStep(
            code="review_supervised_validation_run_packet",
            status=INFO_STATUS,
            label=(
                "Review the Phase 73/74 supervised validation packet. "
                "supervised_validation_run_permitted remains false."
            ),
            command_name=VALIDATION_PACKET_CLI_COMMAND,
            json_route=VALIDATION_PACKET_HTTP_ROUTE,
        ),
        OwnerNextStep(
            code="later_owner_approval_required_before_validation",
            status=INFO_STATUS,
            label=(
                "A later explicit owner approval is required before any real-world "
                "validation. owner_approved stays false."
            ),
            command_name=CLI_COMMAND,
            json_route=HTTP_ROUTE,
        ),
        OwnerNextStep(
            code="supervised_validation_run_not_permitted",
            status=INFO_STATUS,
            label=(
                "supervised_validation_run_permitted=false. Do not execute validation, "
                "send email, enroll campaigns, or place calls from this audit."
            ),
            command_name=CLI_COMMAND,
            json_route=HTTP_ROUTE,
        ),
    )


def _bucket_status(status: str) -> str:
    checked = _checked_status(status)
    if checked == READY_STATUS:
        return INFO_STATUS
    if checked == BLOCKED_STATUS:
        return BLOCKED_STATUS
    if checked == WARNING_STATUS:
        return WARNING_STATUS
    if checked == INFO_STATUS:
        return INFO_STATUS
    return _unknown_status(checked)


def _checked_status(status: str) -> str:
    if status not in OVERALL_STATUSES:
        return _unknown_status(status)
    return status


def _unknown_status(status: str) -> Never:
    raise RuntimeError(f"unhandled final safety audit status: {status!r}")


def _assert_halt_unchanged(before: HaltStatus, after: HaltStatus) -> None:
    if after is not before:
        raise RuntimeError("final safety audit must not change operator halt")


def _flag_payload(item: LiveFlagItem) -> dict[str, Any]:
    return {"name": item.name, "enabled": item.enabled}


def _phase_payload(item: PhaseInventoryItem) -> dict[str, Any]:
    return {"phase_number": item.phase_number, "title": item.title}


def _named_payload(item: NamedItem) -> dict[str, Any]:
    return {"name": item.name}


def _migration_payload(item: MigrationInventoryItem) -> dict[str, Any]:
    return {"filename": item.filename, "revision_id": item.revision_id}


def _ci_job_payload(item: CiJobItem) -> dict[str, Any]:
    return {"name": item.name, "present": item.present}


def _finding_payload(item: FindingCodeItem) -> dict[str, Any]:
    return {"code": item.code, "severity": item.severity}


def _count_payload(item: StatusCount) -> dict[str, Any]:
    return {"key": item.key, "count": item.count}


def _doc_payload(item: DocCoverageItem) -> dict[str, Any]:
    return {
        "key": item.key,
        "path": item.path,
        "present": item.present,
        "mentioned": item.mentioned,
    }


def _issue_payload(item: OpenIssueItem) -> dict[str, Any]:
    return {"issue_number": item.issue_number, "title": item.title}


def _approval_payload(item: OwnerApprovalItem) -> dict[str, Any]:
    return {"code": item.code, "name": item.name, "granted": item.granted}


def _action_payload(item: OwnerNextStep) -> dict[str, Any]:
    return {
        "code": item.code,
        "status": item.status,
        "label": item.label,
        "command_name": item.command_name,
        "json_route": item.json_route,
    }


def _format_markdown(packet: FinalSafetyAuditPacket, payload: dict[str, Any]) -> str:
    lines = [
        "# Final safety and repository audit",
        "",
        (
            f"status={payload['overall_status']} "
            f"kind={payload['packet_kind']} "
            f"purpose={payload['purpose']}"
        ),
        f"- generated_at: {payload['generated_at']}",
        (
            f"- operator_halt_before={payload['operator_halt_before']} "
            f"status={payload['operator_halt_status']} "
            f"after={payload['operator_halt_after']} "
            f"unchanged={_bool_text(payload['operator_halt_unchanged'])}"
        ),
        f"- outbound_enabled: {_bool_text(payload['outbound_enabled'])}",
        f"- live_providers_enabled: {_bool_text(payload['live_providers_enabled'])}",
        f"- cli_command: {payload['cli_command']}",
        f"- http_route: {payload['http_route']}",
        (
            "- source_launch_readiness_overall_status: "
            f"{payload['source_launch_readiness_overall_status']}"
        ),
        (
            "- source_contact_validation_overall_status: "
            f"{payload['source_contact_validation_overall_status']}"
        ),
        "",
        "## Safety flags",
        "- read_only=true",
        "- export_only=true",
        "- dry_run_only=true",
        "- no_execution=true",
        "- no_outbound=true",
        "- no_provider_calls=true",
        "- no_send=true",
        "- no_call=true",
        "- no_book=true",
        "- no_spend=true",
        "- no_deploy=true",
        "- no_autodial=true",
        "- no_ai_voice=true",
        "- no_migrations=true",
        "- no_github_actions=true",
        "- owner_approved=false",
        "- supervised_validation_run_permitted=false",
        "- execution_allowed=false",
        "- export_is_not_permission_to_validate=true",
        "- final_safety_audit_is_not_execution=true",
        f"- halt_changed={_bool_text(payload['halt_changed'])}",
        f"- operator_halt_unchanged={_bool_text(payload['operator_halt_unchanged'])}",
        "",
        "## Kill-switch proof",
        (
            "- kill_switch_outbound_disabled: "
            f"{_bool_text(payload['kill_switch_outbound_disabled'])}"
        ),
        (
            "- kill_switch_operator_halt_honored: "
            f"{_bool_text(payload['kill_switch_operator_halt_honored'])}"
        ),
        f"- dual_kill_switch_proof: {_bool_text(payload['dual_kill_switch_proof'])}",
        f"- github_actions_called: {_bool_text(payload['github_actions_called'])}",
        f"- git_provider_called: {_bool_text(payload['git_provider_called'])}",
        "",
        "## Provider / live flags",
    ]
    for flag in packet.live_flag_inventory:
        lines.append(f"- {flag.name} enabled={_bool_text(flag.enabled)}")
    lines.extend(["", "## Phase inventory"])
    for phase in packet.phases:
        lines.append(f"- phase {phase.phase_number}: {phase.title}")
    lines.extend(["", "## Command inventory"])
    for command_item in packet.commands:
        lines.append(f"- {command_item.name}")
    lines.extend(["", "## Route inventory"])
    for route in packet.routes:
        lines.append(f"- {route.name}")
    lines.extend(["", "## Migration inventory"])
    for migration in packet.migrations:
        lines.append(f"- {migration.filename} revision_id={migration.revision_id}")
    lines.extend(["", "## Test / CI inventory"])
    lines.append(f"- ci_smoke_gate_present: {_bool_text(packet.ci_smoke_gate_present)}")
    lines.append(
        f"- ci_smoke_gate_documented: {_bool_text(packet.ci_smoke_gate_documented)}"
    )
    for job in packet.ci_jobs:
        lines.append(f"- ci_job {job.name} present={_bool_text(job.present)}")
    for command in packet.safe_local_commands:
        lines.append(f"- safe_local_command: {command}")
    lines.extend(
        [
            "",
            "## Status code counts",
            f"- blocked_code_count: {payload['blocked_code_count']}",
            f"- warning_code_count: {payload['warning_code_count']}",
            f"- info_code_count: {payload['info_code_count']}",
        ]
    )
    lines.extend(["", "## Finding codes"])
    for finding in packet.finding_codes:
        lines.append(f"- [{finding.severity}] {finding.code}")
    lines.extend(["", "## Documentation coverage"])
    for doc in packet.documentation_coverage:
        lines.append(
            f"- {doc.key} path={doc.path} present={_bool_text(doc.present)} "
            f"mentioned={_bool_text(doc.mentioned)}"
        )
    lines.extend(["", "## Open issues"])
    for issue in packet.open_issues:
        lines.append(f"- {issue.issue_number} {issue.title}")
    lines.extend(["", "## Owner approvals still required"])
    for approval in packet.owner_approvals_required:
        lines.append(
            f"- {approval.code} granted={_bool_text(approval.granted)} name={approval.name}"
        )
    lines.extend(["", "## Owner next steps"])
    for action in packet.next_actions:
        command_name = action.command_name or "-"
        json_route = action.json_route or "-"
        lines.append(
            f"- [{action.status}] {action.code} command={command_name} "
            f"json_route={json_route} label={action.label}"
        )
    lines.extend(
        [
            "",
            "## Local git",
            f"- available: {_bool_text(packet.local_git.available)}",
            f"- current_branch: {packet.local_git.current_branch}",
            f"- current_sha: {packet.local_git.current_sha}",
            f"- working_tree_status: {packet.local_git.working_tree_status}",
            "- git_provider_called: false",
            "- github_actions_called: false",
        ]
    )
    return "\n".join(lines)


def _bool_text(value: object) -> str:
    return "true" if value is True else "false"
