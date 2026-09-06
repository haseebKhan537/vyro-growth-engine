"""Read-only staged go-live rollout plan export.

Phase 45 consolidates existing go-live readiness, launch-blocker, binder,
runbook, manifest, and launch-readiness surfaces into a sanitized staged
manual rollout plan. It reuses those services as source material and never
recalculates readiness. It never executes, applies settings, lifts halt,
enables outbound, calls providers, builds, publishes, deploys, or changes
live state. This plan is not permission to go live and is not an execution
surface.
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
from vyro_growth.domain import FindingCode, FindingSeverity, NextActionCode
from vyro_growth.observability import sanitize_mapping, sanitize_operator_text
from vyro_growth.services.compliance_evidence_binder import (
    CLI_COMMAND as BINDER_CLI_COMMAND,
)
from vyro_growth.services.compliance_evidence_binder import (
    HTTP_ROUTE as BINDER_HTTP_ROUTE,
)
from vyro_growth.services.compliance_evidence_binder import (
    ComplianceEvidenceBinder,
    ComplianceEvidenceBinderService,
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
from vyro_growth.services.launch_blockers_plan import (
    LaunchBlockersPlan,
    LaunchBlockersPlanService,
)
from vyro_growth.services.launch_readiness import (
    LaunchReadinessChecklist,
    LaunchReadinessService,
)
from vyro_growth.services.operator_halt import HaltStatus, read_operator_halt
from vyro_growth.services.release_artifact_manifest import (
    CLI_COMMAND as MANIFEST_CLI_COMMAND,
)
from vyro_growth.services.release_artifact_manifest import (
    HTTP_ROUTE as MANIFEST_HTTP_ROUTE,
)
from vyro_growth.services.release_artifact_manifest import (
    LocalGitMetadata,
    ReleaseArtifactManifest,
    ReleaseArtifactManifestService,
)
from vyro_growth.services.release_candidate_runbook import (
    CLI_COMMAND as RUNBOOK_CLI_COMMAND,
)
from vyro_growth.services.release_candidate_runbook import (
    HTTP_ROUTE as RUNBOOK_HTTP_ROUTE,
)
from vyro_growth.services.release_candidate_runbook import (
    REQUIRED_CI_JOB_NAMES,
    ReleaseCandidateRunbook,
    ReleaseCandidateRunbookService,
)

logger = structlog.get_logger(__name__)

PACKET_KIND = "staged_go_live_rollout_plan"
PACKET_PURPOSE = "manual_owner_staged_rollout_planning_only"
PLAN_NOT_GO_LIVE_CODE = NextActionCode.STAGED_ROLLOUT_PLAN_IS_NOT_GO_LIVE.value
EXECUTION_DISABLED_CODE = "execution_disabled_in_this_phase"
CLI_COMMAND = "staged-rollout-plan"
HTTP_ROUTE = "/internal/staged-rollout-plan"
HTML_ROUTE = "/internal/operator-staged-rollout-plan"
LAUNCH_READINESS_COMMAND = "launch-readiness"
LAUNCH_READINESS_ROUTE = "/internal/launch-readiness"
OWNER_APPROVAL_TYPES: tuple[str, ...] = (
    "none",
    "owner_review",
    "owner_approval_packet",
    "settings_change_request",
    "live_enablement_review",
)
STAGE_KEYS: tuple[str, ...] = (
    "stage_0",
    "stage_1",
    "stage_2",
    "stage_3",
    "stage_4",
    "stage_5",
)
RELATED_COMMANDS: tuple[str, ...] = (
    INDEX_CLI_COMMAND,
    BLOCKERS_CLI_COMMAND,
    LAUNCH_READINESS_COMMAND,
    "settings-execution-preflight",
    "owner-handoff-packet",
    BINDER_CLI_COMMAND,
    RUNBOOK_CLI_COMMAND,
    MANIFEST_CLI_COMMAND,
    "check-config",
    "smoke-dry-run",
    CLI_COMMAND,
    "owner-launch-dossier",
    "provider-setup-checklist",
    "go-live-rehearsal-checklist",
    "rehearsal-outcome-report",
    "supervised-pilot-plan",
    "system-status",
)
RELATED_ROUTES: tuple[str, ...] = (
    "/internal/operator-go-live-readiness-index",
    INDEX_HTTP_ROUTE,
    "/internal/operator-launch-blockers-plan",
    BLOCKERS_HTTP_ROUTE,
    LAUNCH_READINESS_ROUTE,
    "/internal/operator-settings-execution-preflight",
    "/internal/settings-execution-preflight",
    "/internal/operator-owner-handoff-packet",
    "/internal/owner-handoff-packet",
    "/internal/operator-compliance-evidence-binder",
    BINDER_HTTP_ROUTE,
    "/internal/operator-release-candidate-runbook",
    RUNBOOK_HTTP_ROUTE,
    "/internal/operator-release-artifact-manifest",
    MANIFEST_HTTP_ROUTE,
    "/internal/operator-audit-timeline",
    HTML_ROUTE,
    HTTP_ROUTE,
    "/internal/operator-owner-launch-dossier",
    "/internal/owner-launch-dossier",
    "/internal/operator-provider-setup-checklist",
    "/internal/provider-setup-checklist",
    "/internal/operator-go-live-rehearsal-checklist",
    "/internal/go-live-rehearsal-checklist",
    "/internal/operator-rehearsal-outcome-report",
    "/internal/rehearsal-outcome-report",
    "/internal/operator-supervised-pilot-plan",
    "/internal/supervised-pilot-plan",
    "/internal/operator-supervised-pilot-candidates",
    "/internal/supervised-pilot-candidates",
    "/internal/operator-supervised-pilot-go-no-go",
    "/internal/supervised-pilot-go-no-go",
    "/internal/operator-supervised-pilot-first-send-preflight",
    "/internal/supervised-pilot-first-send-preflight",
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


@dataclass(frozen=True)
class StagedRolloutChecklistItem:
    code: str
    status: str
    label: str
    owner_approval_type: str
    html_route: str | None
    json_route: str | None
    command_name: str | None
    config_name: str | None


@dataclass(frozen=True)
class StagedRolloutStage:
    stage_key: str
    stage_label: str
    status: str
    blocker_codes: tuple[str, ...]
    gate_codes: tuple[str, ...]
    required_owner_approval_type: str
    checklist_items: tuple[StagedRolloutChecklistItem, ...]
    related_commands: tuple[str, ...]
    related_routes: tuple[str, ...]
    related_config_names: tuple[str, ...]
    read_only: bool
    no_execution: bool
    execution_allowed: bool
    go_live_permitted: bool
    deployment_allowed: bool
    settings_applied: bool
    halt_changed: bool
    outbound_enabled: bool
    owner_approved: bool
    staged_rollout_plan_is_not_go_live: bool


@dataclass(frozen=True)
class StagedRolloutPlan:
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
    build_allowed: bool
    artifact_publish_allowed: bool
    container_build_attempted: bool
    artifact_publish_attempted: bool
    outbound_enabled: bool
    live_providers_enabled: bool
    manual_review_only: bool
    staged_rollout_plan_is_not_go_live: bool
    plan_is_not_permission_to_go_live: bool
    plan_is_not_execution: bool
    index_is_not_permission_to_go_live: bool
    handoff_is_not_go_live: bool
    binder_is_not_go_live: bool
    runbook_is_not_deployment: bool
    manifest_is_not_a_build_or_deploy: bool
    operator_halt_status: str
    operator_halt_before: str
    operator_halt_after: str
    closed_provider_flag_names: tuple[str, ...]
    missing_credential_names: tuple[str, ...]
    blocker_codes: tuple[str, ...]
    cli_command: str
    http_route: str
    source_index_command: str
    source_index_route: str
    source_index_overall_status: str
    source_blockers_plan_command: str
    source_blockers_plan_route: str
    source_blockers_plan_overall_status: str
    source_launch_readiness_command: str
    source_launch_readiness_route: str
    source_launch_readiness_overall_status: str
    source_binder_command: str
    source_binder_route: str
    source_binder_overall_status: str
    source_runbook_command: str
    source_runbook_route: str
    source_runbook_overall_status: str
    source_manifest_command: str
    source_manifest_route: str
    source_manifest_overall_status: str
    related_commands: tuple[str, ...]
    related_routes: tuple[str, ...]
    local_git: LocalGitMetadata
    stages: tuple[StagedRolloutStage, ...]


class StagedRolloutPlanService:
    """Compose existing read-only exports into a staged planning packet."""

    def __init__(
        self,
        *,
        blockers_plan: LaunchBlockersPlanService | None = None,
        launch_readiness: LaunchReadinessService | None = None,
        binder: ComplianceEvidenceBinderService | None = None,
        runbook: ReleaseCandidateRunbookService | None = None,
        manifest: ReleaseArtifactManifestService | None = None,
    ) -> None:
        self.blockers_plan = blockers_plan or LaunchBlockersPlanService()
        self.launch_readiness = launch_readiness or LaunchReadinessService()
        self.binder = binder or ComplianceEvidenceBinderService()
        self.runbook = runbook or ReleaseCandidateRunbookService()
        self.manifest = manifest or ReleaseArtifactManifestService()

    def build(self, db: Session, settings: Settings) -> StagedRolloutPlan:
        halt_before = read_operator_halt(db)
        blockers = self.blockers_plan.build(db, settings)
        launch = self.launch_readiness.assess(db, settings)
        binder = self.binder.build(db, settings)
        runbook = self.runbook.build(db, settings)
        manifest = self.manifest.build(db, settings)
        halt_after = read_operator_halt(db)
        if halt_after != halt_before:
            raise RuntimeError("staged rollout plan must not change operator halt status")
        stages = _stages(blockers, launch, binder, runbook, manifest)
        missing_credentials = _unique_sorted(
            (
                *blockers.missing_credential_names,
                *launch_missing_credential_names(launch),
                *binder.missing_credential_names,
                *runbook.missing_credential_names,
                *manifest.missing_credential_names,
            )
        )
        closed_flags = _unique_sorted(
            (
                *blockers.closed_provider_flag_names,
                *binder.closed_provider_flag_names,
                *runbook.closed_provider_flag_names,
                *manifest.closed_provider_flag_names,
            )
        )
        blocker_codes = _unique_sorted(
            (
                *blockers.blocker_codes,
                *binder.blocker_codes,
                *runbook.blocker_codes,
                *manifest.blocker_codes,
                *(code for stage in stages for code in stage.blocker_codes),
            )
        )
        plan = StagedRolloutPlan(
            generated_at=datetime.now(tz=UTC),
            packet_kind=PACKET_KIND,
            purpose=PACKET_PURPOSE,
            overall_status=_worst_status(
                blockers.source_index_overall_status,
                blockers.overall_status,
                launch.overall_status,
                binder.overall_status,
                runbook.overall_status,
                manifest.overall_status,
                *(stage.status for stage in stages),
            ),
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
            build_allowed=False,
            artifact_publish_allowed=False,
            container_build_attempted=False,
            artifact_publish_attempted=False,
            outbound_enabled=settings.outbound_enabled,
            live_providers_enabled=blockers.live_providers_enabled,
            manual_review_only=True,
            staged_rollout_plan_is_not_go_live=True,
            plan_is_not_permission_to_go_live=True,
            plan_is_not_execution=True,
            index_is_not_permission_to_go_live=True,
            handoff_is_not_go_live=True,
            binder_is_not_go_live=True,
            runbook_is_not_deployment=True,
            manifest_is_not_a_build_or_deploy=True,
            operator_halt_status=halt_after.value,
            operator_halt_before=halt_before.value,
            operator_halt_after=halt_after.value,
            closed_provider_flag_names=closed_flags,
            missing_credential_names=missing_credentials,
            blocker_codes=blocker_codes,
            cli_command=CLI_COMMAND,
            http_route=HTTP_ROUTE,
            source_index_command=INDEX_CLI_COMMAND,
            source_index_route=INDEX_HTTP_ROUTE,
            source_index_overall_status=blockers.source_index_overall_status,
            source_blockers_plan_command=BLOCKERS_CLI_COMMAND,
            source_blockers_plan_route=BLOCKERS_HTTP_ROUTE,
            source_blockers_plan_overall_status=blockers.overall_status,
            source_launch_readiness_command=LAUNCH_READINESS_COMMAND,
            source_launch_readiness_route=LAUNCH_READINESS_ROUTE,
            source_launch_readiness_overall_status=launch.overall_status,
            source_binder_command=BINDER_CLI_COMMAND,
            source_binder_route=BINDER_HTTP_ROUTE,
            source_binder_overall_status=binder.overall_status,
            source_runbook_command=RUNBOOK_CLI_COMMAND,
            source_runbook_route=RUNBOOK_HTTP_ROUTE,
            source_runbook_overall_status=runbook.overall_status,
            source_manifest_command=MANIFEST_CLI_COMMAND,
            source_manifest_route=MANIFEST_HTTP_ROUTE,
            source_manifest_overall_status=manifest.overall_status,
            related_commands=RELATED_COMMANDS,
            related_routes=RELATED_ROUTES,
            local_git=manifest.source_provenance.local_git,
            stages=stages,
        )
        logger.info(
            "staged_rollout_plan_built",
            read_only=True,
            no_execution=True,
            overall_status=plan.overall_status,
            operator_halt_status=plan.operator_halt_status,
            outbound_enabled=plan.outbound_enabled,
            go_live_permitted=False,
            execution_allowed=False,
            deployment_allowed=False,
            settings_applied=False,
            halt_changed=False,
            owner_approved=False,
            staged_rollout_plan_is_not_go_live=True,
        )
        return plan


def _stages(
    blockers: LaunchBlockersPlan,
    launch: LaunchReadinessChecklist,
    binder: ComplianceEvidenceBinder,
    runbook: ReleaseCandidateRunbook,
    manifest: ReleaseArtifactManifest,
) -> tuple[StagedRolloutStage, ...]:
    return (
        _stage_0(blockers, launch, runbook),
        _stage_1(blockers, launch, runbook),
        _stage_2(launch, binder, runbook),
        _stage_3(blockers, launch, binder),
        _stage_4(runbook, manifest),
        _stage_5(),
    )


def _stage_0(
    blockers: LaunchBlockersPlan,
    launch: LaunchReadinessChecklist,
    runbook: ReleaseCandidateRunbook,
) -> StagedRolloutStage:
    outbound_ok = not blockers.outbound_enabled and not launch.outbound_enabled
    providers_ok = not blockers.live_providers_enabled and not launch.live_providers_enabled
    halt_ok = blockers.operator_halt_status == HaltStatus.HALTED.value
    status = FindingSeverity.INFO.value
    if not outbound_ok or not providers_ok:
        status = FindingSeverity.BLOCKED.value
    elif not halt_ok:
        status = FindingSeverity.WARNING.value
    codes = _unique_sorted(
        (
            NextActionCode.KEEP_OUTBOUND_DISABLED.value,
            NextActionCode.KEEP_LIVE_PROVIDERS_DISABLED.value,
            (
                NextActionCode.KEEP_OPERATOR_HALT.value
                if halt_ok
                else NextActionCode.RECORD_OPERATOR_HALT.value
            ),
        )
    )
    return _stage(
        key="stage_0",
        label="Safe defaults and operator halt verification",
        status=status,
        blocker_codes=codes,
        gate_codes=("outbound_disabled", "operator_halt", "live_providers_disabled"),
        approval="none",
        items=(
            _item(
                NextActionCode.KEEP_OUTBOUND_DISABLED.value,
                "info" if outbound_ok else FindingSeverity.BLOCKED.value,
                "Verify OUTBOUND_ENABLED remains false. This plan does not enable outbound.",
                config_name="OUTBOUND_ENABLED",
            ),
            _item(
                NextActionCode.KEEP_OPERATOR_HALT.value
                if halt_ok
                else (NextActionCode.RECORD_OPERATOR_HALT.value),
                "info" if halt_ok else FindingSeverity.WARNING.value,
                (
                    "Verify operator halt remains halted. This plan does not "
                    "change operator halt state."
                ),
                command_name="system-status",
                json_route="/internal/monitoring/status",
            ),
            _item(
                NextActionCode.KEEP_LIVE_PROVIDERS_DISABLED.value,
                "info" if providers_ok else FindingSeverity.BLOCKED.value,
                (
                    "Verify live-provider flags remain closed. Review flag "
                    "names only; this plan does not enable providers."
                ),
                command_name=LAUNCH_READINESS_COMMAND,
                json_route=LAUNCH_READINESS_ROUTE,
                html_route=LAUNCH_READINESS_ROUTE,
            ),
            _item(
                "verify_safe_environment_defaults",
                (
                    FindingSeverity.INFO.value
                    if runbook.safe_environment_defaults.env_example_defaults_present
                    else FindingSeverity.WARNING.value
                ),
                (
                    "Review safe environment default names in launch-readiness "
                    "and the release-candidate runbook. Do not paste values."
                ),
                command_name=RUNBOOK_CLI_COMMAND,
                json_route=RUNBOOK_HTTP_ROUTE,
                html_route="/internal/operator-release-candidate-runbook",
            ),
        ),
        commands=(LAUNCH_READINESS_COMMAND, RUNBOOK_CLI_COMMAND, "system-status", "check-config"),
        routes=(
            LAUNCH_READINESS_ROUTE,
            RUNBOOK_HTTP_ROUTE,
            "/internal/operator-release-candidate-runbook",
            "/internal/monitoring/status",
        ),
        config_names=("OUTBOUND_ENABLED",),
    )


def _stage_1(
    blockers: LaunchBlockersPlan,
    launch: LaunchReadinessChecklist,
    runbook: ReleaseCandidateRunbook,
) -> StagedRolloutStage:
    missing = _unique_sorted(
        (
            *blockers.missing_credential_names,
            *launch_missing_credential_names(launch),
            *runbook.missing_credential_names,
        )
    )
    closed_flags = _unique_sorted(
        (*blockers.closed_provider_flag_names, *runbook.closed_provider_flag_names)
    )
    status = FindingSeverity.WARNING.value if missing else FindingSeverity.INFO.value
    items = [
        _item(
            NextActionCode.CONFIGURE_REQUIRED_CREDENTIALS.value,
            "missing" if missing else FindingSeverity.INFO.value,
            (
                "Prepare named required credentials in local env later. "
                "This plan lists variable names only and never shows values."
            ),
            approval="settings_change_request" if missing else "none",
            command_name=LAUNCH_READINESS_COMMAND,
            json_route=LAUNCH_READINESS_ROUTE,
            html_route=LAUNCH_READINESS_ROUTE,
        )
    ]
    for name in missing:
        items.append(
            _item(
                FindingCode.MISSING_REQUIRED_CREDENTIAL.value,
                "missing",
                (
                    f"Prepare credential variable {name} locally later. "
                    "Do not paste values into this plan."
                ),
                approval="settings_change_request",
                command_name=LAUNCH_READINESS_COMMAND,
                json_route=LAUNCH_READINESS_ROUTE,
                html_route=LAUNCH_READINESS_ROUTE,
                config_name=name,
            )
        )
    for name in closed_flags:
        items.append(
            _item(
                NextActionCode.KEEP_LIVE_PROVIDERS_DISABLED.value,
                "closed",
                (
                    f"Live-provider flag {name} remains false. Review the "
                    "name only; this plan does not enable providers."
                ),
                approval="live_enablement_review",
                command_name=LAUNCH_READINESS_COMMAND,
                json_route=LAUNCH_READINESS_ROUTE,
                html_route=LAUNCH_READINESS_ROUTE,
                config_name=name,
            )
        )
    return _stage(
        key="stage_1",
        label="Credential and configuration preparation",
        status=status,
        blocker_codes=_unique_sorted(
            (
                NextActionCode.CONFIGURE_REQUIRED_CREDENTIALS.value,
                FindingCode.MISSING_REQUIRED_CREDENTIAL.value if missing else "",
            )
        ),
        gate_codes=("required_credentials", "closed_provider_flags"),
        approval="settings_change_request" if missing else "none",
        items=tuple(items),
        commands=(LAUNCH_READINESS_COMMAND, "check-config"),
        routes=(LAUNCH_READINESS_ROUTE,),
        config_names=_unique_sorted((*missing, *closed_flags)),
    )


def _stage_2(
    launch: LaunchReadinessChecklist,
    binder: ComplianceEvidenceBinder,
    runbook: ReleaseCandidateRunbook,
) -> StagedRolloutStage:
    smoke = runbook.ci_gates_and_local_verification.smoke_gate
    deploy = runbook.ci_gates_and_local_verification.deploy_config_gate
    launch_smoke = launch.ci_smoke_gate
    smoke_present = smoke.present and launch_smoke.present
    smoke_documented = smoke.documented and launch_smoke.documented
    status = FindingSeverity.INFO.value
    if not smoke_present or not deploy.present:
        status = FindingSeverity.BLOCKED.value
    elif not smoke_documented or not deploy.documented:
        status = FindingSeverity.WARNING.value
    codes = []
    if not smoke_present or not smoke_documented:
        codes.append(NextActionCode.RESTORE_CI_SMOKE_GATE.value)
    if not deploy.present or not deploy.documented:
        codes.append("restore_ci_deploy_config_gate")
    items = [
        _item(
            NextActionCode.RESTORE_CI_SMOKE_GATE.value if not smoke_present else "ci_smoke_gate",
            (
                FindingSeverity.BLOCKED.value
                if not smoke_present
                else (
                    FindingSeverity.WARNING.value
                    if not smoke_documented
                    else FindingSeverity.INFO.value
                )
            ),
            (
                "Review the local smoke-dry-run CI gate name and command. "
                "This plan does not run CI or call GitHub Actions."
            ),
            command_name=smoke.command_name or "smoke-dry-run",
            json_route=LAUNCH_READINESS_ROUTE,
            html_route=LAUNCH_READINESS_ROUTE,
        ),
        _item(
            "restore_ci_deploy_config_gate" if not deploy.present else "deploy_config_gate",
            (
                FindingSeverity.BLOCKED.value
                if not deploy.present
                else (
                    FindingSeverity.WARNING.value
                    if not deploy.documented
                    else FindingSeverity.INFO.value
                )
            ),
            (
                "Review the deploy-config CI gate name and command. This "
                "plan does not deploy or call GitHub Actions."
            ),
            command_name=deploy.command_name or "check-config",
            json_route=LAUNCH_READINESS_ROUTE,
            html_route=LAUNCH_READINESS_ROUTE,
        ),
        _item(
            "local_dry_run_verification",
            FindingSeverity.INFO.value,
            (
                "Review local dry-run verification command names from the "
                "release-candidate runbook. This plan does not execute them."
            ),
            command_name=RUNBOOK_CLI_COMMAND,
            json_route=RUNBOOK_HTTP_ROUTE,
            html_route="/internal/operator-release-candidate-runbook",
        ),
        _item(
            "binder_ci_gate_review",
            binder.overall_status,
            (
                "Review sanitized CI-gate evidence in the compliance "
                "evidence binder. Evidence snippets are not exported."
            ),
            command_name=BINDER_CLI_COMMAND,
            json_route=BINDER_HTTP_ROUTE,
            html_route="/internal/operator-compliance-evidence-binder",
        ),
    ]
    return _stage(
        key="stage_2",
        label="Local dry-run verification and CI gates",
        status=status,
        blocker_codes=_unique_sorted(codes),
        gate_codes=("ci_smoke_gate", "deploy_config_gate", "local_dry_run"),
        approval="none",
        items=tuple(items),
        commands=(
            LAUNCH_READINESS_COMMAND,
            BINDER_CLI_COMMAND,
            RUNBOOK_CLI_COMMAND,
            "smoke-dry-run",
            "check-config",
        ),
        routes=(
            LAUNCH_READINESS_ROUTE,
            BINDER_HTTP_ROUTE,
            "/internal/operator-compliance-evidence-binder",
            RUNBOOK_HTTP_ROUTE,
            "/internal/operator-release-candidate-runbook",
        ),
        config_names=REQUIRED_CI_JOB_NAMES,
    )


def _stage_3(
    blockers: LaunchBlockersPlan,
    launch: LaunchReadinessChecklist,
    binder: ComplianceEvidenceBinder,
) -> StagedRolloutStage:
    pending_packets = launch.pending_owner_approval_packets
    pending_settings = launch.pending_settings_change_request_count
    approval: OwnerApprovalType = "owner_review"
    if pending_packets:
        approval = "owner_approval_packet"
    elif pending_settings:
        approval = "settings_change_request"
    review_codes = _unique_sorted(
        step.blocker_code
        for step in blockers.steps
        if step.owner_approval_type
        in {"owner_review", "owner_approval_packet", "settings_change_request"}
    )
    status = _worst_status(
        blockers.source_index_overall_status,
        blockers.overall_status,
        launch.overall_status,
        binder.overall_status,
    )
    items = (
        _item(
            NextActionCode.GO_LIVE_READINESS_INDEX_IS_NOT_PERMISSION.value,
            blockers.source_index_overall_status,
            (
                "Review the go-live readiness index. Read-only owner-review "
                "export; it is not permission to go live."
            ),
            approval="owner_review",
            command_name=INDEX_CLI_COMMAND,
            json_route=INDEX_HTTP_ROUTE,
            html_route="/internal/operator-go-live-readiness-index",
        ),
        _item(
            NextActionCode.LAUNCH_BLOCKERS_PLAN_IS_NOT_PERMISSION.value,
            blockers.overall_status,
            (
                "Review the launch blockers remediation plan. Planning "
                "export only; it is not an execution surface."
            ),
            approval="owner_review",
            command_name=BLOCKERS_CLI_COMMAND,
            json_route=BLOCKERS_HTTP_ROUTE,
            html_route="/internal/operator-launch-blockers-plan",
        ),
        _item(
            NextActionCode.OWNER_REVIEW_APPROVAL_PACKETS.value,
            "open" if pending_packets else FindingSeverity.INFO.value,
            (
                "Owner-review approval packets and checklists. Recording a "
                "decision does not execute packets."
            ),
            approval="owner_approval_packet",
            command_name="owner-handoff-packet",
            json_route="/internal/owner-handoff-packet",
            html_route="/internal/operator-owner-handoff-packet",
        ),
        _item(
            NextActionCode.REVIEW_SETTINGS_CHANGE_REQUESTS.value,
            "open" if pending_settings else FindingSeverity.INFO.value,
            (
                "Owner-review pending settings-change request records. "
                "This plan does not apply settings."
            ),
            approval="settings_change_request",
            command_name="settings-execution-preflight",
            json_route="/internal/settings-execution-preflight",
            html_route="/internal/operator-settings-execution-preflight",
        ),
        _item(
            NextActionCode.BINDER_IS_NOT_GO_LIVE.value,
            binder.overall_status,
            (
                "Review the compliance evidence binder. Sanitized evidence "
                "index only; it is not permission to go live."
            ),
            approval="owner_review",
            command_name=BINDER_CLI_COMMAND,
            json_route=BINDER_HTTP_ROUTE,
            html_route="/internal/operator-compliance-evidence-binder",
        ),
    )
    return _stage(
        key="stage_3",
        label="Owner review of packets, checklists, and readiness surfaces",
        status=status,
        blocker_codes=_unique_sorted(
            (
                NextActionCode.GO_LIVE_READINESS_INDEX_IS_NOT_PERMISSION.value,
                NextActionCode.LAUNCH_BLOCKERS_PLAN_IS_NOT_PERMISSION.value,
                NextActionCode.OWNER_REVIEW_APPROVAL_PACKETS.value,
                NextActionCode.BINDER_IS_NOT_GO_LIVE.value,
                *review_codes,
            )
        ),
        gate_codes=("owner_review", "approval_packets", "settings_change_requests"),
        approval=approval,
        items=items,
        commands=(
            INDEX_CLI_COMMAND,
            BLOCKERS_CLI_COMMAND,
            "owner-handoff-packet",
            "settings-execution-preflight",
            BINDER_CLI_COMMAND,
        ),
        routes=(
            "/internal/operator-go-live-readiness-index",
            INDEX_HTTP_ROUTE,
            "/internal/operator-launch-blockers-plan",
            BLOCKERS_HTTP_ROUTE,
            "/internal/operator-owner-handoff-packet",
            "/internal/owner-handoff-packet",
            "/internal/operator-settings-execution-preflight",
            "/internal/settings-execution-preflight",
            "/internal/operator-compliance-evidence-binder",
            BINDER_HTTP_ROUTE,
        ),
        config_names=(),
    )


def _stage_4(
    runbook: ReleaseCandidateRunbook,
    manifest: ReleaseArtifactManifest,
) -> StagedRolloutStage:
    items = [
        _item(
            NextActionCode.RUNBOOK_IS_NOT_DEPLOYMENT.value,
            FindingSeverity.INFO.value,
            (
                "Review the release-candidate runbook as future manual "
                "deployment preparation only. The runbook is not a "
                "deployment mechanism."
            ),
            command_name=RUNBOOK_CLI_COMMAND,
            json_route=RUNBOOK_HTTP_ROUTE,
            html_route="/internal/operator-release-candidate-runbook",
        ),
        _item(
            NextActionCode.MANIFEST_IS_NOT_BUILD_OR_DEPLOY.value,
            FindingSeverity.INFO.value,
            (
                "Review the release artifact manifest inventory. This plan "
                "does not build, publish, or deploy artifacts."
            ),
            command_name=MANIFEST_CLI_COMMAND,
            json_route=MANIFEST_HTTP_ROUTE,
            html_route="/internal/operator-release-artifact-manifest",
        ),
    ]
    for step in runbook.manual_deployment_sequence:
        items.append(
            _item(
                step.code,
                FindingSeverity.INFO.value,
                (
                    "Future manual deployment instruction code only. This "
                    "plan does not deploy or execute the instruction."
                ),
                command_name=step.command_name,
                json_route=step.route_name or RUNBOOK_HTTP_ROUTE,
                html_route="/internal/operator-release-candidate-runbook",
            )
        )
    return _stage(
        key="stage_4",
        label="Future manual deployment preparation only",
        status=FindingSeverity.INFO.value,
        blocker_codes=_unique_sorted(
            (
                NextActionCode.RUNBOOK_IS_NOT_DEPLOYMENT.value,
                NextActionCode.MANIFEST_IS_NOT_BUILD_OR_DEPLOY.value,
            )
        ),
        gate_codes=("runbook_not_deployment", "manifest_not_build_or_deploy"),
        approval="none",
        items=tuple(items),
        commands=(RUNBOOK_CLI_COMMAND, MANIFEST_CLI_COMMAND),
        routes=(
            RUNBOOK_HTTP_ROUTE,
            "/internal/operator-release-candidate-runbook",
            MANIFEST_HTTP_ROUTE,
            "/internal/operator-release-artifact-manifest",
        ),
        config_names=(),
    )


def _stage_5() -> StagedRolloutStage:
    return _stage(
        key="stage_5",
        label="Future owner-approved live enablement prerequisites only",
        status=FindingSeverity.INFO.value,
        blocker_codes=_unique_sorted(
            (
                PLAN_NOT_GO_LIVE_CODE,
                EXECUTION_DISABLED_CODE,
                NextActionCode.HANDOFF_IS_NOT_GO_LIVE.value,
                NextActionCode.KEEP_OUTBOUND_DISABLED.value,
            )
        ),
        gate_codes=("live_enablement_not_permitted", "owner_approved_false"),
        approval="live_enablement_review",
        items=(
            _item(
                PLAN_NOT_GO_LIVE_CODE,
                FindingSeverity.INFO.value,
                (
                    "This staged rollout plan is not permission to go live "
                    "and is not an execution surface."
                ),
                approval="none",
                command_name=CLI_COMMAND,
                json_route=HTTP_ROUTE,
                html_route=HTML_ROUTE,
            ),
            _item(
                EXECUTION_DISABLED_CODE,
                FindingSeverity.INFO.value,
                (
                    "Execution remains disabled. This plan does not apply "
                    "settings, lift halt, or enable outbound."
                ),
                approval="none",
                command_name=CLI_COMMAND,
                json_route=HTTP_ROUTE,
                html_route=HTML_ROUTE,
            ),
            _item(
                NextActionCode.HANDOFF_IS_NOT_GO_LIVE.value,
                FindingSeverity.INFO.value,
                (
                    "Owner-approved live enablement is a future prerequisite "
                    "only. This plan does not set owner_approved."
                ),
                approval="live_enablement_review",
                command_name="owner-handoff-packet",
                json_route="/internal/owner-handoff-packet",
                html_route="/internal/operator-owner-handoff-packet",
            ),
            _item(
                NextActionCode.KEEP_OUTBOUND_DISABLED.value,
                FindingSeverity.INFO.value,
                (
                    "OUTBOUND_ENABLED remains false. Future live enablement "
                    "is not performed by this plan."
                ),
                approval="live_enablement_review",
                command_name=LAUNCH_READINESS_COMMAND,
                json_route=LAUNCH_READINESS_ROUTE,
                html_route=LAUNCH_READINESS_ROUTE,
                config_name="OUTBOUND_ENABLED",
            ),
        ),
        commands=(CLI_COMMAND, "owner-handoff-packet", LAUNCH_READINESS_COMMAND),
        routes=(
            HTTP_ROUTE,
            HTML_ROUTE,
            "/internal/owner-handoff-packet",
            "/internal/operator-owner-handoff-packet",
            LAUNCH_READINESS_ROUTE,
        ),
        config_names=("OUTBOUND_ENABLED",),
    )


def _stage(
    *,
    key: str,
    label: str,
    status: str,
    blocker_codes: Sequence[str],
    gate_codes: Sequence[str],
    approval: OwnerApprovalType,
    items: Sequence[StagedRolloutChecklistItem],
    commands: Sequence[str],
    routes: Sequence[str],
    config_names: Sequence[str],
) -> StagedRolloutStage:
    return StagedRolloutStage(
        stage_key=_safe_text(key),
        stage_label=_safe_text(label),
        status=_safe_text(status) or FindingSeverity.INFO.value,
        blocker_codes=_unique_sorted(blocker_codes),
        gate_codes=_unique_sorted(gate_codes),
        required_owner_approval_type=_safe_approval(approval),
        checklist_items=tuple(items),
        related_commands=_unique_sorted(commands),
        related_routes=_unique_sorted(routes),
        related_config_names=_unique_sorted(config_names),
        read_only=True,
        no_execution=True,
        execution_allowed=False,
        go_live_permitted=False,
        deployment_allowed=False,
        settings_applied=False,
        halt_changed=False,
        outbound_enabled=False,
        owner_approved=False,
        staged_rollout_plan_is_not_go_live=True,
    )


def _item(
    code: str,
    status: str,
    label: str,
    *,
    approval: OwnerApprovalType = "none",
    html_route: str | None = None,
    json_route: str | None = None,
    command_name: str | None = None,
    config_name: str | None = None,
) -> StagedRolloutChecklistItem:
    return StagedRolloutChecklistItem(
        code=_safe_text(code),
        status=_safe_text(status) or FindingSeverity.INFO.value,
        label=_safe_text(label),
        owner_approval_type=_safe_approval(approval),
        html_route=_safe_optional(html_route),
        json_route=_safe_optional(json_route),
        command_name=_safe_optional(command_name),
        config_name=_safe_optional(config_name),
    )


def launch_missing_credential_names(launch: LaunchReadinessChecklist) -> tuple[str, ...]:
    return _unique_sorted(
        item.name for item in launch.secret_inventory if item.required and not item.present
    )


def _worst_status(*values: str) -> str:
    cleaned = [_safe_text(item) for item in values if item]
    if not cleaned:
        return FindingSeverity.INFO.value
    return max(cleaned, key=lambda item: _STATUS_RANK.get(item, 0))


def _unique_sorted(values: Iterable[str]) -> tuple[str, ...]:
    cleaned = [_safe_text(item) for item in values]
    return tuple(sorted({item for item in cleaned if item}))


def _safe_approval(value: str) -> str:
    cleaned = _safe_text(value)
    return cleaned if cleaned in OWNER_APPROVAL_TYPES else "none"


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


def plan_payload(plan: StagedRolloutPlan) -> dict[str, Any]:
    return {
        "generated_at": plan.generated_at.isoformat(),
        "packet_kind": plan.packet_kind,
        "purpose": plan.purpose,
        "overall_status": plan.overall_status,
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
        "build_allowed": False,
        "artifact_publish_allowed": False,
        "container_build_attempted": False,
        "artifact_publish_attempted": False,
        "outbound_enabled": plan.outbound_enabled,
        "live_providers_enabled": plan.live_providers_enabled,
        "manual_review_only": True,
        "staged_rollout_plan_is_not_go_live": True,
        "plan_is_not_permission_to_go_live": True,
        "plan_is_not_execution": True,
        "index_is_not_permission_to_go_live": True,
        "handoff_is_not_go_live": True,
        "binder_is_not_go_live": True,
        "runbook_is_not_deployment": True,
        "manifest_is_not_a_build_or_deploy": True,
        "operator_halt_status": plan.operator_halt_status,
        "operator_halt_before": plan.operator_halt_before,
        "operator_halt_after": plan.operator_halt_after,
        "closed_provider_flag_names": list(plan.closed_provider_flag_names),
        "missing_credential_names": list(plan.missing_credential_names),
        "blocker_codes": list(plan.blocker_codes),
        "cli_command": CLI_COMMAND,
        "http_route": HTTP_ROUTE,
        "source_index_command": plan.source_index_command,
        "source_index_route": plan.source_index_route,
        "source_index_overall_status": plan.source_index_overall_status,
        "source_blockers_plan_command": plan.source_blockers_plan_command,
        "source_blockers_plan_route": plan.source_blockers_plan_route,
        "source_blockers_plan_overall_status": plan.source_blockers_plan_overall_status,
        "source_launch_readiness_command": plan.source_launch_readiness_command,
        "source_launch_readiness_route": plan.source_launch_readiness_route,
        "source_launch_readiness_overall_status": plan.source_launch_readiness_overall_status,
        "source_binder_command": plan.source_binder_command,
        "source_binder_route": plan.source_binder_route,
        "source_binder_overall_status": plan.source_binder_overall_status,
        "source_runbook_command": plan.source_runbook_command,
        "source_runbook_route": plan.source_runbook_route,
        "source_runbook_overall_status": plan.source_runbook_overall_status,
        "source_manifest_command": plan.source_manifest_command,
        "source_manifest_route": plan.source_manifest_route,
        "source_manifest_overall_status": plan.source_manifest_overall_status,
        "related_commands": list(plan.related_commands),
        "related_routes": list(plan.related_routes),
        "local_git": {
            "available": plan.local_git.available,
            "current_branch": plan.local_git.current_branch,
            "current_sha": plan.local_git.current_sha,
            "working_tree_status": plan.local_git.working_tree_status,
            "git_provider_called": False,
            "github_actions_called": False,
        },
        "stages": [_stage_payload(stage) for stage in plan.stages],
    }


def _stage_payload(stage: StagedRolloutStage) -> dict[str, Any]:
    return {
        "stage_key": stage.stage_key,
        "stage_label": stage.stage_label,
        "status": stage.status,
        "blocker_codes": list(stage.blocker_codes),
        "gate_codes": list(stage.gate_codes),
        "required_owner_approval_type": stage.required_owner_approval_type,
        "checklist_items": [_item_payload(item) for item in stage.checklist_items],
        "related_commands": list(stage.related_commands),
        "related_routes": list(stage.related_routes),
        "related_config_names": list(stage.related_config_names),
        "read_only": True,
        "no_execution": True,
        "execution_allowed": False,
        "go_live_permitted": False,
        "deployment_allowed": False,
        "settings_applied": False,
        "halt_changed": False,
        "outbound_enabled": False,
        "owner_approved": False,
        "staged_rollout_plan_is_not_go_live": True,
    }


def _item_payload(item: StagedRolloutChecklistItem) -> dict[str, Any]:
    return {
        "code": item.code,
        "status": item.status,
        "label": item.label,
        "owner_approval_type": item.owner_approval_type,
        "html_route": item.html_route,
        "json_route": item.json_route,
        "command_name": item.command_name,
        "config_name": item.config_name,
    }


def format_staged_rollout_plan(
    plan: StagedRolloutPlan,
    *,
    as_json: bool = False,
) -> str:
    payload = sanitize_mapping(plan_payload(plan))
    if as_json:
        return json.dumps(payload, sort_keys=True)
    return _format_markdown(plan, payload)


def _format_markdown(plan: StagedRolloutPlan, payload: dict[str, Any]) -> str:
    lines = [
        "# Staged go-live rollout plan",
        "",
        "This plan is a sanitized owner/operator staged rollout planning "
        "export of existing readiness, blocker, binder, runbook, and "
        "manifest surfaces. It is not permission to go live and is not an "
        "execution surface.",
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
        f"- build_allowed: {_bool_text(payload['build_allowed'])}",
        f"- artifact_publish_allowed: {_bool_text(payload['artifact_publish_allowed'])}",
        f"- manual_review_only: {_bool_text(payload['manual_review_only'])}",
        (
            "- staged_rollout_plan_is_not_go_live: "
            f"{_bool_text(payload['staged_rollout_plan_is_not_go_live'])}"
        ),
        (
            "- plan_is_not_permission_to_go_live: "
            f"{_bool_text(payload['plan_is_not_permission_to_go_live'])}"
        ),
        f"- plan_is_not_execution: {_bool_text(payload['plan_is_not_execution'])}",
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
        f"- source_launch_readiness_command: {payload['source_launch_readiness_command']}",
        f"- source_launch_readiness_route: {payload['source_launch_readiness_route']}",
        (
            "- source_launch_readiness_overall_status: "
            f"{payload['source_launch_readiness_overall_status']}"
        ),
        f"- source_binder_command: {payload['source_binder_command']}",
        f"- source_binder_route: {payload['source_binder_route']}",
        f"- source_binder_overall_status: {payload['source_binder_overall_status']}",
        f"- source_runbook_command: {payload['source_runbook_command']}",
        f"- source_runbook_route: {payload['source_runbook_route']}",
        f"- source_runbook_overall_status: {payload['source_runbook_overall_status']}",
        f"- source_manifest_command: {payload['source_manifest_command']}",
        f"- source_manifest_route: {payload['source_manifest_route']}",
        f"- source_manifest_overall_status: {payload['source_manifest_overall_status']}",
        f"- blocker_codes: {_format_codes(plan.blocker_codes)}",
        f"- missing_credential_names: {_format_codes(plan.missing_credential_names)}",
        f"- closed_provider_flag_names: {_format_codes(plan.closed_provider_flag_names)}",
        "",
        "## Live-blocking flags",
        f"- OUTBOUND_ENABLED={_bool_text(plan.outbound_enabled)}",
        f"- operator_halt_status={plan.operator_halt_status}",
        f"- live_providers_enabled={_bool_text(plan.live_providers_enabled)}",
        "- read_only=true",
        "- no_execution=true",
        "- manual_review_only=true",
        "- execution_allowed=false",
        "- go_live_permitted=false",
        "- deployment_allowed=false",
        "- settings_applied=false",
        "- halt_changed=false",
        "- owner_approved=false",
        "- staged_rollout_plan_is_not_go_live=true",
        "- plan_is_not_permission_to_go_live=true",
        "- plan_is_not_execution=true",
        f"- local_git_available: {_bool_text(plan.local_git.available)}",
        f"- current_branch: {plan.local_git.current_branch}",
        f"- current_sha: {plan.local_git.current_sha}",
        f"- working_tree_status: {plan.local_git.working_tree_status}",
        f"- git_provider_called: {_bool_text(plan.local_git.git_provider_called)}",
        f"- github_actions_called: {_bool_text(plan.local_git.github_actions_called)}",
        "",
        "## Staged rollout groups",
    ]
    for stage in plan.stages:
        lines.extend(
            [
                f"### {stage.stage_label}",
                f"- stage_key: {stage.stage_key}",
                f"- status: {stage.status}",
                f"- blocker_codes: {_format_codes(stage.blocker_codes)}",
                f"- gate_codes: {_format_codes(stage.gate_codes)}",
                f"- required_owner_approval_type: {stage.required_owner_approval_type}",
                f"- related_commands: {_format_codes(stage.related_commands)}",
                f"- related_routes: {_format_codes(stage.related_routes)}",
                f"- related_config_names: {_format_codes(stage.related_config_names)}",
                "- read_only=true",
                "- no_execution=true",
                "- execution_allowed=false",
                "- go_live_permitted=false",
                "- deployment_allowed=false",
                "- settings_applied=false",
                "- halt_changed=false",
                "- outbound_enabled=false",
                "- owner_approved=false",
                "- staged_rollout_plan_is_not_go_live=true",
            ]
        )
        for item in stage.checklist_items:
            html_route = item.html_route or "-"
            json_route = item.json_route or "-"
            command_name = item.command_name or "-"
            config_name = item.config_name or "-"
            lines.append(
                f"- [{item.status}] {item.code} approval={item.owner_approval_type} "
                f"html_route={html_route} json_route={json_route} "
                f"command={command_name} config_name={config_name} "
                f"label={item.label}"
            )
    if not plan.stages:
        lines.append("- stages: none")
    return "\n".join(lines)


def _format_codes(values: Sequence[str]) -> str:
    return ",".join(values) if values else "-"
