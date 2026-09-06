"""Read-only owner launch dossier export.

Phase 47 consolidates existing go-live readiness, launch-blocker, staged
rollout, owner-handoff, compliance binder, runbook, manifest, settings
preflight, and operator-audit surfaces into one sanitized owner/operator
packet. It reuses those services as source material and never recalculates
readiness. It never executes, applies settings, lifts halt, enables
outbound, calls providers, builds, publishes, deploys, or changes live
state. This dossier is not permission to go live and is not an execution
surface.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy.orm import Session

from vyro_growth.config import Settings
from vyro_growth.domain import FindingSeverity, NextActionCode
from vyro_growth.observability import sanitize_mapping, sanitize_operator_text
from vyro_growth.services.compliance_evidence_binder import (
    CLI_COMMAND as BINDER_CLI_COMMAND,
)
from vyro_growth.services.compliance_evidence_binder import (
    HTTP_ROUTE as BINDER_HTTP_ROUTE,
)
from vyro_growth.services.go_live_readiness_index import (
    CLI_COMMAND as INDEX_CLI_COMMAND,
)
from vyro_growth.services.go_live_readiness_index import (
    HTTP_ROUTE as INDEX_HTTP_ROUTE,
)
from vyro_growth.services.launch_blockers_plan import (
    CLI_COMMAND as BLOCKERS_CLI_COMMAND,
)
from vyro_growth.services.launch_blockers_plan import (
    HTTP_ROUTE as BLOCKERS_HTTP_ROUTE,
)
from vyro_growth.services.operator_audit_timeline import (
    OperatorAuditTimeline,
    OperatorAuditTimelineService,
)
from vyro_growth.services.operator_halt import HaltStatus, read_operator_halt
from vyro_growth.services.owner_handoff import OwnerHandoffPacket, OwnerHandoffPacketService
from vyro_growth.services.release_artifact_manifest import (
    CLI_COMMAND as MANIFEST_CLI_COMMAND,
)
from vyro_growth.services.release_artifact_manifest import (
    HTTP_ROUTE as MANIFEST_HTTP_ROUTE,
)
from vyro_growth.services.release_artifact_manifest import LocalGitMetadata
from vyro_growth.services.release_candidate_runbook import (
    CLI_COMMAND as RUNBOOK_CLI_COMMAND,
)
from vyro_growth.services.release_candidate_runbook import (
    HTTP_ROUTE as RUNBOOK_HTTP_ROUTE,
)
from vyro_growth.services.settings_execution_preflight import (
    SettingsExecutionPreflight,
    SettingsExecutionPreflightService,
)
from vyro_growth.services.staged_rollout_plan import (
    CLI_COMMAND as STAGED_CLI_COMMAND,
)
from vyro_growth.services.staged_rollout_plan import (
    HTTP_ROUTE as STAGED_HTTP_ROUTE,
)
from vyro_growth.services.staged_rollout_plan import StagedRolloutPlan, StagedRolloutPlanService

logger = structlog.get_logger(__name__)

PACKET_KIND = "owner_launch_dossier"
PACKET_PURPOSE = "manual_owner_review_export_only"
DOSSIER_NOT_GO_LIVE_CODE = NextActionCode.OWNER_LAUNCH_DOSSIER_IS_NOT_GO_LIVE.value
EXECUTION_DISABLED_CODE = "execution_disabled_in_this_phase"
CLI_COMMAND = "owner-launch-dossier"
HTTP_ROUTE = "/internal/owner-launch-dossier"
HTML_ROUTE = "/internal/operator-owner-launch-dossier"
HANDOFF_CLI_COMMAND = "owner-handoff-packet"
HANDOFF_HTTP_ROUTE = "/internal/owner-handoff-packet"
HANDOFF_HTML_ROUTE = "/internal/operator-owner-handoff-packet"
PREFLIGHT_CLI_COMMAND = "settings-execution-preflight"
PREFLIGHT_HTTP_ROUTE = "/internal/settings-execution-preflight"
PREFLIGHT_HTML_ROUTE = "/internal/operator-settings-execution-preflight"
AUDIT_HTML_ROUTE = "/internal/operator-audit-timeline"
INDEX_HTML_ROUTE = "/internal/operator-go-live-readiness-index"
BLOCKERS_HTML_ROUTE = "/internal/operator-launch-blockers-plan"
STAGED_HTML_ROUTE = "/internal/operator-staged-rollout-plan"
BINDER_HTML_ROUTE = "/internal/operator-compliance-evidence-binder"
RUNBOOK_HTML_ROUTE = "/internal/operator-release-candidate-runbook"
MANIFEST_HTML_ROUTE = "/internal/operator-release-artifact-manifest"
SOURCE_KEYS: tuple[str, ...] = (
    "go-live-readiness-index",
    "launch-blockers-plan",
    "staged-rollout-plan",
    "owner-handoff-packet",
    "compliance-evidence-binder",
    "release-candidate-runbook",
    "release-artifact-manifest",
    "settings-execution-preflight",
    "operator-audit-timeline",
)
RELATED_COMMANDS: tuple[str, ...] = (
    INDEX_CLI_COMMAND,
    BLOCKERS_CLI_COMMAND,
    STAGED_CLI_COMMAND,
    HANDOFF_CLI_COMMAND,
    BINDER_CLI_COMMAND,
    RUNBOOK_CLI_COMMAND,
    MANIFEST_CLI_COMMAND,
    PREFLIGHT_CLI_COMMAND,
    "launch-readiness",
    "check-config",
    "smoke-dry-run",
    CLI_COMMAND,
    "provider-setup-checklist",
    "go-live-rehearsal-checklist",
    "rehearsal-outcome-report",
    "supervised-pilot-plan",
    "system-status",
)
RELATED_ROUTES: tuple[str, ...] = (
    INDEX_HTML_ROUTE,
    INDEX_HTTP_ROUTE,
    BLOCKERS_HTML_ROUTE,
    BLOCKERS_HTTP_ROUTE,
    STAGED_HTML_ROUTE,
    STAGED_HTTP_ROUTE,
    HANDOFF_HTML_ROUTE,
    HANDOFF_HTTP_ROUTE,
    BINDER_HTML_ROUTE,
    BINDER_HTTP_ROUTE,
    RUNBOOK_HTML_ROUTE,
    RUNBOOK_HTTP_ROUTE,
    MANIFEST_HTML_ROUTE,
    MANIFEST_HTTP_ROUTE,
    PREFLIGHT_HTML_ROUTE,
    PREFLIGHT_HTTP_ROUTE,
    AUDIT_HTML_ROUTE,
    HTML_ROUTE,
    HTTP_ROUTE,
    "/internal/operator-provider-setup-checklist",
    "/internal/provider-setup-checklist",
    "/internal/operator-go-live-rehearsal-checklist",
    "/internal/go-live-rehearsal-checklist",
    "/internal/operator-rehearsal-outcome-report",
    "/internal/rehearsal-outcome-report",
    "/internal/operator-supervised-pilot-plan",
    "/internal/supervised-pilot-plan",
)
_STATUS_RANK = {
    FindingSeverity.INFO.value: 0,
    "ready_for_owner_review": 1,
    "open": 1,
    "missing": 2,
    "closed": 2,
    FindingSeverity.WARNING.value: 2,
    FindingSeverity.BLOCKED.value: 3,
}


@dataclass(frozen=True)
class DossierSourceSurface:
    key: str
    label: str
    purpose: str
    overall_status: str
    command_name: str | None
    json_route: str | None
    html_route: str | None
    blocker_codes: tuple[str, ...]
    gate_codes: tuple[str, ...]
    missing_credential_names: tuple[str, ...]
    read_only: bool
    no_execution: bool
    go_live_permitted: bool
    deployment_allowed: bool


@dataclass(frozen=True)
class DossierNextAction:
    code: str
    status: str
    label: str
    command_name: str | None
    json_route: str | None
    html_route: str | None
    config_name: str | None


@dataclass(frozen=True)
class DossierSettingsPreflightSummary:
    overall_status: str
    request_count: int
    pending_decision_count: int
    approved_decision_count: int
    blocked_count: int
    executable_count: int
    blocker_codes: tuple[str, ...]
    missing_gate_codes: tuple[str, ...]
    missing_credential_names: tuple[str, ...]
    closed_provider_flag_names: tuple[str, ...]
    no_execution: bool
    dry_run_only: bool
    executed: int
    settings_applied: bool
    execution_allowed: bool


@dataclass(frozen=True)
class DossierAuditSummary:
    matching_count: int
    shown_count: int
    truncated: bool
    available_event_types: tuple[str, ...]
    available_sources: tuple[str, ...]
    available_statuses: tuple[str, ...]
    read_only: bool
    no_execution: bool
    executed: int
    halt_changed: bool
    outbound_enabled: bool
    operator_halt_status: str


@dataclass(frozen=True)
class OwnerLaunchDossier:
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
    owner_launch_dossier_is_not_go_live: bool
    dossier_is_not_permission_to_go_live: bool
    dossier_is_not_execution: bool
    index_is_not_permission_to_go_live: bool
    handoff_is_not_go_live: bool
    binder_is_not_go_live: bool
    runbook_is_not_deployment: bool
    manifest_is_not_a_build_or_deploy: bool
    staged_rollout_plan_is_not_go_live: bool
    operator_halt_status: str
    operator_halt_before: str
    operator_halt_after: str
    closed_provider_flag_names: tuple[str, ...]
    missing_credential_names: tuple[str, ...]
    blocker_codes: tuple[str, ...]
    gate_codes: tuple[str, ...]
    cli_command: str
    http_route: str
    source_index_command: str
    source_index_route: str
    source_index_overall_status: str
    source_blockers_plan_command: str
    source_blockers_plan_route: str
    source_blockers_plan_overall_status: str
    source_staged_rollout_command: str
    source_staged_rollout_route: str
    source_staged_rollout_overall_status: str
    source_handoff_command: str
    source_handoff_route: str
    source_handoff_overall_status: str
    source_binder_command: str
    source_binder_route: str
    source_binder_overall_status: str
    source_runbook_command: str
    source_runbook_route: str
    source_runbook_overall_status: str
    source_manifest_command: str
    source_manifest_route: str
    source_manifest_overall_status: str
    source_preflight_command: str
    source_preflight_route: str
    source_preflight_overall_status: str
    source_audit_route: str
    source_audit_matching_count: int
    related_commands: tuple[str, ...]
    related_routes: tuple[str, ...]
    local_git: LocalGitMetadata
    sources: tuple[DossierSourceSurface, ...]
    settings_preflight: DossierSettingsPreflightSummary
    operator_audit: DossierAuditSummary
    next_actions: tuple[DossierNextAction, ...]


class OwnerLaunchDossierService:
    """Compose existing read-only exports into one owner-review dossier."""

    def __init__(
        self,
        *,
        staged_rollout: StagedRolloutPlanService | None = None,
        owner_handoff: OwnerHandoffPacketService | None = None,
        settings_preflight: SettingsExecutionPreflightService | None = None,
        audit_timeline: OperatorAuditTimelineService | None = None,
    ) -> None:
        self.staged_rollout = staged_rollout or StagedRolloutPlanService()
        self.owner_handoff = owner_handoff or OwnerHandoffPacketService()
        self.settings_preflight = settings_preflight or SettingsExecutionPreflightService()
        self.audit_timeline = audit_timeline or OperatorAuditTimelineService()

    def build(self, db: Session, settings: Settings) -> OwnerLaunchDossier:
        halt_before = read_operator_halt(db)
        staged = self.staged_rollout.build(db, settings)
        handoff = self.owner_handoff.build(db, settings)
        preflight = self.settings_preflight.simulate(db, settings)
        audit = self.audit_timeline.timeline(db, settings)
        halt_after = read_operator_halt(db)
        if halt_after != halt_before:
            raise RuntimeError("owner launch dossier must not change operator halt status")
        sources = _sources(staged, handoff, preflight, audit)
        preflight_summary = _preflight_summary(preflight)
        audit_summary = _audit_summary(audit)
        next_actions = _next_actions(staged, handoff, preflight, audit)
        missing_credentials = _unique_sorted(
            (
                *staged.missing_credential_names,
                *handoff.missing_credential_names,
                *preflight.missing_credential_names,
            )
        )
        closed_flags = _unique_sorted(
            (
                *staged.closed_provider_flag_names,
                *handoff.closed_provider_flag_names,
                *preflight.closed_provider_flag_names,
            )
        )
        blocker_codes = _unique_sorted(
            (
                *staged.blocker_codes,
                *handoff.blocker_codes,
                *preflight.blocker_codes,
                *(code for source in sources for code in source.blocker_codes),
                *(action.code for action in next_actions),
            )
        )
        gate_codes = _unique_sorted(
            (
                *(code for stage in staged.stages for code in stage.gate_codes),
                *preflight.missing_gate_codes,
                "outbound_disabled",
                "operator_halt",
                "live_providers_disabled",
                "no_execution",
                "no_go_live",
                "no_deployment",
                "no_build",
                "no_publish",
            )
        )
        dossier = OwnerLaunchDossier(
            generated_at=datetime.now(tz=UTC),
            packet_kind=PACKET_KIND,
            purpose=PACKET_PURPOSE,
            overall_status=_worst_status(
                staged.source_index_overall_status,
                staged.source_blockers_plan_overall_status,
                staged.overall_status,
                handoff.overall_status,
                staged.source_binder_overall_status,
                staged.source_runbook_overall_status,
                staged.source_manifest_overall_status,
                preflight.overall_status,
                *(source.overall_status for source in sources),
            ),
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
            outbound_enabled=settings.outbound_enabled,
            live_providers_enabled=staged.live_providers_enabled,
            manual_review_only=True,
            owner_launch_dossier_is_not_go_live=True,
            dossier_is_not_permission_to_go_live=True,
            dossier_is_not_execution=True,
            index_is_not_permission_to_go_live=True,
            handoff_is_not_go_live=True,
            binder_is_not_go_live=True,
            runbook_is_not_deployment=True,
            manifest_is_not_a_build_or_deploy=True,
            staged_rollout_plan_is_not_go_live=True,
            operator_halt_status=halt_after.value,
            operator_halt_before=halt_before.value,
            operator_halt_after=halt_after.value,
            closed_provider_flag_names=closed_flags,
            missing_credential_names=missing_credentials,
            blocker_codes=blocker_codes,
            gate_codes=gate_codes,
            cli_command=CLI_COMMAND,
            http_route=HTTP_ROUTE,
            source_index_command=INDEX_CLI_COMMAND,
            source_index_route=INDEX_HTTP_ROUTE,
            source_index_overall_status=staged.source_index_overall_status,
            source_blockers_plan_command=BLOCKERS_CLI_COMMAND,
            source_blockers_plan_route=BLOCKERS_HTTP_ROUTE,
            source_blockers_plan_overall_status=staged.source_blockers_plan_overall_status,
            source_staged_rollout_command=STAGED_CLI_COMMAND,
            source_staged_rollout_route=STAGED_HTTP_ROUTE,
            source_staged_rollout_overall_status=staged.overall_status,
            source_handoff_command=HANDOFF_CLI_COMMAND,
            source_handoff_route=HANDOFF_HTTP_ROUTE,
            source_handoff_overall_status=handoff.overall_status,
            source_binder_command=BINDER_CLI_COMMAND,
            source_binder_route=BINDER_HTTP_ROUTE,
            source_binder_overall_status=staged.source_binder_overall_status,
            source_runbook_command=RUNBOOK_CLI_COMMAND,
            source_runbook_route=RUNBOOK_HTTP_ROUTE,
            source_runbook_overall_status=staged.source_runbook_overall_status,
            source_manifest_command=MANIFEST_CLI_COMMAND,
            source_manifest_route=MANIFEST_HTTP_ROUTE,
            source_manifest_overall_status=staged.source_manifest_overall_status,
            source_preflight_command=PREFLIGHT_CLI_COMMAND,
            source_preflight_route=PREFLIGHT_HTTP_ROUTE,
            source_preflight_overall_status=preflight.overall_status,
            source_audit_route=AUDIT_HTML_ROUTE,
            source_audit_matching_count=audit.matching_count,
            related_commands=RELATED_COMMANDS,
            related_routes=RELATED_ROUTES,
            local_git=staged.local_git,
            sources=sources,
            settings_preflight=preflight_summary,
            operator_audit=audit_summary,
            next_actions=next_actions,
        )
        logger.info(
            "owner_launch_dossier_built",
            read_only=True,
            no_execution=True,
            no_go_live=True,
            no_deployment=True,
            overall_status=dossier.overall_status,
            operator_halt_status=dossier.operator_halt_status,
            outbound_enabled=dossier.outbound_enabled,
            go_live_permitted=False,
            execution_allowed=False,
            deployment_allowed=False,
            settings_applied=False,
            halt_changed=False,
            owner_approved=False,
            owner_launch_dossier_is_not_go_live=True,
        )
        return dossier


def _sources(
    staged: StagedRolloutPlan,
    handoff: OwnerHandoffPacket,
    preflight: SettingsExecutionPreflight,
    audit: OperatorAuditTimeline,
) -> tuple[DossierSourceSurface, ...]:
    staged_gates = _unique_sorted(code for stage in staged.stages for code in stage.gate_codes)
    return (
        _source(
            key="go-live-readiness-index",
            label="Go-live readiness index",
            purpose="manual_owner_review_index_only",
            status=staged.source_index_overall_status,
            command_name=INDEX_CLI_COMMAND,
            json_route=INDEX_HTTP_ROUTE,
            html_route=INDEX_HTML_ROUTE,
            blocker_codes=(NextActionCode.GO_LIVE_READINESS_INDEX_IS_NOT_PERMISSION.value,),
            gate_codes=("owner_review",),
        ),
        _source(
            key="launch-blockers-plan",
            label="Launch blockers remediation plan",
            purpose="manual_owner_remediation_planning_only",
            status=staged.source_blockers_plan_overall_status,
            command_name=BLOCKERS_CLI_COMMAND,
            json_route=BLOCKERS_HTTP_ROUTE,
            html_route=BLOCKERS_HTML_ROUTE,
            blocker_codes=staged.blocker_codes,
            gate_codes=("launch_blockers",),
        ),
        _source(
            key="staged-rollout-plan",
            label="Staged go-live rollout plan",
            purpose="manual_owner_staged_rollout_planning_only",
            status=staged.overall_status,
            command_name=STAGED_CLI_COMMAND,
            json_route=STAGED_HTTP_ROUTE,
            html_route=STAGED_HTML_ROUTE,
            blocker_codes=(NextActionCode.STAGED_ROLLOUT_PLAN_IS_NOT_GO_LIVE.value,),
            gate_codes=staged_gates,
        ),
        _source(
            key="owner-handoff-packet",
            label="Owner go-live handoff packet",
            purpose="manual_owner_review_only",
            status=handoff.overall_status,
            command_name=HANDOFF_CLI_COMMAND,
            json_route=HANDOFF_HTTP_ROUTE,
            html_route=HANDOFF_HTML_ROUTE,
            blocker_codes=handoff.blocker_codes,
            gate_codes=("owner_review",),
            missing_credential_names=handoff.missing_credential_names,
        ),
        _source(
            key="compliance-evidence-binder",
            label="Compliance evidence binder",
            purpose="manual_owner_review_only",
            status=staged.source_binder_overall_status,
            command_name=BINDER_CLI_COMMAND,
            json_route=BINDER_HTTP_ROUTE,
            html_route=BINDER_HTML_ROUTE,
            blocker_codes=(NextActionCode.BINDER_IS_NOT_GO_LIVE.value,),
            gate_codes=("compliance_evidence",),
        ),
        _source(
            key="release-candidate-runbook",
            label="Release-candidate runbook",
            purpose="future_manual_deployment_planning_only",
            status=staged.source_runbook_overall_status,
            command_name=RUNBOOK_CLI_COMMAND,
            json_route=RUNBOOK_HTTP_ROUTE,
            html_route=RUNBOOK_HTML_ROUTE,
            blocker_codes=(NextActionCode.RUNBOOK_IS_NOT_DEPLOYMENT.value,),
            gate_codes=("runbook_not_deployment",),
        ),
        _source(
            key="release-artifact-manifest",
            label="Release artifact manifest",
            purpose="future_manual_owner_review_only",
            status=staged.source_manifest_overall_status,
            command_name=MANIFEST_CLI_COMMAND,
            json_route=MANIFEST_HTTP_ROUTE,
            html_route=MANIFEST_HTML_ROUTE,
            blocker_codes=(NextActionCode.MANIFEST_IS_NOT_BUILD_OR_DEPLOY.value,),
            gate_codes=("manifest_not_build_or_deploy",),
        ),
        _source(
            key="settings-execution-preflight",
            label="Settings execution preflight",
            purpose="dry_run_settings_blocker_review_only",
            status=preflight.overall_status,
            command_name=PREFLIGHT_CLI_COMMAND,
            json_route=PREFLIGHT_HTTP_ROUTE,
            html_route=PREFLIGHT_HTML_ROUTE,
            blocker_codes=preflight.blocker_codes,
            gate_codes=preflight.missing_gate_codes,
            missing_credential_names=preflight.missing_credential_names,
        ),
        _source(
            key="operator-audit-timeline",
            label="Operator audit timeline",
            purpose="read_only_activity_audit_only",
            status=FindingSeverity.INFO.value,
            command_name=None,
            json_route=None,
            html_route=AUDIT_HTML_ROUTE,
            blocker_codes=(NextActionCode.INSPECT_OPERATOR_AUDIT_TIMELINE.value,),
            gate_codes=("operator_audit",),
        ),
    )


def _source(
    *,
    key: str,
    label: str,
    purpose: str,
    status: str,
    command_name: str | None,
    json_route: str | None,
    html_route: str | None,
    blocker_codes: Sequence[str],
    gate_codes: Sequence[str],
    missing_credential_names: Sequence[str] = (),
) -> DossierSourceSurface:
    return DossierSourceSurface(
        key=_safe_text(key),
        label=_safe_text(label),
        purpose=_safe_text(purpose),
        overall_status=_safe_text(status) or FindingSeverity.INFO.value,
        command_name=_safe_optional(command_name),
        json_route=_safe_optional(json_route),
        html_route=_safe_optional(html_route),
        blocker_codes=_unique_sorted(blocker_codes),
        gate_codes=_unique_sorted(gate_codes),
        missing_credential_names=_unique_sorted(missing_credential_names),
        read_only=True,
        no_execution=True,
        go_live_permitted=False,
        deployment_allowed=False,
    )


def _preflight_summary(
    preflight: SettingsExecutionPreflight,
) -> DossierSettingsPreflightSummary:
    return DossierSettingsPreflightSummary(
        overall_status=_safe_text(preflight.overall_status) or FindingSeverity.INFO.value,
        request_count=preflight.request_count,
        pending_decision_count=preflight.pending_decision_count,
        approved_decision_count=preflight.approved_decision_count,
        blocked_count=preflight.blocked_count,
        executable_count=0,
        blocker_codes=_unique_sorted(preflight.blocker_codes),
        missing_gate_codes=_unique_sorted(preflight.missing_gate_codes),
        missing_credential_names=_unique_sorted(preflight.missing_credential_names),
        closed_provider_flag_names=_unique_sorted(preflight.closed_provider_flag_names),
        no_execution=True,
        dry_run_only=True,
        executed=0,
        settings_applied=False,
        execution_allowed=False,
    )


def _audit_summary(audit: OperatorAuditTimeline) -> DossierAuditSummary:
    return DossierAuditSummary(
        matching_count=audit.matching_count,
        shown_count=audit.shown_count,
        truncated=audit.truncated,
        available_event_types=_unique_sorted(audit.available_event_types),
        available_sources=_unique_sorted(audit.available_sources),
        available_statuses=_unique_sorted(audit.available_statuses),
        read_only=True,
        no_execution=True,
        executed=0,
        halt_changed=False,
        outbound_enabled=audit.outbound_enabled,
        operator_halt_status=_safe_text(audit.operator_halt_status),
    )


def _next_actions(
    staged: StagedRolloutPlan,
    handoff: OwnerHandoffPacket,
    preflight: SettingsExecutionPreflight,
    audit: OperatorAuditTimeline,
) -> tuple[DossierNextAction, ...]:
    halt_ok = staged.operator_halt_status == HaltStatus.HALTED.value
    outbound_ok = not staged.outbound_enabled
    missing = _unique_sorted(
        (
            *staged.missing_credential_names,
            *handoff.missing_credential_names,
            *preflight.missing_credential_names,
        )
    )
    actions = [
        _action(
            DOSSIER_NOT_GO_LIVE_CODE,
            FindingSeverity.INFO.value,
            (
                "This owner launch dossier is a sanitized review export only. "
                "It is not permission to go live and is not an execution surface."
            ),
            command_name=CLI_COMMAND,
            json_route=HTTP_ROUTE,
            html_route=HTML_ROUTE,
        ),
        _action(
            EXECUTION_DISABLED_CODE,
            FindingSeverity.INFO.value,
            (
                "Execution remains disabled. This dossier does not apply "
                "settings, lift halt, enable outbound, deploy, or call providers."
            ),
            command_name=CLI_COMMAND,
            json_route=HTTP_ROUTE,
            html_route=HTML_ROUTE,
        ),
        _action(
            NextActionCode.KEEP_OUTBOUND_DISABLED.value,
            FindingSeverity.INFO.value if outbound_ok else FindingSeverity.BLOCKED.value,
            "Verify OUTBOUND_ENABLED remains false. This dossier does not enable outbound.",
            command_name="launch-readiness",
            json_route="/internal/launch-readiness",
            html_route="/internal/launch-readiness",
            config_name="OUTBOUND_ENABLED",
        ),
        _action(
            (
                NextActionCode.KEEP_OPERATOR_HALT.value
                if halt_ok
                else NextActionCode.RECORD_OPERATOR_HALT.value
            ),
            FindingSeverity.INFO.value if halt_ok else FindingSeverity.WARNING.value,
            (
                "Verify operator halt remains halted. This dossier does not "
                "change operator halt state."
            ),
            command_name="system-status",
            json_route="/internal/monitoring/status",
        ),
        _action(
            NextActionCode.GO_LIVE_READINESS_INDEX_IS_NOT_PERMISSION.value,
            staged.source_index_overall_status,
            (
                "Review the go-live readiness index. Read-only owner-review "
                "export; it is not permission to go live."
            ),
            command_name=INDEX_CLI_COMMAND,
            json_route=INDEX_HTTP_ROUTE,
            html_route=INDEX_HTML_ROUTE,
        ),
        _action(
            NextActionCode.LAUNCH_BLOCKERS_PLAN_IS_NOT_PERMISSION.value,
            staged.source_blockers_plan_overall_status,
            (
                "Review the launch blockers remediation plan. Planning "
                "export only; it is not an execution surface."
            ),
            command_name=BLOCKERS_CLI_COMMAND,
            json_route=BLOCKERS_HTTP_ROUTE,
            html_route=BLOCKERS_HTML_ROUTE,
        ),
        _action(
            NextActionCode.STAGED_ROLLOUT_PLAN_IS_NOT_GO_LIVE.value,
            staged.overall_status,
            (
                "Review the staged go-live rollout plan. Planning export "
                "only; it is not permission to go live."
            ),
            command_name=STAGED_CLI_COMMAND,
            json_route=STAGED_HTTP_ROUTE,
            html_route=STAGED_HTML_ROUTE,
        ),
        _action(
            NextActionCode.HANDOFF_IS_NOT_GO_LIVE.value,
            handoff.overall_status,
            (
                "Review the owner go-live handoff packet. Read-only owner "
                "review; it is not permission or machinery for going live."
            ),
            command_name=HANDOFF_CLI_COMMAND,
            json_route=HANDOFF_HTTP_ROUTE,
            html_route=HANDOFF_HTML_ROUTE,
        ),
        _action(
            NextActionCode.BINDER_IS_NOT_GO_LIVE.value,
            staged.source_binder_overall_status,
            (
                "Review the compliance evidence binder. Sanitized evidence "
                "index only; evidence snippets are not exported."
            ),
            command_name=BINDER_CLI_COMMAND,
            json_route=BINDER_HTTP_ROUTE,
            html_route=BINDER_HTML_ROUTE,
        ),
        _action(
            NextActionCode.INSPECT_SETTINGS_EXECUTION_PREFLIGHT.value,
            preflight.overall_status,
            (
                "Review settings-execution preflight counts and blocker "
                "codes. Dry-run only; this dossier does not apply settings."
            ),
            command_name=PREFLIGHT_CLI_COMMAND,
            json_route=PREFLIGHT_HTTP_ROUTE,
            html_route=PREFLIGHT_HTML_ROUTE,
        ),
        _action(
            NextActionCode.INSPECT_OPERATOR_AUDIT_TIMELINE.value,
            FindingSeverity.INFO.value,
            (
                f"Review the operator audit timeline counts "
                f"(matching={audit.matching_count}, shown={audit.shown_count}). "
                "Read-only; do not execute."
            ),
            html_route=AUDIT_HTML_ROUTE,
        ),
        _action(
            NextActionCode.CONFIGURE_REQUIRED_CREDENTIALS.value,
            "missing" if missing else FindingSeverity.INFO.value,
            (
                "Prepare named required credentials in local env later. "
                "This dossier lists variable names only and never shows values."
            ),
            command_name="launch-readiness",
            json_route="/internal/launch-readiness",
            html_route="/internal/launch-readiness",
        ),
    ]
    return tuple(actions)


def _action(
    code: str,
    status: str,
    label: str,
    *,
    command_name: str | None = None,
    json_route: str | None = None,
    html_route: str | None = None,
    config_name: str | None = None,
) -> DossierNextAction:
    return DossierNextAction(
        code=_safe_text(code),
        status=_safe_text(status) or FindingSeverity.INFO.value,
        label=_safe_text(label),
        command_name=_safe_optional(command_name),
        json_route=_safe_optional(json_route),
        html_route=_safe_optional(html_route),
        config_name=_safe_optional(config_name),
    )


def _worst_status(*values: str) -> str:
    cleaned = [_safe_text(item) for item in values if item]
    if not cleaned:
        return FindingSeverity.INFO.value
    return max(cleaned, key=lambda item: _STATUS_RANK.get(item, 0))


def _unique_sorted(values: Iterable[str]) -> tuple[str, ...]:
    cleaned = [_safe_text(item) for item in values]
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


def dossier_payload(dossier: OwnerLaunchDossier) -> dict[str, Any]:
    return {
        "generated_at": dossier.generated_at.isoformat(),
        "packet_kind": dossier.packet_kind,
        "purpose": dossier.purpose,
        "overall_status": dossier.overall_status,
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
        "outbound_enabled": dossier.outbound_enabled,
        "live_providers_enabled": dossier.live_providers_enabled,
        "manual_review_only": True,
        "owner_launch_dossier_is_not_go_live": True,
        "dossier_is_not_permission_to_go_live": True,
        "dossier_is_not_execution": True,
        "index_is_not_permission_to_go_live": True,
        "handoff_is_not_go_live": True,
        "binder_is_not_go_live": True,
        "runbook_is_not_deployment": True,
        "manifest_is_not_a_build_or_deploy": True,
        "staged_rollout_plan_is_not_go_live": True,
        "operator_halt_status": dossier.operator_halt_status,
        "operator_halt_before": dossier.operator_halt_before,
        "operator_halt_after": dossier.operator_halt_after,
        "closed_provider_flag_names": list(dossier.closed_provider_flag_names),
        "missing_credential_names": list(dossier.missing_credential_names),
        "blocker_codes": list(dossier.blocker_codes),
        "gate_codes": list(dossier.gate_codes),
        "cli_command": CLI_COMMAND,
        "http_route": HTTP_ROUTE,
        "source_index_command": dossier.source_index_command,
        "source_index_route": dossier.source_index_route,
        "source_index_overall_status": dossier.source_index_overall_status,
        "source_blockers_plan_command": dossier.source_blockers_plan_command,
        "source_blockers_plan_route": dossier.source_blockers_plan_route,
        "source_blockers_plan_overall_status": dossier.source_blockers_plan_overall_status,
        "source_staged_rollout_command": dossier.source_staged_rollout_command,
        "source_staged_rollout_route": dossier.source_staged_rollout_route,
        "source_staged_rollout_overall_status": dossier.source_staged_rollout_overall_status,
        "source_handoff_command": dossier.source_handoff_command,
        "source_handoff_route": dossier.source_handoff_route,
        "source_handoff_overall_status": dossier.source_handoff_overall_status,
        "source_binder_command": dossier.source_binder_command,
        "source_binder_route": dossier.source_binder_route,
        "source_binder_overall_status": dossier.source_binder_overall_status,
        "source_runbook_command": dossier.source_runbook_command,
        "source_runbook_route": dossier.source_runbook_route,
        "source_runbook_overall_status": dossier.source_runbook_overall_status,
        "source_manifest_command": dossier.source_manifest_command,
        "source_manifest_route": dossier.source_manifest_route,
        "source_manifest_overall_status": dossier.source_manifest_overall_status,
        "source_preflight_command": dossier.source_preflight_command,
        "source_preflight_route": dossier.source_preflight_route,
        "source_preflight_overall_status": dossier.source_preflight_overall_status,
        "source_audit_route": dossier.source_audit_route,
        "source_audit_matching_count": dossier.source_audit_matching_count,
        "related_commands": list(dossier.related_commands),
        "related_routes": list(dossier.related_routes),
        "local_git": {
            "available": dossier.local_git.available,
            "current_branch": dossier.local_git.current_branch,
            "current_sha": dossier.local_git.current_sha,
            "working_tree_status": dossier.local_git.working_tree_status,
            "git_provider_called": False,
            "github_actions_called": False,
        },
        "sources": [_source_payload(source) for source in dossier.sources],
        "settings_preflight": {
            "overall_status": dossier.settings_preflight.overall_status,
            "request_count": dossier.settings_preflight.request_count,
            "pending_decision_count": dossier.settings_preflight.pending_decision_count,
            "approved_decision_count": dossier.settings_preflight.approved_decision_count,
            "blocked_count": dossier.settings_preflight.blocked_count,
            "executable_count": 0,
            "blocker_codes": list(dossier.settings_preflight.blocker_codes),
            "missing_gate_codes": list(dossier.settings_preflight.missing_gate_codes),
            "missing_credential_names": list(dossier.settings_preflight.missing_credential_names),
            "closed_provider_flag_names": list(
                dossier.settings_preflight.closed_provider_flag_names
            ),
            "no_execution": True,
            "dry_run_only": True,
            "executed": 0,
            "settings_applied": False,
            "execution_allowed": False,
        },
        "operator_audit": {
            "matching_count": dossier.operator_audit.matching_count,
            "shown_count": dossier.operator_audit.shown_count,
            "truncated": dossier.operator_audit.truncated,
            "available_event_types": list(dossier.operator_audit.available_event_types),
            "available_sources": list(dossier.operator_audit.available_sources),
            "available_statuses": list(dossier.operator_audit.available_statuses),
            "read_only": True,
            "no_execution": True,
            "executed": 0,
            "halt_changed": False,
            "outbound_enabled": dossier.operator_audit.outbound_enabled,
            "operator_halt_status": dossier.operator_audit.operator_halt_status,
        },
        "next_actions": [_action_payload(action) for action in dossier.next_actions],
    }


def _source_payload(source: DossierSourceSurface) -> dict[str, Any]:
    return {
        "key": source.key,
        "label": source.label,
        "purpose": source.purpose,
        "overall_status": source.overall_status,
        "command_name": source.command_name,
        "json_route": source.json_route,
        "html_route": source.html_route,
        "blocker_codes": list(source.blocker_codes),
        "gate_codes": list(source.gate_codes),
        "missing_credential_names": list(source.missing_credential_names),
        "read_only": True,
        "no_execution": True,
        "go_live_permitted": False,
        "deployment_allowed": False,
    }


def _action_payload(action: DossierNextAction) -> dict[str, Any]:
    return {
        "code": action.code,
        "status": action.status,
        "label": action.label,
        "command_name": action.command_name,
        "json_route": action.json_route,
        "html_route": action.html_route,
        "config_name": action.config_name,
    }


def format_owner_launch_dossier(
    dossier: OwnerLaunchDossier,
    *,
    as_json: bool = False,
) -> str:
    payload = sanitize_mapping(dossier_payload(dossier))
    if as_json:
        return json.dumps(payload, sort_keys=True)
    return _format_markdown(dossier, payload)


def _format_markdown(dossier: OwnerLaunchDossier, payload: dict[str, Any]) -> str:
    lines = [
        "# Owner launch dossier",
        "",
        "This dossier is a sanitized owner/operator review export of "
        "existing readiness, blocker, staged-rollout, handoff, binder, "
        "runbook, manifest, settings-preflight, and audit surfaces. It is "
        "not permission to go live and is not an execution surface.",
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
            "- owner_launch_dossier_is_not_go_live: "
            f"{_bool_text(payload['owner_launch_dossier_is_not_go_live'])}"
        ),
        (
            "- dossier_is_not_permission_to_go_live: "
            f"{_bool_text(payload['dossier_is_not_permission_to_go_live'])}"
        ),
        f"- dossier_is_not_execution: {_bool_text(payload['dossier_is_not_execution'])}",
        (
            "- index_is_not_permission_to_go_live: "
            f"{_bool_text(payload['index_is_not_permission_to_go_live'])}"
        ),
        f"- handoff_is_not_go_live: {_bool_text(payload['handoff_is_not_go_live'])}",
        f"- binder_is_not_go_live: {_bool_text(payload['binder_is_not_go_live'])}",
        f"- runbook_is_not_deployment: {_bool_text(payload['runbook_is_not_deployment'])}",
        (
            "- manifest_is_not_a_build_or_deploy: "
            f"{_bool_text(payload['manifest_is_not_a_build_or_deploy'])}"
        ),
        (
            "- staged_rollout_plan_is_not_go_live: "
            f"{_bool_text(payload['staged_rollout_plan_is_not_go_live'])}"
        ),
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
        f"- source_index_command: {payload['source_index_command']}",
        f"- source_index_route: {payload['source_index_route']}",
        f"- source_index_overall_status: {payload['source_index_overall_status']}",
        f"- source_blockers_plan_command: {payload['source_blockers_plan_command']}",
        f"- source_blockers_plan_route: {payload['source_blockers_plan_route']}",
        (
            "- source_blockers_plan_overall_status: "
            f"{payload['source_blockers_plan_overall_status']}"
        ),
        f"- source_staged_rollout_command: {payload['source_staged_rollout_command']}",
        f"- source_staged_rollout_route: {payload['source_staged_rollout_route']}",
        (
            "- source_staged_rollout_overall_status: "
            f"{payload['source_staged_rollout_overall_status']}"
        ),
        f"- source_handoff_command: {payload['source_handoff_command']}",
        f"- source_handoff_route: {payload['source_handoff_route']}",
        f"- source_handoff_overall_status: {payload['source_handoff_overall_status']}",
        f"- source_binder_command: {payload['source_binder_command']}",
        f"- source_binder_route: {payload['source_binder_route']}",
        f"- source_binder_overall_status: {payload['source_binder_overall_status']}",
        f"- source_runbook_command: {payload['source_runbook_command']}",
        f"- source_runbook_route: {payload['source_runbook_route']}",
        f"- source_runbook_overall_status: {payload['source_runbook_overall_status']}",
        f"- source_manifest_command: {payload['source_manifest_command']}",
        f"- source_manifest_route: {payload['source_manifest_route']}",
        f"- source_manifest_overall_status: {payload['source_manifest_overall_status']}",
        f"- source_preflight_command: {payload['source_preflight_command']}",
        f"- source_preflight_route: {payload['source_preflight_route']}",
        f"- source_preflight_overall_status: {payload['source_preflight_overall_status']}",
        f"- source_audit_route: {payload['source_audit_route']}",
        f"- source_audit_matching_count: {payload['source_audit_matching_count']}",
        f"- blocker_codes: {_format_codes(dossier.blocker_codes)}",
        f"- gate_codes: {_format_codes(dossier.gate_codes)}",
        f"- missing_credential_names: {_format_codes(dossier.missing_credential_names)}",
        f"- closed_provider_flag_names: {_format_codes(dossier.closed_provider_flag_names)}",
        "",
        "## Live-blocking flags",
        f"- OUTBOUND_ENABLED={_bool_text(dossier.outbound_enabled)}",
        f"- operator_halt_status={dossier.operator_halt_status}",
        f"- live_providers_enabled={_bool_text(dossier.live_providers_enabled)}",
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
        "- owner_launch_dossier_is_not_go_live=true",
        "- dossier_is_not_permission_to_go_live=true",
        "- dossier_is_not_execution=true",
        f"- local_git_available: {_bool_text(dossier.local_git.available)}",
        f"- current_branch: {dossier.local_git.current_branch}",
        f"- current_sha: {dossier.local_git.current_sha}",
        f"- working_tree_status: {dossier.local_git.working_tree_status}",
        f"- git_provider_called: {_bool_text(dossier.local_git.git_provider_called)}",
        f"- github_actions_called: {_bool_text(dossier.local_git.github_actions_called)}",
        "",
        "## Included surfaces",
    ]
    for source in dossier.sources:
        command_name = source.command_name or "-"
        json_route = source.json_route or "-"
        html_route = source.html_route or "-"
        lines.extend(
            [
                f"### {source.label}",
                f"- key: {source.key}",
                f"- purpose: {source.purpose}",
                f"- overall_status: {source.overall_status}",
                f"- command_name: {command_name}",
                f"- json_route: {json_route}",
                f"- html_route: {html_route}",
                f"- blocker_codes: {_format_codes(source.blocker_codes)}",
                f"- gate_codes: {_format_codes(source.gate_codes)}",
                f"- missing_credential_names: {_format_codes(source.missing_credential_names)}",
                "- read_only=true",
                "- no_execution=true",
                "- go_live_permitted=false",
                "- deployment_allowed=false",
            ]
        )
    lines.extend(
        [
            "",
            "## Settings execution preflight summary",
            f"- overall_status: {dossier.settings_preflight.overall_status}",
            f"- request_count: {dossier.settings_preflight.request_count}",
            f"- pending_decision_count: {dossier.settings_preflight.pending_decision_count}",
            f"- approved_decision_count: {dossier.settings_preflight.approved_decision_count}",
            f"- blocked_count: {dossier.settings_preflight.blocked_count}",
            f"- executable_count: {dossier.settings_preflight.executable_count}",
            f"- blocker_codes: {_format_codes(dossier.settings_preflight.blocker_codes)}",
            f"- missing_gate_codes: {_format_codes(dossier.settings_preflight.missing_gate_codes)}",
            (
                "- missing_credential_names: "
                f"{_format_codes(dossier.settings_preflight.missing_credential_names)}"
            ),
            "- no_execution=true",
            "- dry_run_only=true",
            "- executed=0",
            "- settings_applied=false",
            "- execution_allowed=false",
            "",
            "## Operator audit summary",
            f"- matching_count: {dossier.operator_audit.matching_count}",
            f"- shown_count: {dossier.operator_audit.shown_count}",
            f"- truncated: {_bool_text(dossier.operator_audit.truncated)}",
            (
                "- available_event_types: "
                f"{_format_codes(dossier.operator_audit.available_event_types)}"
            ),
            f"- available_sources: {_format_codes(dossier.operator_audit.available_sources)}",
            f"- available_statuses: {_format_codes(dossier.operator_audit.available_statuses)}",
            "- read_only=true",
            "- no_execution=true",
            "- executed=0",
            "- halt_changed=false",
            f"- outbound_enabled: {_bool_text(dossier.operator_audit.outbound_enabled)}",
            f"- operator_halt_status: {dossier.operator_audit.operator_halt_status}",
            "",
            "## Owner next actions",
        ]
    )
    for action in dossier.next_actions:
        command_name = action.command_name or "-"
        json_route = action.json_route or "-"
        html_route = action.html_route or "-"
        config_name = action.config_name or "-"
        lines.append(
            f"- [{action.status}] {action.code} command={command_name} "
            f"json_route={json_route} html_route={html_route} "
            f"config_name={config_name} label={action.label}"
        )
    if not dossier.next_actions:
        lines.append("- next_actions: none")
    return "\n".join(lines)


def _format_codes(values: Sequence[str]) -> str:
    return ",".join(values) if values else "-"
