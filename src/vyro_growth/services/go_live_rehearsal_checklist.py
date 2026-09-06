"""Read-only manual go-live rehearsal checklist export.

Phase 51 consolidates existing launch-readiness, go-live index, launch-blocker,
staged-rollout, owner-launch-dossier, provider-setup, release-candidate
runbook, release-artifact-manifest, and settings-preflight surfaces into one
sanitized manual rehearsal checklist. It reuses those services as source
material and never recalculates readiness. It never executes, applies
settings, lifts halt, enables outbound, calls providers, builds, publishes,
deploys, or changes live state. This checklist is not a script runner, not
permission to go live, and not an execution surface.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

import structlog
from sqlalchemy.orm import Session

from vyro_growth.config import Settings
from vyro_growth.domain import FindingSeverity, NextActionCode
from vyro_growth.observability import sanitize_mapping, sanitize_operator_text
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
from vyro_growth.services.operator_halt import HaltStatus, read_operator_halt
from vyro_growth.services.owner_launch_dossier import (
    CLI_COMMAND as DOSSIER_CLI_COMMAND,
)
from vyro_growth.services.owner_launch_dossier import (
    HTTP_ROUTE as DOSSIER_HTTP_ROUTE,
)
from vyro_growth.services.owner_launch_dossier import OwnerLaunchDossier, OwnerLaunchDossierService
from vyro_growth.services.provider_setup_checklist import (
    CLI_COMMAND as PROVIDER_CLI_COMMAND,
)
from vyro_growth.services.provider_setup_checklist import (
    HTTP_ROUTE as PROVIDER_HTTP_ROUTE,
)
from vyro_growth.services.provider_setup_checklist import (
    ProviderSetupChecklist,
    ProviderSetupChecklistService,
)
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
from vyro_growth.services.staged_rollout_plan import (
    CLI_COMMAND as STAGED_CLI_COMMAND,
)
from vyro_growth.services.staged_rollout_plan import (
    HTTP_ROUTE as STAGED_HTTP_ROUTE,
)
from vyro_growth.services.staged_rollout_plan import (
    LAUNCH_READINESS_COMMAND,
    LAUNCH_READINESS_ROUTE,
)

logger = structlog.get_logger(__name__)

PACKET_KIND = "go_live_rehearsal_checklist"
PACKET_PURPOSE = "manual_owner_go_live_rehearsal_review_only"
REHEARSAL_NOT_GO_LIVE_CODE = NextActionCode.GO_LIVE_REHEARSAL_CHECKLIST_IS_NOT_GO_LIVE.value
EXECUTION_DISABLED_CODE = "execution_disabled_in_this_phase"
CLI_COMMAND = "go-live-rehearsal-checklist"
HTTP_ROUTE = "/internal/go-live-rehearsal-checklist"
HTML_ROUTE = "/internal/operator-go-live-rehearsal-checklist"
PREFLIGHT_CLI_COMMAND = "settings-execution-preflight"
PREFLIGHT_HTTP_ROUTE = "/internal/settings-execution-preflight"
INDEX_HTML_ROUTE = "/internal/operator-go-live-readiness-index"
BLOCKERS_HTML_ROUTE = "/internal/operator-launch-blockers-plan"
STAGED_HTML_ROUTE = "/internal/operator-staged-rollout-plan"
DOSSIER_HTML_ROUTE = "/internal/operator-owner-launch-dossier"
PROVIDER_HTML_ROUTE = "/internal/operator-provider-setup-checklist"
PREFLIGHT_HTML_ROUTE = "/internal/operator-settings-execution-preflight"
RUNBOOK_HTML_ROUTE = "/internal/operator-release-candidate-runbook"
MANIFEST_HTML_ROUTE = "/internal/operator-release-artifact-manifest"
OWNER_APPROVAL_TYPES: tuple[str, ...] = (
    "none",
    "owner_review",
    "owner_approval_packet",
    "settings_change_request",
    "live_enablement_review",
)
STEP_KINDS: tuple[str, ...] = (
    "configuration",
    "credential",
    "legal_compliance",
    "deployment",
    "provider_setup",
    "manual_review",
)
GATE_KEYS: tuple[str, ...] = (
    "safe_defaults",
    "launch_readiness",
    "go_live_readiness_index",
    "launch_blockers_plan",
    "provider_setup_checklist",
    "settings_execution_preflight",
    "staged_rollout_plan",
    "owner_launch_dossier",
    "release_candidate_runbook",
    "release_artifact_manifest",
    "rollback_abort",
)
SOURCE_KEYS: tuple[str, ...] = (
    "launch-readiness",
    "go-live-readiness-index",
    "launch-blockers-plan",
    "staged-rollout-plan",
    "owner-launch-dossier",
    "provider-setup-checklist",
    "release-candidate-runbook",
    "release-artifact-manifest",
    "settings-execution-preflight",
)
RELATED_COMMANDS: tuple[str, ...] = (
    LAUNCH_READINESS_COMMAND,
    INDEX_CLI_COMMAND,
    BLOCKERS_CLI_COMMAND,
    STAGED_CLI_COMMAND,
    DOSSIER_CLI_COMMAND,
    PROVIDER_CLI_COMMAND,
    PREFLIGHT_CLI_COMMAND,
    RUNBOOK_CLI_COMMAND,
    MANIFEST_CLI_COMMAND,
    "check-config",
    "smoke-dry-run",
    CLI_COMMAND,
    "rehearsal-outcome-report",
    "supervised-pilot-plan",
    "system-status",
)
RELATED_ROUTES: tuple[str, ...] = (
    LAUNCH_READINESS_ROUTE,
    INDEX_HTML_ROUTE,
    INDEX_HTTP_ROUTE,
    BLOCKERS_HTML_ROUTE,
    BLOCKERS_HTTP_ROUTE,
    STAGED_HTML_ROUTE,
    STAGED_HTTP_ROUTE,
    DOSSIER_HTML_ROUTE,
    DOSSIER_HTTP_ROUTE,
    PROVIDER_HTML_ROUTE,
    PROVIDER_HTTP_ROUTE,
    PREFLIGHT_HTML_ROUTE,
    PREFLIGHT_HTTP_ROUTE,
    RUNBOOK_HTML_ROUTE,
    RUNBOOK_HTTP_ROUTE,
    MANIFEST_HTML_ROUTE,
    MANIFEST_HTTP_ROUTE,
    HTML_ROUTE,
    HTTP_ROUTE,
    "/internal/operator-rehearsal-outcome-report",
    "/internal/rehearsal-outcome-report",
    "/internal/operator-supervised-pilot-plan",
    "/internal/supervised-pilot-plan",
    "/internal/operator-supervised-pilot-candidates",
    "/internal/supervised-pilot-candidates",
    "/internal/operator-supervised-pilot-go-no-go",
    "/internal/supervised-pilot-go-no-go",
)
EXPECTED_SAFE_ASSERTION_KEYS: tuple[str, ...] = (
    "executed",
    "OUTBOUND_ENABLED",
    "go_live_permitted",
    "execution_allowed",
    "deployment_allowed",
    "owner_approved",
    "halt_changed",
    "settings_applied",
    "build_allowed",
    "artifact_publish_allowed",
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
OwnerApprovalType = Literal[
    "none",
    "owner_review",
    "owner_approval_packet",
    "settings_change_request",
    "live_enablement_review",
]
StepKind = Literal[
    "configuration",
    "credential",
    "legal_compliance",
    "deployment",
    "provider_setup",
    "manual_review",
]


@dataclass(frozen=True)
class RehearsalAssertion:
    key: str
    expected: str
    observed: str
    passed: bool


@dataclass(frozen=True)
class RehearsalSourceSurface:
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
class RehearsalStep:
    step_key: str
    gate_key: str
    label: str
    instruction: str
    status: str
    step_kind: str
    required_owner_approval_type: str
    command_name: str | None
    json_route: str | None
    html_route: str | None
    config_name: str | None
    expected_assertions: tuple[str, ...]
    blocker_codes: tuple[str, ...]
    gate_codes: tuple[str, ...]
    runnable: bool
    executed: int


@dataclass(frozen=True)
class RehearsalRollbackNote:
    code: str
    label: str
    instruction: str


@dataclass(frozen=True)
class RehearsalNextAction:
    code: str
    status: str
    label: str
    command_name: str | None
    json_route: str | None
    html_route: str | None
    config_name: str | None


@dataclass(frozen=True)
class GoLiveRehearsalChecklist:
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
    go_live_rehearsal_checklist_is_not_go_live: bool
    checklist_is_not_permission_to_go_live: bool
    checklist_is_not_execution: bool
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
    closed_provider_flag_names: tuple[str, ...]
    missing_credential_names: tuple[str, ...]
    blocker_codes: tuple[str, ...]
    gate_codes: tuple[str, ...]
    cli_command: str
    http_route: str
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
    source_runbook_command: str
    source_runbook_route: str
    source_runbook_overall_status: str
    source_manifest_command: str
    source_manifest_route: str
    source_manifest_overall_status: str
    related_commands: tuple[str, ...]
    related_routes: tuple[str, ...]
    local_git: LocalGitMetadata
    expected_safe_assertions: tuple[RehearsalAssertion, ...]
    sources: tuple[RehearsalSourceSurface, ...]
    rehearsal_steps: tuple[RehearsalStep, ...]
    rollback_guidance: tuple[RehearsalRollbackNote, ...]
    next_actions: tuple[RehearsalNextAction, ...]


class GoLiveRehearsalChecklistService:
    """Compose existing read-only exports into a manual rehearsal checklist."""

    def __init__(
        self,
        *,
        provider_setup: ProviderSetupChecklistService | None = None,
        owner_dossier: OwnerLaunchDossierService | None = None,
    ) -> None:
        self.owner_dossier = owner_dossier or OwnerLaunchDossierService()
        self.provider_setup = provider_setup or ProviderSetupChecklistService(
            owner_dossier=self.owner_dossier
        )

    def build(self, db: Session, settings: Settings) -> GoLiveRehearsalChecklist:
        halt_before = read_operator_halt(db)
        dossier = self.owner_dossier.build(db, settings)
        provider = self.provider_setup.build(db, settings)
        halt_after = read_operator_halt(db)
        if halt_after != halt_before:
            raise RuntimeError("go-live rehearsal checklist must not change operator halt status")
        sources = _sources(dossier, provider)
        assertions = _expected_safe_assertions(dossier, provider, halt_before, halt_after)
        steps = _rehearsal_steps(dossier, provider, assertions)
        rollback = _rollback_guidance()
        next_actions = _next_actions(dossier, provider, assertions)
        missing_credentials = _unique_sorted(
            (
                *dossier.missing_credential_names,
                *provider.missing_credential_names,
            )
        )
        closed_flags = _unique_sorted(
            (
                *dossier.closed_provider_flag_names,
                *provider.closed_provider_flag_names,
            )
        )
        blocker_codes = _unique_sorted(
            (
                *dossier.blocker_codes,
                *provider.blocker_codes,
                *(code for source in sources for code in source.blocker_codes),
                *(code for step in steps for code in step.blocker_codes),
                *(action.code for action in next_actions),
            )
        )
        gate_codes = _unique_sorted(
            (
                *dossier.gate_codes,
                *provider.gate_codes,
                *(code for source in sources for code in source.gate_codes),
                *(code for step in steps for code in step.gate_codes),
                "outbound_disabled",
                "operator_halt",
                "live_providers_disabled",
                "no_execution",
                "no_go_live",
                "no_deployment",
                "no_build",
                "no_publish",
                "no_command_execution",
            )
        )
        checklist = GoLiveRehearsalChecklist(
            generated_at=datetime.now(tz=UTC),
            packet_kind=PACKET_KIND,
            purpose=PACKET_PURPOSE,
            overall_status=_worst_status(
                dossier.overall_status,
                provider.overall_status,
                provider.source_launch_readiness_overall_status,
                *(source.overall_status for source in sources),
                *(step.status for step in steps),
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
            live_providers_enabled=dossier.live_providers_enabled,
            manual_review_only=True,
            go_live_rehearsal_checklist_is_not_go_live=True,
            checklist_is_not_permission_to_go_live=True,
            checklist_is_not_execution=True,
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
            closed_provider_flag_names=closed_flags,
            missing_credential_names=missing_credentials,
            blocker_codes=blocker_codes,
            gate_codes=gate_codes,
            cli_command=CLI_COMMAND,
            http_route=HTTP_ROUTE,
            source_launch_readiness_command=LAUNCH_READINESS_COMMAND,
            source_launch_readiness_route=LAUNCH_READINESS_ROUTE,
            source_launch_readiness_overall_status=(
                provider.source_launch_readiness_overall_status
            ),
            source_index_command=INDEX_CLI_COMMAND,
            source_index_route=INDEX_HTTP_ROUTE,
            source_index_overall_status=dossier.source_index_overall_status,
            source_blockers_plan_command=BLOCKERS_CLI_COMMAND,
            source_blockers_plan_route=BLOCKERS_HTTP_ROUTE,
            source_blockers_plan_overall_status=dossier.source_blockers_plan_overall_status,
            source_staged_rollout_command=STAGED_CLI_COMMAND,
            source_staged_rollout_route=STAGED_HTTP_ROUTE,
            source_staged_rollout_overall_status=dossier.source_staged_rollout_overall_status,
            source_dossier_command=DOSSIER_CLI_COMMAND,
            source_dossier_route=DOSSIER_HTTP_ROUTE,
            source_dossier_overall_status=dossier.overall_status,
            source_provider_setup_command=PROVIDER_CLI_COMMAND,
            source_provider_setup_route=PROVIDER_HTTP_ROUTE,
            source_provider_setup_overall_status=provider.overall_status,
            source_preflight_command=PREFLIGHT_CLI_COMMAND,
            source_preflight_route=PREFLIGHT_HTTP_ROUTE,
            source_preflight_overall_status=dossier.source_preflight_overall_status,
            source_runbook_command=RUNBOOK_CLI_COMMAND,
            source_runbook_route=RUNBOOK_HTTP_ROUTE,
            source_runbook_overall_status=dossier.source_runbook_overall_status,
            source_manifest_command=MANIFEST_CLI_COMMAND,
            source_manifest_route=MANIFEST_HTTP_ROUTE,
            source_manifest_overall_status=dossier.source_manifest_overall_status,
            related_commands=RELATED_COMMANDS,
            related_routes=RELATED_ROUTES,
            local_git=dossier.local_git,
            expected_safe_assertions=assertions,
            sources=sources,
            rehearsal_steps=steps,
            rollback_guidance=rollback,
            next_actions=next_actions,
        )
        logger.info(
            "go_live_rehearsal_checklist_built",
            read_only=True,
            no_execution=True,
            no_go_live=True,
            no_deployment=True,
            overall_status=checklist.overall_status,
            operator_halt_status=checklist.operator_halt_status,
            outbound_enabled=checklist.outbound_enabled,
            go_live_permitted=False,
            execution_allowed=False,
            deployment_allowed=False,
            settings_applied=False,
            halt_changed=False,
            owner_approved=False,
            executed=0,
            go_live_rehearsal_checklist_is_not_go_live=True,
            rehearsal_is_not_a_script_runner=True,
        )
        return checklist


def _sources(
    dossier: OwnerLaunchDossier,
    provider: ProviderSetupChecklist,
) -> tuple[RehearsalSourceSurface, ...]:
    return (
        _source(
            key="launch-readiness",
            label="Launch readiness",
            purpose="manual_owner_launch_readiness_review_only",
            status=provider.source_launch_readiness_overall_status,
            command_name=LAUNCH_READINESS_COMMAND,
            json_route=LAUNCH_READINESS_ROUTE,
            html_route=LAUNCH_READINESS_ROUTE,
            blocker_codes=(NextActionCode.KEEP_OUTBOUND_DISABLED.value,),
            gate_codes=("launch_readiness", "outbound_disabled"),
            missing_credential_names=dossier.missing_credential_names,
        ),
        _source(
            key="go-live-readiness-index",
            label="Go-live readiness index",
            purpose="manual_owner_review_index_only",
            status=dossier.source_index_overall_status,
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
            status=dossier.source_blockers_plan_overall_status,
            command_name=BLOCKERS_CLI_COMMAND,
            json_route=BLOCKERS_HTTP_ROUTE,
            html_route=BLOCKERS_HTML_ROUTE,
            blocker_codes=dossier.blocker_codes,
            gate_codes=("launch_blockers",),
        ),
        _source(
            key="staged-rollout-plan",
            label="Staged go-live rollout plan",
            purpose="manual_owner_staged_rollout_planning_only",
            status=dossier.source_staged_rollout_overall_status,
            command_name=STAGED_CLI_COMMAND,
            json_route=STAGED_HTTP_ROUTE,
            html_route=STAGED_HTML_ROUTE,
            blocker_codes=(NextActionCode.STAGED_ROLLOUT_PLAN_IS_NOT_GO_LIVE.value,),
            gate_codes=("staged_rollout",),
        ),
        _source(
            key="owner-launch-dossier",
            label="Owner launch dossier",
            purpose="manual_owner_review_export_only",
            status=dossier.overall_status,
            command_name=DOSSIER_CLI_COMMAND,
            json_route=DOSSIER_HTTP_ROUTE,
            html_route=DOSSIER_HTML_ROUTE,
            blocker_codes=(NextActionCode.OWNER_LAUNCH_DOSSIER_IS_NOT_GO_LIVE.value,),
            gate_codes=("owner_review",),
            missing_credential_names=dossier.missing_credential_names,
        ),
        _source(
            key="provider-setup-checklist",
            label="Provider setup checklist",
            purpose="manual_owner_provider_setup_review_only",
            status=provider.overall_status,
            command_name=PROVIDER_CLI_COMMAND,
            json_route=PROVIDER_HTTP_ROUTE,
            html_route=PROVIDER_HTML_ROUTE,
            blocker_codes=(NextActionCode.PROVIDER_SETUP_CHECKLIST_IS_NOT_GO_LIVE.value,),
            gate_codes=("provider_setup",),
            missing_credential_names=provider.missing_credential_names,
        ),
        _source(
            key="release-candidate-runbook",
            label="Release-candidate runbook",
            purpose="future_manual_deployment_planning_only",
            status=dossier.source_runbook_overall_status,
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
            status=dossier.source_manifest_overall_status,
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
            status=dossier.source_preflight_overall_status,
            command_name=PREFLIGHT_CLI_COMMAND,
            json_route=PREFLIGHT_HTTP_ROUTE,
            html_route=PREFLIGHT_HTML_ROUTE,
            blocker_codes=dossier.settings_preflight.blocker_codes,
            gate_codes=dossier.settings_preflight.missing_gate_codes,
            missing_credential_names=dossier.settings_preflight.missing_credential_names,
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
) -> RehearsalSourceSurface:
    return RehearsalSourceSurface(
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


def _expected_safe_assertions(
    dossier: OwnerLaunchDossier,
    provider: ProviderSetupChecklist,
    halt_before: HaltStatus,
    halt_after: HaltStatus,
) -> tuple[RehearsalAssertion, ...]:
    outbound_expected = "false"
    outbound_observed = _bool_text(dossier.outbound_enabled or provider.outbound_enabled)
    halt_unchanged = halt_before == halt_after and not dossier.halt_changed
    return (
        _assertion("executed", "0", "0", True),
        _assertion(
            "OUTBOUND_ENABLED",
            outbound_expected,
            outbound_observed,
            outbound_observed == outbound_expected,
        ),
        _assertion("go_live_permitted", "false", "false", True),
        _assertion("execution_allowed", "false", "false", True),
        _assertion("deployment_allowed", "false", "false", True),
        _assertion("owner_approved", "false", "false", True),
        _assertion("halt_changed", "false", _bool_text(not halt_unchanged), halt_unchanged),
        _assertion("settings_applied", "false", "false", True),
        _assertion("build_allowed", "false", "false", True),
        _assertion("artifact_publish_allowed", "false", "false", True),
    )


def _assertion(key: str, expected: str, observed: str, passed: bool) -> RehearsalAssertion:
    return RehearsalAssertion(
        key=_safe_text(key),
        expected=_safe_text(expected),
        observed=_safe_text(observed),
        passed=passed,
    )


def _rehearsal_steps(
    dossier: OwnerLaunchDossier,
    provider: ProviderSetupChecklist,
    assertions: Sequence[RehearsalAssertion],
) -> tuple[RehearsalStep, ...]:
    halt_ok = dossier.operator_halt_status == HaltStatus.HALTED.value
    outbound_ok = not dossier.outbound_enabled and not provider.outbound_enabled
    providers_ok = not dossier.live_providers_enabled
    assertion_ok = all(item.passed for item in assertions)
    packet_assertions = tuple(f"{item.key}={item.expected}" for item in assertions)
    return (
        _step(
            step_key="verify_safe_defaults",
            gate_key="safe_defaults",
            label="Verify safe defaults and operator halt",
            instruction=(
                "Manually confirm OUTBOUND_ENABLED remains false, live-provider "
                "flags remain closed, and operator halt is unchanged. Do not "
                "run enablement commands from this checklist."
            ),
            status=(
                FindingSeverity.BLOCKED.value
                if not outbound_ok or not providers_ok
                else FindingSeverity.WARNING.value
                if not halt_ok
                else FindingSeverity.INFO.value
            ),
            step_kind="configuration",
            approval="none",
            command_name="system-status",
            json_route="/internal/monitoring/status",
            config_name="OUTBOUND_ENABLED",
            expected_assertions=(
                "executed=0",
                "OUTBOUND_ENABLED=false",
                "halt_changed=false",
                "owner_approved=false",
            ),
            blocker_codes=(
                NextActionCode.KEEP_OUTBOUND_DISABLED.value,
                NextActionCode.KEEP_LIVE_PROVIDERS_DISABLED.value,
                (
                    NextActionCode.KEEP_OPERATOR_HALT.value
                    if halt_ok
                    else NextActionCode.RECORD_OPERATOR_HALT.value
                ),
            ),
            gate_codes=("outbound_disabled", "operator_halt", "live_providers_disabled"),
        ),
        _step(
            step_key="review_launch_readiness",
            gate_key="launch_readiness",
            label="Review launch readiness export",
            instruction=(
                "Open the launch-readiness export as a reference only. Confirm "
                "safe defaults and named missing credentials. Do not apply "
                "settings or paste secret values."
            ),
            status=provider.source_launch_readiness_overall_status,
            step_kind="manual_review",
            approval="owner_review",
            command_name=LAUNCH_READINESS_COMMAND,
            json_route=LAUNCH_READINESS_ROUTE,
            html_route=LAUNCH_READINESS_ROUTE,
            expected_assertions=("executed=0", "OUTBOUND_ENABLED=false", "owner_approved=false"),
            blocker_codes=(NextActionCode.KEEP_OUTBOUND_DISABLED.value,),
            gate_codes=("launch_readiness",),
        ),
        _step(
            step_key="review_go_live_readiness_index",
            gate_key="go_live_readiness_index",
            label="Review go-live readiness index",
            instruction=(
                "Inspect the go-live readiness index as a read-only rollup. "
                "This rehearsal does not treat the index as permission to go live."
            ),
            status=dossier.source_index_overall_status,
            step_kind="manual_review",
            approval="owner_review",
            command_name=INDEX_CLI_COMMAND,
            json_route=INDEX_HTTP_ROUTE,
            html_route=INDEX_HTML_ROUTE,
            expected_assertions=("go_live_permitted=false", "execution_allowed=false"),
            blocker_codes=(NextActionCode.GO_LIVE_READINESS_INDEX_IS_NOT_PERMISSION.value,),
            gate_codes=("owner_review",),
        ),
        _step(
            step_key="review_launch_blockers_plan",
            gate_key="launch_blockers_plan",
            label="Review launch blockers remediation plan",
            instruction=(
                "Review grouped launch blockers and recommended manual "
                "remediation text. Do not execute remediation from this checklist."
            ),
            status=dossier.source_blockers_plan_overall_status,
            step_kind="manual_review",
            approval="owner_review",
            command_name=BLOCKERS_CLI_COMMAND,
            json_route=BLOCKERS_HTTP_ROUTE,
            html_route=BLOCKERS_HTML_ROUTE,
            expected_assertions=("execution_allowed=false", "settings_applied=false"),
            blocker_codes=(NextActionCode.LAUNCH_BLOCKERS_PLAN_IS_NOT_PERMISSION.value,),
            gate_codes=("launch_blockers",),
        ),
        _step(
            step_key="review_provider_setup_checklist",
            gate_key="provider_setup_checklist",
            label="Review provider setup checklist",
            instruction=(
                "Review provider credential and live-flag names only. Confirm "
                "closed flags and missing credential names. Do not enter "
                "values, enable providers, or call provider APIs."
            ),
            status=provider.overall_status,
            step_kind="provider_setup",
            approval="live_enablement_review",
            command_name=PROVIDER_CLI_COMMAND,
            json_route=PROVIDER_HTTP_ROUTE,
            html_route=PROVIDER_HTML_ROUTE,
            expected_assertions=(
                "executed=0",
                "OUTBOUND_ENABLED=false",
                "go_live_permitted=false",
            ),
            blocker_codes=(NextActionCode.PROVIDER_SETUP_CHECKLIST_IS_NOT_GO_LIVE.value,),
            gate_codes=("provider_setup", "no_provider_calls"),
        ),
        _step(
            step_key="review_settings_execution_preflight",
            gate_key="settings_execution_preflight",
            label="Review settings execution preflight",
            instruction=(
                "Review the dry-run settings preflight counts and blocker "
                "codes. This rehearsal does not apply settings or execute "
                "approved requests."
            ),
            status=dossier.source_preflight_overall_status,
            step_kind="configuration",
            approval="settings_change_request",
            command_name=PREFLIGHT_CLI_COMMAND,
            json_route=PREFLIGHT_HTTP_ROUTE,
            html_route=PREFLIGHT_HTML_ROUTE,
            expected_assertions=(
                "executed=0",
                "execution_allowed=false",
                "settings_applied=false",
            ),
            blocker_codes=(NextActionCode.INSPECT_SETTINGS_EXECUTION_PREFLIGHT.value,),
            gate_codes=("settings_preflight", "no_execution"),
        ),
        _step(
            step_key="review_staged_rollout_plan",
            gate_key="staged_rollout_plan",
            label="Review staged go-live rollout plan",
            instruction=(
                "Review staged rollout groups as planning text only. Do not "
                "advance a live stage or treat the plan as a runner."
            ),
            status=dossier.source_staged_rollout_overall_status,
            step_kind="manual_review",
            approval="owner_review",
            command_name=STAGED_CLI_COMMAND,
            json_route=STAGED_HTTP_ROUTE,
            html_route=STAGED_HTML_ROUTE,
            expected_assertions=("go_live_permitted=false", "deployment_allowed=false"),
            blocker_codes=(NextActionCode.STAGED_ROLLOUT_PLAN_IS_NOT_GO_LIVE.value,),
            gate_codes=("staged_rollout",),
        ),
        _step(
            step_key="review_owner_launch_dossier",
            gate_key="owner_launch_dossier",
            label="Review owner launch dossier",
            instruction=(
                "Review the owner launch dossier packet. Confirm source "
                "statuses and next actions remain non-executable."
            ),
            status=dossier.overall_status,
            step_kind="manual_review",
            approval="owner_review",
            command_name=DOSSIER_CLI_COMMAND,
            json_route=DOSSIER_HTTP_ROUTE,
            html_route=DOSSIER_HTML_ROUTE,
            expected_assertions=("go_live_permitted=false", "owner_approved=false"),
            blocker_codes=(NextActionCode.OWNER_LAUNCH_DOSSIER_IS_NOT_GO_LIVE.value,),
            gate_codes=("owner_review",),
        ),
        _step(
            step_key="review_release_candidate_runbook",
            gate_key="release_candidate_runbook",
            label="Review release-candidate runbook",
            instruction=(
                "Read the runbook as future manual deployment instructions "
                "only. This rehearsal does not deploy, start workers, or "
                "call GitHub Actions."
            ),
            status=dossier.source_runbook_overall_status,
            step_kind="deployment",
            approval="owner_review",
            command_name=RUNBOOK_CLI_COMMAND,
            json_route=RUNBOOK_HTTP_ROUTE,
            html_route=RUNBOOK_HTML_ROUTE,
            expected_assertions=("deployment_allowed=false", "go_live_permitted=false"),
            blocker_codes=(NextActionCode.RUNBOOK_IS_NOT_DEPLOYMENT.value,),
            gate_codes=("runbook_not_deployment", "no_deployment"),
        ),
        _step(
            step_key="review_release_artifact_manifest",
            gate_key="release_artifact_manifest",
            label="Review release artifact manifest",
            instruction=(
                "Review expected artifact, migration, and command names. "
                "This rehearsal does not build containers, publish artifacts, "
                "or deploy."
            ),
            status=dossier.source_manifest_overall_status,
            step_kind="deployment",
            approval="owner_review",
            command_name=MANIFEST_CLI_COMMAND,
            json_route=MANIFEST_HTTP_ROUTE,
            html_route=MANIFEST_HTML_ROUTE,
            expected_assertions=("build_allowed=false", "artifact_publish_allowed=false"),
            blocker_codes=(NextActionCode.MANIFEST_IS_NOT_BUILD_OR_DEPLOY.value,),
            gate_codes=("manifest_not_build_or_deploy", "no_build", "no_publish"),
        ),
        _step(
            step_key="confirm_expected_safe_assertions",
            gate_key="safe_defaults",
            label="Confirm expected safe assertions",
            instruction=(
                "Confirm the rehearsal packet still reports executed=0, "
                "OUTBOUND_ENABLED=false, go_live_permitted=false, "
                "execution_allowed=false, deployment_allowed=false, "
                "owner_approved=false, and halt unchanged. If any assertion "
                "fails, abort the rehearsal."
            ),
            status=FindingSeverity.INFO.value if assertion_ok else FindingSeverity.BLOCKED.value,
            step_kind="legal_compliance",
            approval="none",
            command_name=CLI_COMMAND,
            json_route=HTTP_ROUTE,
            expected_assertions=packet_assertions,
            blocker_codes=(REHEARSAL_NOT_GO_LIVE_CODE, EXECUTION_DISABLED_CODE),
            gate_codes=("expected_safe_assertions", "no_execution"),
        ),
        _step(
            step_key="abort_or_rollback_review",
            gate_key="rollback_abort",
            label="Review abort and rollback guidance",
            instruction=(
                "If any rehearsal gate fails, abort. Keep operator halt, keep "
                "OUTBOUND_ENABLED=false, do not deploy, and return to owner "
                "review of the failing export. This text is guidance only."
            ),
            status=FindingSeverity.INFO.value,
            step_kind="manual_review",
            approval="none",
            command_name=CLI_COMMAND,
            json_route=HTTP_ROUTE,
            expected_assertions=("halt_changed=false", "deployment_allowed=false"),
            blocker_codes=(REHEARSAL_NOT_GO_LIVE_CODE,),
            gate_codes=("rollback_abort",),
        ),
    )


def _step(
    *,
    step_key: str,
    gate_key: str,
    label: str,
    instruction: str,
    status: str,
    step_kind: StepKind,
    approval: OwnerApprovalType,
    command_name: str | None = None,
    json_route: str | None = None,
    html_route: str | None = None,
    config_name: str | None = None,
    expected_assertions: Sequence[str] = (),
    blocker_codes: Sequence[str] = (),
    gate_codes: Sequence[str] = (),
) -> RehearsalStep:
    return RehearsalStep(
        step_key=_safe_text(step_key),
        gate_key=_safe_text(gate_key),
        label=_safe_text(label),
        instruction=_safe_text(instruction),
        status=_safe_text(status) or FindingSeverity.INFO.value,
        step_kind=_safe_step_kind(step_kind),
        required_owner_approval_type=_safe_approval(approval),
        command_name=_safe_optional(command_name),
        json_route=_safe_optional(json_route),
        html_route=_safe_optional(html_route),
        config_name=_safe_optional(config_name),
        expected_assertions=_unique_sorted(expected_assertions),
        blocker_codes=_unique_sorted(blocker_codes),
        gate_codes=_unique_sorted(gate_codes),
        runnable=False,
        executed=0,
    )


def _rollback_guidance() -> tuple[RehearsalRollbackNote, ...]:
    return (
        _rollback(
            "abort_on_failed_assertion",
            "Abort when a safe assertion fails",
            (
                "If executed, OUTBOUND_ENABLED, go_live_permitted, "
                "execution_allowed, deployment_allowed, owner_approved, or "
                "halt_changed is not the expected safe value, stop the "
                "rehearsal. Do not continue to a later gate."
            ),
        ),
        _rollback(
            "keep_operator_halt",
            "Keep operator halt unchanged",
            (
                "Do not lift operator halt during or after rehearsal. If halt "
                "differs from the before value, treat the rehearsal as failed."
            ),
        ),
        _rollback(
            "keep_outbound_disabled",
            "Keep outbound disabled",
            (
                "Leave OUTBOUND_ENABLED=false. This checklist does not enable "
                "outbound or live providers."
            ),
        ),
        _rollback(
            "do_not_deploy_or_publish",
            "Do not deploy, build, or publish",
            (
                "Do not build containers, publish artifacts, deploy, apply "
                "settings, or call GitHub Actions. Return to the failing "
                "read-only export for owner review."
            ),
        ),
        _rollback(
            "no_script_runner",
            "Do not treat command names as runnable automation",
            (
                "Command names and routes are references only. This export is "
                "not a script runner and must not execute those commands."
            ),
        ),
    )


def _rollback(code: str, label: str, instruction: str) -> RehearsalRollbackNote:
    return RehearsalRollbackNote(
        code=_safe_text(code),
        label=_safe_text(label),
        instruction=_safe_text(instruction),
    )


def _next_actions(
    dossier: OwnerLaunchDossier,
    provider: ProviderSetupChecklist,
    assertions: Sequence[RehearsalAssertion],
) -> tuple[RehearsalNextAction, ...]:
    halt_ok = dossier.operator_halt_status == HaltStatus.HALTED.value
    outbound_ok = not dossier.outbound_enabled and not provider.outbound_enabled
    assertion_ok = all(item.passed for item in assertions)
    missing = _unique_sorted(
        (*dossier.missing_credential_names, *provider.missing_credential_names)
    )
    return (
        _action(
            REHEARSAL_NOT_GO_LIVE_CODE,
            FindingSeverity.INFO.value,
            (
                "This go-live rehearsal checklist is a sanitized manual "
                "review export only. It is not a script runner, not "
                "permission to go live, and not an execution surface."
            ),
            command_name=CLI_COMMAND,
            json_route=HTTP_ROUTE,
            html_route=HTML_ROUTE,
        ),
        _action(
            EXECUTION_DISABLED_CODE,
            FindingSeverity.INFO.value,
            (
                "Execution remains disabled. This checklist does not run "
                "commands, apply settings, lift halt, enable outbound, "
                "deploy, build, publish, or call providers."
            ),
            command_name=CLI_COMMAND,
            json_route=HTTP_ROUTE,
            html_route=HTML_ROUTE,
        ),
        _action(
            NextActionCode.KEEP_OUTBOUND_DISABLED.value,
            FindingSeverity.INFO.value if outbound_ok else FindingSeverity.BLOCKED.value,
            "Verify OUTBOUND_ENABLED remains false. This rehearsal does not enable outbound.",
            command_name=LAUNCH_READINESS_COMMAND,
            json_route=LAUNCH_READINESS_ROUTE,
            html_route=LAUNCH_READINESS_ROUTE,
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
                "Verify operator halt remains halted. This rehearsal does "
                "not change operator halt state."
            ),
            command_name="system-status",
            json_route="/internal/monitoring/status",
        ),
        _action(
            NextActionCode.PROVIDER_SETUP_CHECKLIST_IS_NOT_GO_LIVE.value,
            provider.overall_status,
            (
                "Review the provider setup checklist. Credential and flag "
                "names only; it is not permission to go live."
            ),
            command_name=PROVIDER_CLI_COMMAND,
            json_route=PROVIDER_HTTP_ROUTE,
            html_route=PROVIDER_HTML_ROUTE,
        ),
        _action(
            NextActionCode.OWNER_LAUNCH_DOSSIER_IS_NOT_GO_LIVE.value,
            dossier.overall_status,
            (
                "Review the owner launch dossier. Read-only owner-review "
                "export; it is not permission to go live."
            ),
            command_name=DOSSIER_CLI_COMMAND,
            json_route=DOSSIER_HTTP_ROUTE,
            html_route=DOSSIER_HTML_ROUTE,
        ),
        _action(
            NextActionCode.STAGED_ROLLOUT_PLAN_IS_NOT_GO_LIVE.value,
            dossier.source_staged_rollout_overall_status,
            (
                "Review the staged go-live rollout plan. Planning export "
                "only; it is not permission to go live."
            ),
            command_name=STAGED_CLI_COMMAND,
            json_route=STAGED_HTTP_ROUTE,
            html_route=STAGED_HTML_ROUTE,
        ),
        _action(
            NextActionCode.CONFIGURE_REQUIRED_CREDENTIALS.value,
            "missing" if missing else FindingSeverity.INFO.value,
            (
                "Prepare named required credentials in local env later. "
                "This rehearsal lists variable names only and never shows values."
            ),
            command_name=LAUNCH_READINESS_COMMAND,
            json_route=LAUNCH_READINESS_ROUTE,
            html_route=LAUNCH_READINESS_ROUTE,
        ),
        _action(
            REHEARSAL_NOT_GO_LIVE_CODE + "_assertions",
            FindingSeverity.INFO.value if assertion_ok else FindingSeverity.BLOCKED.value,
            (
                "Confirm expected safe assertions remain executed=0, "
                "OUTBOUND_ENABLED=false, go_live_permitted=false, "
                "execution_allowed=false, deployment_allowed=false, "
                "owner_approved=false, and halt unchanged."
            ),
            command_name=CLI_COMMAND,
            json_route=HTTP_ROUTE,
            html_route=HTML_ROUTE,
        ),
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
) -> RehearsalNextAction:
    return RehearsalNextAction(
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


def _safe_approval(value: str) -> str:
    cleaned = _safe_text(value)
    if cleaned in OWNER_APPROVAL_TYPES:
        return cleaned
    return "owner_review"


def _safe_step_kind(value: str) -> str:
    cleaned = _safe_text(value)
    if cleaned in STEP_KINDS:
        return cleaned
    return "manual_review"


def _bool_text(value: object) -> str:
    return "true" if value else "false"


def rehearsal_payload(checklist: GoLiveRehearsalChecklist) -> dict[str, Any]:
    return {
        "generated_at": checklist.generated_at.isoformat(),
        "packet_kind": checklist.packet_kind,
        "purpose": checklist.purpose,
        "overall_status": checklist.overall_status,
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
        "outbound_enabled": checklist.outbound_enabled,
        "live_providers_enabled": checklist.live_providers_enabled,
        "manual_review_only": True,
        "go_live_rehearsal_checklist_is_not_go_live": True,
        "checklist_is_not_permission_to_go_live": True,
        "checklist_is_not_execution": True,
        "rehearsal_is_not_a_script_runner": True,
        "index_is_not_permission_to_go_live": True,
        "dossier_is_not_permission_to_go_live": True,
        "staged_rollout_plan_is_not_go_live": True,
        "provider_setup_checklist_is_not_go_live": True,
        "runbook_is_not_deployment": True,
        "manifest_is_not_a_build_or_deploy": True,
        "operator_halt_status": checklist.operator_halt_status,
        "operator_halt_before": checklist.operator_halt_before,
        "operator_halt_after": checklist.operator_halt_after,
        "closed_provider_flag_names": list(checklist.closed_provider_flag_names),
        "missing_credential_names": list(checklist.missing_credential_names),
        "blocker_codes": list(checklist.blocker_codes),
        "gate_codes": list(checklist.gate_codes),
        "cli_command": CLI_COMMAND,
        "http_route": HTTP_ROUTE,
        "source_launch_readiness_command": checklist.source_launch_readiness_command,
        "source_launch_readiness_route": checklist.source_launch_readiness_route,
        "source_launch_readiness_overall_status": (
            checklist.source_launch_readiness_overall_status
        ),
        "source_index_command": checklist.source_index_command,
        "source_index_route": checklist.source_index_route,
        "source_index_overall_status": checklist.source_index_overall_status,
        "source_blockers_plan_command": checklist.source_blockers_plan_command,
        "source_blockers_plan_route": checklist.source_blockers_plan_route,
        "source_blockers_plan_overall_status": checklist.source_blockers_plan_overall_status,
        "source_staged_rollout_command": checklist.source_staged_rollout_command,
        "source_staged_rollout_route": checklist.source_staged_rollout_route,
        "source_staged_rollout_overall_status": checklist.source_staged_rollout_overall_status,
        "source_dossier_command": checklist.source_dossier_command,
        "source_dossier_route": checklist.source_dossier_route,
        "source_dossier_overall_status": checklist.source_dossier_overall_status,
        "source_provider_setup_command": checklist.source_provider_setup_command,
        "source_provider_setup_route": checklist.source_provider_setup_route,
        "source_provider_setup_overall_status": checklist.source_provider_setup_overall_status,
        "source_preflight_command": checklist.source_preflight_command,
        "source_preflight_route": checklist.source_preflight_route,
        "source_preflight_overall_status": checklist.source_preflight_overall_status,
        "source_runbook_command": checklist.source_runbook_command,
        "source_runbook_route": checklist.source_runbook_route,
        "source_runbook_overall_status": checklist.source_runbook_overall_status,
        "source_manifest_command": checklist.source_manifest_command,
        "source_manifest_route": checklist.source_manifest_route,
        "source_manifest_overall_status": checklist.source_manifest_overall_status,
        "related_commands": list(checklist.related_commands),
        "related_routes": list(checklist.related_routes),
        "local_git": {
            "available": checklist.local_git.available,
            "current_branch": checklist.local_git.current_branch,
            "current_sha": checklist.local_git.current_sha,
            "working_tree_status": checklist.local_git.working_tree_status,
            "git_provider_called": False,
            "github_actions_called": False,
        },
        "expected_safe_assertions": [
            _assertion_payload(item) for item in checklist.expected_safe_assertions
        ],
        "sources": [_source_payload(source) for source in checklist.sources],
        "rehearsal_steps": [_step_payload(step) for step in checklist.rehearsal_steps],
        "rollback_guidance": [_rollback_payload(note) for note in checklist.rollback_guidance],
        "next_actions": [_action_payload(action) for action in checklist.next_actions],
    }


def _assertion_payload(item: RehearsalAssertion) -> dict[str, Any]:
    return {
        "key": item.key,
        "expected": item.expected,
        "observed": item.observed,
        "passed": item.passed,
    }


def _source_payload(source: RehearsalSourceSurface) -> dict[str, Any]:
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


def _step_payload(step: RehearsalStep) -> dict[str, Any]:
    return {
        "step_key": step.step_key,
        "gate_key": step.gate_key,
        "label": step.label,
        "instruction": step.instruction,
        "status": step.status,
        "step_kind": step.step_kind,
        "required_owner_approval_type": step.required_owner_approval_type,
        "command_name": step.command_name,
        "json_route": step.json_route,
        "html_route": step.html_route,
        "config_name": step.config_name,
        "expected_assertions": list(step.expected_assertions),
        "blocker_codes": list(step.blocker_codes),
        "gate_codes": list(step.gate_codes),
        "runnable": False,
        "executed": 0,
    }


def _rollback_payload(note: RehearsalRollbackNote) -> dict[str, Any]:
    return {
        "code": note.code,
        "label": note.label,
        "instruction": note.instruction,
    }


def _action_payload(action: RehearsalNextAction) -> dict[str, Any]:
    return {
        "code": action.code,
        "status": action.status,
        "label": action.label,
        "command_name": action.command_name,
        "json_route": action.json_route,
        "html_route": action.html_route,
        "config_name": action.config_name,
    }


def format_go_live_rehearsal_checklist(
    checklist: GoLiveRehearsalChecklist,
    *,
    as_json: bool = False,
) -> str:
    payload = sanitize_mapping(rehearsal_payload(checklist))
    if as_json:
        return json.dumps(payload, sort_keys=True)
    return _format_markdown(checklist, payload)


def _format_markdown(checklist: GoLiveRehearsalChecklist, payload: dict[str, Any]) -> str:
    lines = [
        "# Go-live rehearsal checklist",
        "",
        "This checklist is a sanitized owner/operator manual rehearsal "
        "export of existing readiness, blocker, staged-rollout, dossier, "
        "provider-setup, runbook, manifest, and settings-preflight "
        "surfaces. Command names and routes are references only. It is "
        "not a script runner, not permission to go live, and not an "
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
            "- go_live_rehearsal_checklist_is_not_go_live: "
            f"{_bool_text(payload['go_live_rehearsal_checklist_is_not_go_live'])}"
        ),
        (
            "- checklist_is_not_permission_to_go_live: "
            f"{_bool_text(payload['checklist_is_not_permission_to_go_live'])}"
        ),
        f"- checklist_is_not_execution: {_bool_text(payload['checklist_is_not_execution'])}",
        (
            "- rehearsal_is_not_a_script_runner: "
            f"{_bool_text(payload['rehearsal_is_not_a_script_runner'])}"
        ),
        (
            "- index_is_not_permission_to_go_live: "
            f"{_bool_text(payload['index_is_not_permission_to_go_live'])}"
        ),
        (
            "- dossier_is_not_permission_to_go_live: "
            f"{_bool_text(payload['dossier_is_not_permission_to_go_live'])}"
        ),
        (
            "- staged_rollout_plan_is_not_go_live: "
            f"{_bool_text(payload['staged_rollout_plan_is_not_go_live'])}"
        ),
        (
            "- provider_setup_checklist_is_not_go_live: "
            f"{_bool_text(payload['provider_setup_checklist_is_not_go_live'])}"
        ),
        f"- runbook_is_not_deployment: {_bool_text(payload['runbook_is_not_deployment'])}",
        (
            "- manifest_is_not_a_build_or_deploy: "
            f"{_bool_text(payload['manifest_is_not_a_build_or_deploy'])}"
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
        f"- source_launch_readiness_command: {payload['source_launch_readiness_command']}",
        f"- source_launch_readiness_route: {payload['source_launch_readiness_route']}",
        (
            "- source_launch_readiness_overall_status: "
            f"{payload['source_launch_readiness_overall_status']}"
        ),
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
        f"- source_dossier_command: {payload['source_dossier_command']}",
        f"- source_dossier_route: {payload['source_dossier_route']}",
        f"- source_dossier_overall_status: {payload['source_dossier_overall_status']}",
        f"- source_provider_setup_command: {payload['source_provider_setup_command']}",
        f"- source_provider_setup_route: {payload['source_provider_setup_route']}",
        (
            "- source_provider_setup_overall_status: "
            f"{payload['source_provider_setup_overall_status']}"
        ),
        f"- source_preflight_command: {payload['source_preflight_command']}",
        f"- source_preflight_route: {payload['source_preflight_route']}",
        f"- source_preflight_overall_status: {payload['source_preflight_overall_status']}",
        f"- source_runbook_command: {payload['source_runbook_command']}",
        f"- source_runbook_route: {payload['source_runbook_route']}",
        f"- source_runbook_overall_status: {payload['source_runbook_overall_status']}",
        f"- source_manifest_command: {payload['source_manifest_command']}",
        f"- source_manifest_route: {payload['source_manifest_route']}",
        f"- source_manifest_overall_status: {payload['source_manifest_overall_status']}",
        f"- blocker_codes: {_format_codes(checklist.blocker_codes)}",
        f"- gate_codes: {_format_codes(checklist.gate_codes)}",
        f"- missing_credential_names: {_format_codes(checklist.missing_credential_names)}",
        f"- closed_provider_flag_names: {_format_codes(checklist.closed_provider_flag_names)}",
        "",
        "## Live-blocking flags",
        f"- OUTBOUND_ENABLED={_bool_text(checklist.outbound_enabled)}",
        f"- operator_halt_status={checklist.operator_halt_status}",
        f"- live_providers_enabled={_bool_text(checklist.live_providers_enabled)}",
        "- read_only=true",
        "- no_execution=true",
        "- no_go_live=true",
        "- no_deployment=true",
        "- manual_review_only=true",
        "- rehearsal_is_not_a_script_runner=true",
        "- execution_allowed=false",
        "- go_live_permitted=false",
        "- deployment_allowed=false",
        "- settings_applied=false",
        "- halt_changed=false",
        "- owner_approved=false",
        "- go_live_rehearsal_checklist_is_not_go_live=true",
        "- checklist_is_not_permission_to_go_live=true",
        "- checklist_is_not_execution=true",
        f"- local_git_available: {_bool_text(checklist.local_git.available)}",
        f"- current_branch: {checklist.local_git.current_branch}",
        f"- current_sha: {checklist.local_git.current_sha}",
        f"- working_tree_status: {checklist.local_git.working_tree_status}",
        f"- git_provider_called: {_bool_text(checklist.local_git.git_provider_called)}",
        f"- github_actions_called: {_bool_text(checklist.local_git.github_actions_called)}",
        "",
        "## Expected safe assertions",
    ]
    for item in checklist.expected_safe_assertions:
        lines.append(
            f"- {item.key} expected={item.expected} observed={item.observed} "
            f"passed={_bool_text(item.passed)}"
        )
    lines.extend(["", "## Included surfaces"])
    for source in checklist.sources:
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
    lines.extend(["", "## Rehearsal steps"])
    for step in checklist.rehearsal_steps:
        command_name = step.command_name or "-"
        json_route = step.json_route or "-"
        html_route = step.html_route or "-"
        config_name = step.config_name or "-"
        lines.extend(
            [
                f"### {step.label}",
                f"- step_key: {step.step_key}",
                f"- gate_key: {step.gate_key}",
                f"- status: {step.status}",
                f"- step_kind: {step.step_kind}",
                f"- required_owner_approval_type: {step.required_owner_approval_type}",
                f"- command_name: {command_name}",
                f"- json_route: {json_route}",
                f"- html_route: {html_route}",
                f"- config_name: {config_name}",
                f"- expected_assertions: {_format_codes(step.expected_assertions)}",
                f"- blocker_codes: {_format_codes(step.blocker_codes)}",
                f"- gate_codes: {_format_codes(step.gate_codes)}",
                "- runnable=false",
                "- executed=0",
                f"- instruction: {step.instruction}",
            ]
        )
    lines.extend(["", "## Rollback and abort guidance"])
    for note in checklist.rollback_guidance:
        lines.append(f"- [{note.code}] {note.label} instruction={note.instruction}")
    lines.extend(["", "## Owner next actions"])
    for action in checklist.next_actions:
        command_name = action.command_name or "-"
        json_route = action.json_route or "-"
        html_route = action.html_route or "-"
        config_name = action.config_name or "-"
        lines.append(
            f"- [{action.status}] {action.code} command={command_name} "
            f"json_route={json_route} html_route={html_route} "
            f"config_name={config_name} label={action.label}"
        )
    if not checklist.next_actions:
        lines.append("- next_actions: none")
    return "\n".join(lines)


def _format_codes(values: Sequence[str]) -> str:
    return ",".join(values) if values else "-"
