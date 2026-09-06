"""Read-only rehearsal outcome report export.

Phase 53 summarizes the current Phase 51 go-live rehearsal checklist into a
compact sanitized outcome packet. It reuses GoLiveRehearsalChecklistService
as the source of truth and never recalculates rehearsal state. It never
executes, applies settings, lifts halt, enables outbound, calls providers,
builds, publishes, deploys, or changes live state. This report is not
permission to go live and not an execution surface.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy.orm import Session

from vyro_growth.config import Settings
from vyro_growth.domain import FindingSeverity, NextActionCode
from vyro_growth.observability import sanitize_mapping, sanitize_operator_text
from vyro_growth.services.go_live_rehearsal_checklist import (
    CLI_COMMAND as REHEARSAL_CLI_COMMAND,
)
from vyro_growth.services.go_live_rehearsal_checklist import (
    HTML_ROUTE as REHEARSAL_HTML_ROUTE,
)
from vyro_growth.services.go_live_rehearsal_checklist import (
    HTTP_ROUTE as REHEARSAL_HTTP_ROUTE,
)
from vyro_growth.services.go_live_rehearsal_checklist import (
    OWNER_APPROVAL_TYPES,
    STEP_KINDS,
    GoLiveRehearsalChecklist,
    GoLiveRehearsalChecklistService,
    RehearsalNextAction,
    RehearsalStep,
)
from vyro_growth.services.operator_halt import HaltStatus, read_operator_halt
from vyro_growth.services.release_artifact_manifest import LocalGitMetadata

logger = structlog.get_logger(__name__)

PACKET_KIND = "rehearsal_outcome_report"
PACKET_PURPOSE = "manual_owner_rehearsal_outcome_review_only"
OUTCOME_NOT_GO_LIVE_CODE = NextActionCode.REHEARSAL_OUTCOME_REPORT_IS_NOT_GO_LIVE.value
EXECUTION_DISABLED_CODE = "execution_disabled_in_this_phase"
CLI_COMMAND = "rehearsal-outcome-report"
HTTP_ROUTE = "/internal/rehearsal-outcome-report"
HTML_ROUTE = "/internal/operator-rehearsal-outcome-report"
KNOWN_STEP_STATUSES: tuple[str, ...] = (
    FindingSeverity.INFO.value,
    FindingSeverity.WARNING.value,
    FindingSeverity.BLOCKED.value,
    "ready_for_owner_review",
    "open",
    "missing",
    "closed",
)
RELATED_COMMANDS: tuple[str, ...] = (
    REHEARSAL_CLI_COMMAND,
    "launch-readiness",
    "go-live-readiness-index",
    "launch-blockers-plan",
    "staged-rollout-plan",
    "owner-launch-dossier",
    "provider-setup-checklist",
    "settings-execution-preflight",
    "check-config",
    "smoke-dry-run",
    CLI_COMMAND,
    "supervised-pilot-plan",
    "system-status",
)
RELATED_ROUTES: tuple[str, ...] = (
    REHEARSAL_HTML_ROUTE,
    REHEARSAL_HTTP_ROUTE,
    "/internal/launch-readiness",
    "/internal/operator-go-live-readiness-index",
    "/internal/go-live-readiness-index",
    "/internal/operator-launch-blockers-plan",
    "/internal/launch-blockers-plan",
    "/internal/operator-staged-rollout-plan",
    "/internal/staged-rollout-plan",
    "/internal/operator-owner-launch-dossier",
    "/internal/owner-launch-dossier",
    "/internal/operator-provider-setup-checklist",
    "/internal/provider-setup-checklist",
    "/internal/operator-settings-execution-preflight",
    "/internal/settings-execution-preflight",
    HTML_ROUTE,
    HTTP_ROUTE,
    "/internal/operator-supervised-pilot-plan",
    "/internal/supervised-pilot-plan",
)


@dataclass(frozen=True)
class OutcomeCount:
    key: str
    count: int


@dataclass(frozen=True)
class OutcomeNextAction:
    code: str
    status: str
    label: str
    command_name: str | None
    json_route: str | None
    html_route: str | None
    config_name: str | None


@dataclass(frozen=True)
class RehearsalOutcomeReport:
    generated_at: datetime
    packet_kind: str
    purpose: str
    overall_status: str
    read_only: bool
    no_execution: bool
    no_go_live: bool
    no_deployment: bool
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
    build_allowed: bool
    artifact_publish_allowed: bool
    container_build_attempted: bool
    artifact_publish_attempted: bool
    outbound_enabled: bool
    live_providers_enabled: bool
    manual_review_only: bool
    rehearsal_outcome_report_is_not_go_live: bool
    report_is_not_permission_to_go_live: bool
    report_is_not_execution: bool
    go_live_rehearsal_checklist_is_not_go_live: bool
    rehearsal_is_not_a_script_runner: bool
    index_is_not_permission_to_go_live: bool
    dossier_is_not_permission_to_go_live: bool
    staged_rollout_plan_is_not_go_live: bool
    provider_setup_checklist_is_not_go_live: bool
    runbook_is_not_deployment: bool
    manifest_is_not_a_build_or_deploy: bool
    operator_halt_status: str
    operator_halt_before: str
    operator_halt_after: str
    rehearsal_step_count: int
    rehearsal_step_counts_by_status: tuple[OutcomeCount, ...]
    rehearsal_step_counts_by_kind: tuple[OutcomeCount, ...]
    rehearsal_step_counts_by_required_owner_approval_type: tuple[OutcomeCount, ...]
    expected_safe_assertion_count: int
    expected_safe_assertions_passed: int
    expected_safe_assertions_failed: int
    failed_safe_assertion_keys: tuple[str, ...]
    remaining_owner_approval_types: tuple[str, ...]
    closed_provider_flag_names: tuple[str, ...]
    missing_credential_names: tuple[str, ...]
    missing_config_names: tuple[str, ...]
    blocker_codes: tuple[str, ...]
    gate_codes: tuple[str, ...]
    outcome_summary: str
    cli_command: str
    http_route: str
    source_rehearsal_command: str
    source_rehearsal_route: str
    source_rehearsal_html_route: str
    source_rehearsal_overall_status: str
    source_launch_readiness_command: str
    source_launch_readiness_route: str
    source_launch_readiness_overall_status: str
    source_index_command: str
    source_index_route: str
    source_index_overall_status: str
    source_blockers_plan_command: str
    source_blockers_plan_route: str
    source_blockers_plan_overall_status: str
    source_staged_rollout_command: str
    source_staged_rollout_route: str
    source_staged_rollout_overall_status: str
    source_dossier_command: str
    source_dossier_route: str
    source_dossier_overall_status: str
    source_provider_setup_command: str
    source_provider_setup_route: str
    source_provider_setup_overall_status: str
    source_preflight_command: str
    source_preflight_route: str
    source_preflight_overall_status: str
    related_commands: tuple[str, ...]
    related_routes: tuple[str, ...]
    local_git: LocalGitMetadata
    next_actions: tuple[OutcomeNextAction, ...]


class RehearsalOutcomeReportService:
    """Compose a compact outcome packet from the Phase 51 rehearsal checklist."""

    def __init__(
        self,
        *,
        rehearsal: GoLiveRehearsalChecklistService | None = None,
    ) -> None:
        self.rehearsal = rehearsal or GoLiveRehearsalChecklistService()

    def build(self, db: Session, settings: Settings) -> RehearsalOutcomeReport:
        halt_before = read_operator_halt(db)
        checklist = self.rehearsal.build(db, settings)
        halt_after = read_operator_halt(db)
        if halt_after != halt_before:
            raise RuntimeError("rehearsal outcome report must not change operator halt status")
        report = _from_checklist(checklist, halt_before=halt_before, halt_after=halt_after)
        logger.info(
            "rehearsal_outcome_report_built",
            read_only=True,
            no_execution=True,
            no_go_live=True,
            no_deployment=True,
            overall_status=report.overall_status,
            operator_halt_status=report.operator_halt_status,
            outbound_enabled=report.outbound_enabled,
            go_live_permitted=False,
            execution_allowed=False,
            deployment_allowed=False,
            settings_applied=False,
            halt_changed=False,
            owner_approved=False,
            executed=0,
            rehearsal_outcome_report_is_not_go_live=True,
            go_live_rehearsal_checklist_is_not_go_live=True,
        )
        return report


def _from_checklist(
    checklist: GoLiveRehearsalChecklist,
    *,
    halt_before: HaltStatus,
    halt_after: HaltStatus,
) -> RehearsalOutcomeReport:
    passed = tuple(item for item in checklist.expected_safe_assertions if item.passed)
    failed_keys = _unique_sorted(
        item.key for item in checklist.expected_safe_assertions if not item.passed
    )
    status_counts = _counts(
        (step.status for step in checklist.rehearsal_steps),
        known=KNOWN_STEP_STATUSES,
    )
    kind_counts = _counts(
        (step.step_kind for step in checklist.rehearsal_steps),
        known=STEP_KINDS,
    )
    approval_counts = _counts(
        (step.required_owner_approval_type for step in checklist.rehearsal_steps),
        known=OWNER_APPROVAL_TYPES,
    )
    remaining_approvals = _unique_sorted(
        step.required_owner_approval_type
        for step in checklist.rehearsal_steps
        if step.required_owner_approval_type != "none" and _needs_follow_up(step.status)
    )
    missing_config_names = _unique_sorted(
        step.config_name
        for step in checklist.rehearsal_steps
        if step.config_name and _needs_follow_up(step.status)
    )
    next_actions = _next_actions(checklist)
    outcome_summary = _outcome_summary(
        checklist,
        failed_keys=failed_keys,
        remaining_approvals=remaining_approvals,
    )
    return RehearsalOutcomeReport(
        generated_at=datetime.now(tz=UTC),
        packet_kind=PACKET_KIND,
        purpose=PACKET_PURPOSE,
        overall_status=_safe_text(checklist.overall_status) or FindingSeverity.INFO.value,
        read_only=True,
        no_execution=True,
        no_go_live=True,
        no_deployment=True,
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
        build_allowed=False,
        artifact_publish_allowed=False,
        container_build_attempted=False,
        artifact_publish_attempted=False,
        outbound_enabled=checklist.outbound_enabled,
        live_providers_enabled=checklist.live_providers_enabled,
        manual_review_only=True,
        rehearsal_outcome_report_is_not_go_live=True,
        report_is_not_permission_to_go_live=True,
        report_is_not_execution=True,
        go_live_rehearsal_checklist_is_not_go_live=True,
        rehearsal_is_not_a_script_runner=True,
        index_is_not_permission_to_go_live=True,
        dossier_is_not_permission_to_go_live=True,
        staged_rollout_plan_is_not_go_live=True,
        provider_setup_checklist_is_not_go_live=True,
        runbook_is_not_deployment=True,
        manifest_is_not_a_build_or_deploy=True,
        operator_halt_status=halt_after.value,
        operator_halt_before=halt_before.value,
        operator_halt_after=halt_after.value,
        rehearsal_step_count=len(checklist.rehearsal_steps),
        rehearsal_step_counts_by_status=status_counts,
        rehearsal_step_counts_by_kind=kind_counts,
        rehearsal_step_counts_by_required_owner_approval_type=approval_counts,
        expected_safe_assertion_count=len(checklist.expected_safe_assertions),
        expected_safe_assertions_passed=len(passed),
        expected_safe_assertions_failed=len(failed_keys),
        failed_safe_assertion_keys=failed_keys,
        remaining_owner_approval_types=remaining_approvals,
        closed_provider_flag_names=tuple(checklist.closed_provider_flag_names),
        missing_credential_names=tuple(checklist.missing_credential_names),
        missing_config_names=missing_config_names,
        blocker_codes=tuple(checklist.blocker_codes),
        gate_codes=tuple(checklist.gate_codes),
        outcome_summary=outcome_summary,
        cli_command=CLI_COMMAND,
        http_route=HTTP_ROUTE,
        source_rehearsal_command=REHEARSAL_CLI_COMMAND,
        source_rehearsal_route=REHEARSAL_HTTP_ROUTE,
        source_rehearsal_html_route=REHEARSAL_HTML_ROUTE,
        source_rehearsal_overall_status=checklist.overall_status,
        source_launch_readiness_command=checklist.source_launch_readiness_command,
        source_launch_readiness_route=checklist.source_launch_readiness_route,
        source_launch_readiness_overall_status=checklist.source_launch_readiness_overall_status,
        source_index_command=checklist.source_index_command,
        source_index_route=checklist.source_index_route,
        source_index_overall_status=checklist.source_index_overall_status,
        source_blockers_plan_command=checklist.source_blockers_plan_command,
        source_blockers_plan_route=checklist.source_blockers_plan_route,
        source_blockers_plan_overall_status=checklist.source_blockers_plan_overall_status,
        source_staged_rollout_command=checklist.source_staged_rollout_command,
        source_staged_rollout_route=checklist.source_staged_rollout_route,
        source_staged_rollout_overall_status=checklist.source_staged_rollout_overall_status,
        source_dossier_command=checklist.source_dossier_command,
        source_dossier_route=checklist.source_dossier_route,
        source_dossier_overall_status=checklist.source_dossier_overall_status,
        source_provider_setup_command=checklist.source_provider_setup_command,
        source_provider_setup_route=checklist.source_provider_setup_route,
        source_provider_setup_overall_status=checklist.source_provider_setup_overall_status,
        source_preflight_command=checklist.source_preflight_command,
        source_preflight_route=checklist.source_preflight_route,
        source_preflight_overall_status=checklist.source_preflight_overall_status,
        related_commands=RELATED_COMMANDS,
        related_routes=RELATED_ROUTES,
        local_git=checklist.local_git,
        next_actions=next_actions,
    )


def _needs_follow_up(status: str) -> bool:
    return status not in {FindingSeverity.INFO.value, "ready_for_owner_review"}


def _counts(values: Iterable[str], *, known: Sequence[str]) -> tuple[OutcomeCount, ...]:
    tally: Counter[str] = Counter()
    for key in known:
        tally[key] = 0
    for raw in values:
        key = _safe_text(raw)
        if key:
            tally[key] += 1
    return tuple(OutcomeCount(key=key, count=tally[key]) for key in sorted(tally))


def _next_actions(checklist: GoLiveRehearsalChecklist) -> tuple[OutcomeNextAction, ...]:
    actions = [
        _action(
            OUTCOME_NOT_GO_LIVE_CODE,
            FindingSeverity.INFO.value,
            (
                "This rehearsal outcome report is a sanitized compact "
                "summary of the current manual go-live rehearsal checklist. "
                "It is not permission to go live and not an execution surface."
            ),
            command_name=CLI_COMMAND,
            json_route=HTTP_ROUTE,
            html_route=HTML_ROUTE,
        ),
        _action(
            EXECUTION_DISABLED_CODE,
            FindingSeverity.INFO.value,
            (
                "Execution remains disabled. This report does not run "
                "commands, apply settings, lift halt, enable outbound, "
                "deploy, build, publish, or call providers."
            ),
            command_name=CLI_COMMAND,
            json_route=HTTP_ROUTE,
            html_route=HTML_ROUTE,
        ),
        _action(
            NextActionCode.GO_LIVE_REHEARSAL_CHECKLIST_IS_NOT_GO_LIVE.value,
            checklist.overall_status,
            (
                "Review the source go-live rehearsal checklist. Manual "
                "rehearsal export only; it is not a script runner, not "
                "permission to go live, and not an execution surface."
            ),
            command_name=REHEARSAL_CLI_COMMAND,
            json_route=REHEARSAL_HTTP_ROUTE,
            html_route=REHEARSAL_HTML_ROUTE,
        ),
    ]
    seen = {item.code for item in actions}
    for item in checklist.next_actions:
        if item.code in seen:
            continue
        seen.add(item.code)
        actions.append(_from_rehearsal_action(item))
    return tuple(actions)


def _from_rehearsal_action(item: RehearsalNextAction) -> OutcomeNextAction:
    return _action(
        item.code,
        item.status,
        item.label,
        command_name=item.command_name,
        json_route=item.json_route,
        html_route=item.html_route,
        config_name=item.config_name,
    )


def _action(
    code: str,
    status: str,
    label: str,
    *,
    command_name: str | None = None,
    json_route: str | None = None,
    html_route: str | None = None,
    config_name: str | None = None,
) -> OutcomeNextAction:
    return OutcomeNextAction(
        code=_safe_text(code),
        status=_safe_text(status) or FindingSeverity.INFO.value,
        label=_safe_text(label),
        command_name=_safe_optional(command_name),
        json_route=_safe_optional(json_route),
        html_route=_safe_optional(html_route),
        config_name=_safe_optional(config_name),
    )


def _outcome_summary(
    checklist: GoLiveRehearsalChecklist,
    *,
    failed_keys: Sequence[str],
    remaining_approvals: Sequence[str],
) -> str:
    blocked_steps = _status_count(checklist.rehearsal_steps, FindingSeverity.BLOCKED.value)
    warning_steps = _status_count(checklist.rehearsal_steps, FindingSeverity.WARNING.value)
    failed_text = ",".join(failed_keys) if failed_keys else "none"
    return _safe_text(
        "Manual rehearsal outcome only, not permission to go live. "
        f"status={checklist.overall_status} "
        f"steps={len(checklist.rehearsal_steps)} "
        f"blocked={blocked_steps} warning={warning_steps} "
        f"assertions_failed={len(failed_keys)} failed_keys={failed_text} "
        f"remaining_owner_approval_types={len(remaining_approvals)}."
    )


def _status_count(steps: Sequence[RehearsalStep], status: str) -> int:
    return sum(1 for step in steps if step.status == status)


def _unique_sorted(values: Iterable[str | None]) -> tuple[str, ...]:
    cleaned = [_safe_text(item) for item in values if item]
    return tuple(sorted({item for item in cleaned if item}))


def _safe_optional(value: str | None) -> str | None:
    cleaned = _safe_text(value) if value is not None else ""
    return cleaned or None


def _safe_text(value: object) -> str:
    if value is None:
        return ""
    text = sanitize_operator_text(str(value))
    return text or ""


def _bool_text(value: object) -> str:
    return "true" if value else "false"


def outcome_report_payload(report: RehearsalOutcomeReport) -> dict[str, Any]:
    return {
        "generated_at": report.generated_at.isoformat(),
        "packet_kind": report.packet_kind,
        "purpose": report.purpose,
        "overall_status": report.overall_status,
        "read_only": True,
        "no_execution": True,
        "no_go_live": True,
        "no_deployment": True,
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
        "build_allowed": False,
        "artifact_publish_allowed": False,
        "container_build_attempted": False,
        "artifact_publish_attempted": False,
        "outbound_enabled": report.outbound_enabled,
        "live_providers_enabled": report.live_providers_enabled,
        "manual_review_only": True,
        "rehearsal_outcome_report_is_not_go_live": True,
        "report_is_not_permission_to_go_live": True,
        "report_is_not_execution": True,
        "go_live_rehearsal_checklist_is_not_go_live": True,
        "rehearsal_is_not_a_script_runner": True,
        "index_is_not_permission_to_go_live": True,
        "dossier_is_not_permission_to_go_live": True,
        "staged_rollout_plan_is_not_go_live": True,
        "provider_setup_checklist_is_not_go_live": True,
        "runbook_is_not_deployment": True,
        "manifest_is_not_a_build_or_deploy": True,
        "operator_halt_status": report.operator_halt_status,
        "operator_halt_before": report.operator_halt_before,
        "operator_halt_after": report.operator_halt_after,
        "rehearsal_step_count": report.rehearsal_step_count,
        "rehearsal_step_counts_by_status": [
            _count_payload(item) for item in report.rehearsal_step_counts_by_status
        ],
        "rehearsal_step_counts_by_kind": [
            _count_payload(item) for item in report.rehearsal_step_counts_by_kind
        ],
        "rehearsal_step_counts_by_required_owner_approval_type": [
            _count_payload(item)
            for item in report.rehearsal_step_counts_by_required_owner_approval_type
        ],
        "expected_safe_assertion_count": report.expected_safe_assertion_count,
        "expected_safe_assertions_passed": report.expected_safe_assertions_passed,
        "expected_safe_assertions_failed": report.expected_safe_assertions_failed,
        "failed_safe_assertion_keys": list(report.failed_safe_assertion_keys),
        "remaining_owner_approval_types": list(report.remaining_owner_approval_types),
        "closed_provider_flag_names": list(report.closed_provider_flag_names),
        "missing_credential_names": list(report.missing_credential_names),
        "missing_config_names": list(report.missing_config_names),
        "blocker_codes": list(report.blocker_codes),
        "gate_codes": list(report.gate_codes),
        "outcome_summary": report.outcome_summary,
        "cli_command": CLI_COMMAND,
        "http_route": HTTP_ROUTE,
        "source_rehearsal_command": report.source_rehearsal_command,
        "source_rehearsal_route": report.source_rehearsal_route,
        "source_rehearsal_html_route": report.source_rehearsal_html_route,
        "source_rehearsal_overall_status": report.source_rehearsal_overall_status,
        "source_launch_readiness_command": report.source_launch_readiness_command,
        "source_launch_readiness_route": report.source_launch_readiness_route,
        "source_launch_readiness_overall_status": report.source_launch_readiness_overall_status,
        "source_index_command": report.source_index_command,
        "source_index_route": report.source_index_route,
        "source_index_overall_status": report.source_index_overall_status,
        "source_blockers_plan_command": report.source_blockers_plan_command,
        "source_blockers_plan_route": report.source_blockers_plan_route,
        "source_blockers_plan_overall_status": report.source_blockers_plan_overall_status,
        "source_staged_rollout_command": report.source_staged_rollout_command,
        "source_staged_rollout_route": report.source_staged_rollout_route,
        "source_staged_rollout_overall_status": report.source_staged_rollout_overall_status,
        "source_dossier_command": report.source_dossier_command,
        "source_dossier_route": report.source_dossier_route,
        "source_dossier_overall_status": report.source_dossier_overall_status,
        "source_provider_setup_command": report.source_provider_setup_command,
        "source_provider_setup_route": report.source_provider_setup_route,
        "source_provider_setup_overall_status": report.source_provider_setup_overall_status,
        "source_preflight_command": report.source_preflight_command,
        "source_preflight_route": report.source_preflight_route,
        "source_preflight_overall_status": report.source_preflight_overall_status,
        "related_commands": list(report.related_commands),
        "related_routes": list(report.related_routes),
        "local_git": {
            "available": report.local_git.available,
            "current_branch": report.local_git.current_branch,
            "current_sha": report.local_git.current_sha,
            "working_tree_status": report.local_git.working_tree_status,
            "git_provider_called": False,
            "github_actions_called": False,
        },
        "next_actions": [_action_payload(action) for action in report.next_actions],
    }


def _count_payload(item: OutcomeCount) -> dict[str, Any]:
    return {"key": item.key, "count": item.count}


def _action_payload(action: OutcomeNextAction) -> dict[str, Any]:
    return {
        "code": action.code,
        "status": action.status,
        "label": action.label,
        "command_name": action.command_name,
        "json_route": action.json_route,
        "html_route": action.html_route,
        "config_name": action.config_name,
    }


def format_rehearsal_outcome_report(
    report: RehearsalOutcomeReport,
    *,
    as_json: bool = False,
) -> str:
    payload = sanitize_mapping(outcome_report_payload(report))
    if as_json:
        return json.dumps(payload, sort_keys=True)
    return _format_markdown(report, payload)


def _format_markdown(report: RehearsalOutcomeReport, payload: dict[str, Any]) -> str:
    lines = [
        "# Rehearsal outcome report",
        "",
        "This report is a sanitized compact summary of the current "
        "manual go-live rehearsal checklist. It reuses that checklist as "
        "the source of truth and never executes commands, applies "
        "settings, lifts halt, enables outbound, deploys, builds, or "
        "publishes. It is not permission to go live and not an "
        "execution surface.",
        "",
        f"- overall: {payload['overall_status']}",
        f"- packet_kind: {payload['packet_kind']}",
        f"- purpose: {payload['purpose']}",
        f"- read_only: {_bool_text(payload['read_only'])}",
        f"- no_execution: {_bool_text(payload['no_execution'])}",
        f"- no_go_live: {_bool_text(payload['no_go_live'])}",
        f"- no_deployment: {_bool_text(payload['no_deployment'])}",
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
        f"- build_allowed: {_bool_text(payload['build_allowed'])}",
        f"- artifact_publish_allowed: {_bool_text(payload['artifact_publish_allowed'])}",
        f"- manual_review_only: {_bool_text(payload['manual_review_only'])}",
        (
            "- rehearsal_outcome_report_is_not_go_live: "
            f"{_bool_text(payload['rehearsal_outcome_report_is_not_go_live'])}"
        ),
        (
            "- report_is_not_permission_to_go_live: "
            f"{_bool_text(payload['report_is_not_permission_to_go_live'])}"
        ),
        f"- report_is_not_execution: {_bool_text(payload['report_is_not_execution'])}",
        (
            "- go_live_rehearsal_checklist_is_not_go_live: "
            f"{_bool_text(payload['go_live_rehearsal_checklist_is_not_go_live'])}"
        ),
        (
            "- rehearsal_is_not_a_script_runner: "
            f"{_bool_text(payload['rehearsal_is_not_a_script_runner'])}"
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
        f"- source_rehearsal_command: {payload['source_rehearsal_command']}",
        f"- source_rehearsal_route: {payload['source_rehearsal_route']}",
        f"- source_rehearsal_html_route: {payload['source_rehearsal_html_route']}",
        f"- source_rehearsal_overall_status: {payload['source_rehearsal_overall_status']}",
        f"- source_launch_readiness_command: {payload['source_launch_readiness_command']}",
        f"- source_index_command: {payload['source_index_command']}",
        f"- source_blockers_plan_command: {payload['source_blockers_plan_command']}",
        f"- source_staged_rollout_command: {payload['source_staged_rollout_command']}",
        f"- source_dossier_command: {payload['source_dossier_command']}",
        f"- source_provider_setup_command: {payload['source_provider_setup_command']}",
        f"- source_preflight_command: {payload['source_preflight_command']}",
        f"- rehearsal_step_count: {payload['rehearsal_step_count']}",
        f"- expected_safe_assertion_count: {payload['expected_safe_assertion_count']}",
        f"- expected_safe_assertions_passed: {payload['expected_safe_assertions_passed']}",
        f"- expected_safe_assertions_failed: {payload['expected_safe_assertions_failed']}",
        f"- failed_safe_assertion_keys: {_format_codes(report.failed_safe_assertion_keys)}",
        f"- remaining_owner_approval_types: {_format_codes(report.remaining_owner_approval_types)}",
        f"- blocker_codes: {_format_codes(report.blocker_codes)}",
        f"- gate_codes: {_format_codes(report.gate_codes)}",
        f"- missing_credential_names: {_format_codes(report.missing_credential_names)}",
        f"- missing_config_names: {_format_codes(report.missing_config_names)}",
        f"- closed_provider_flag_names: {_format_codes(report.closed_provider_flag_names)}",
        f"- outcome_summary: {payload['outcome_summary']}",
        "",
        "## Live-blocking flags",
        f"- OUTBOUND_ENABLED={_bool_text(report.outbound_enabled)}",
        f"- operator_halt_status={report.operator_halt_status}",
        f"- live_providers_enabled={_bool_text(report.live_providers_enabled)}",
        "- read_only=true",
        "- no_execution=true",
        "- no_go_live=true",
        "- no_deployment=true",
        "- manual_review_only=true",
        "- execution_allowed=false",
        "- go_live_permitted=false",
        "- deployment_allowed=false",
        "- settings_applied=false",
        "- halt_changed=false",
        "- owner_approved=false",
        "- rehearsal_outcome_report_is_not_go_live=true",
        "- report_is_not_permission_to_go_live=true",
        "- report_is_not_execution=true",
        "- go_live_rehearsal_checklist_is_not_go_live=true",
        f"- local_git_available: {_bool_text(report.local_git.available)}",
        f"- current_branch: {report.local_git.current_branch}",
        f"- current_sha: {report.local_git.current_sha}",
        f"- working_tree_status: {report.local_git.working_tree_status}",
        f"- git_provider_called: {_bool_text(report.local_git.git_provider_called)}",
        f"- github_actions_called: {_bool_text(report.local_git.github_actions_called)}",
        "",
        "## Rehearsal step counts by status",
    ]
    for item in report.rehearsal_step_counts_by_status:
        lines.append(f"- {item.key}: {item.count}")
    lines.extend(["", "## Rehearsal step counts by kind"])
    for item in report.rehearsal_step_counts_by_kind:
        lines.append(f"- {item.key}: {item.count}")
    lines.extend(["", "## Rehearsal step counts by required owner approval type"])
    for item in report.rehearsal_step_counts_by_required_owner_approval_type:
        lines.append(f"- {item.key}: {item.count}")
    lines.extend(["", "## Owner next actions"])
    for action in report.next_actions:
        command_name = action.command_name or "-"
        json_route = action.json_route or "-"
        html_route = action.html_route or "-"
        config_name = action.config_name or "-"
        lines.append(
            f"- [{action.status}] {action.code} command={command_name} "
            f"json_route={json_route} html_route={html_route} "
            f"config_name={config_name} label={action.label}"
        )
    if not report.next_actions:
        lines.append("- next_actions: none")
    return "\n".join(lines)


def _format_codes(values: Sequence[str]) -> str:
    return ",".join(values) if values else "-"
