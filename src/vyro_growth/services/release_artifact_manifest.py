"""Read-only release artifact manifest and provenance export.

Phase 39 describes what would be included in a future release candidate:
expected branch/SHA inputs, artifact paths, migrations, runtime commands,
container/deployment config files, and safety gates. It never builds
containers, publishes artifacts, deploys, applies settings, lifts halt,
enables outbound, calls providers, spends, executes approved items,
executes owner approval packets, executes settings requests, creates
campaigns, books meetings, places calls, or contacts anyone.
"""

from __future__ import annotations

import json
import re
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
from vyro_growth.services.launch_readiness import default_repo_root
from vyro_growth.services.operator_halt import HaltStatus, read_operator_halt
from vyro_growth.services.release_candidate_runbook import (
    ReleaseCandidateRunbook,
    ReleaseCandidateRunbookService,
    RunbookCiGate,
)

logger = structlog.get_logger(__name__)

PACKET_KIND = "release_artifact_manifest"
PACKET_PURPOSE = "future_manual_owner_review_only"
CLI_COMMAND = "release-artifact-manifest"
HTTP_ROUTE = "/internal/release-artifact-manifest"
MANIFEST_NOT_BUILD_OR_DEPLOY_CODE = NextActionCode.MANIFEST_IS_NOT_BUILD_OR_DEPLOY.value
EXECUTION_DISABLED_CODE = "execution_disabled_in_this_phase"
SECTION_MANIFEST = "release_artifact_manifest"
SECTION_PROVENANCE = "source_provenance"
SECTION_ARTIFACTS = "artifact_inventory"
SECTION_MIGRATIONS = "migration_inventory"
SECTION_GATES = "safety_gate_inventory"
EXPECTED_REPO_NAME = "vyro-growth-engine"
EXPECTED_BASE_BRANCH = "main"
EXPECTED_WORKFLOW_PATH = ".github/workflows/ci.yml"
EXPECTED_RELEASE_CHANNEL = "owner_reviewed_manual_deploy"
MIGRATIONS_RELATIVE = Path("alembic") / "versions"
GIT_UNAVAILABLE = "unavailable"
GIT_NOT_INSPECTED = "not_inspected"
SHA_RE = re.compile(r"^[0-9a-f]{7,40}$")
BRANCH_RE = re.compile(r"^[A-Za-z0-9._/\-]{1,200}$")
REVISION_RE = re.compile(
    r'^revision(?::\s*str)?\s*=\s*["\']([^"\']+)["\']',
    re.MULTILINE,
)
PACKED_REF_RE = re.compile(r"^([0-9a-f]{7,40})\s+(refs/\S+)$")
REQUIRED_CI_JOB_NAMES: tuple[str, ...] = ("test", "smoke-dry-run", "deploy-config")
RELATED_COMMANDS: tuple[str, ...] = (
    "check-config",
    "smoke-dry-run",
    "check-smoke-output",
    "launch-readiness",
    "settings-execution-preflight",
    "owner-handoff-packet",
    "compliance-evidence-binder",
    "release-candidate-runbook",
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
    "/internal/release-candidate-runbook",
    "/internal/operator-dashboard",
    "/internal/operator-audit-timeline",
    "/internal/operator-compliance-evidence-binder",
    "/internal/operator-release-candidate-runbook",
    HTTP_ROUTE,
)
EXPECTED_ARTIFACTS: tuple[tuple[str, str, bool], ...] = (
    ("package_directory", "src/vyro_growth", True),
    ("dockerfile", "Dockerfile", False),
    ("docker_compose", "docker-compose.yml", False),
    ("alembic_ini", "alembic.ini", False),
    ("migrations_directory", "alembic/versions", True),
    ("docs_directory", "docs", True),
    ("tests_directory", "tests", True),
    ("ci_workflow", EXPECTED_WORKFLOW_PATH, False),
)
RUNTIME_COMMANDS: tuple[tuple[str, str], ...] = (
    ("api", "uvicorn vyro_growth.main:app --host 0.0.0.0 --port 8000"),
    ("worker_check", "vyro-growth worker --check"),
    ("worker_list", "vyro-growth worker --list"),
    ("smoke_dry_run", "vyro-growth smoke-dry-run --local-only --json"),
    ("check_smoke_output", "vyro-growth check-smoke-output --file"),
    ("check_config", "vyro-growth check-config"),
    ("compose_config", "docker compose config --quiet"),
    ("migrate", "alembic upgrade head"),
    ("manifest_export", f"vyro-growth {CLI_COMMAND}"),
)
_SEVERITY_RANK = {
    FindingSeverity.INFO.value: 0,
    FindingSeverity.WARNING.value: 1,
    FindingSeverity.BLOCKED.value: 2,
}


@dataclass(frozen=True)
class ManifestChecklistItem:
    code: str
    severity: str
    source_section: str
    status: str


@dataclass(frozen=True)
class LocalGitMetadata:
    available: bool
    current_branch: str
    current_sha: str
    working_tree_status: str
    git_provider_called: bool
    github_actions_called: bool


@dataclass(frozen=True)
class SourceProvenance:
    expected_repo_name: str
    expected_base_branch: str
    expected_workflow_path: str
    expected_release_channel: str
    sha_source: str
    local_git: LocalGitMetadata
    git_provider_called: bool
    github_actions_called: bool


@dataclass(frozen=True)
class ArtifactInventoryItem:
    kind: str
    path: str
    present: bool
    is_directory: bool


@dataclass(frozen=True)
class MigrationInventoryItem:
    filename: str
    revision_id: str


@dataclass(frozen=True)
class RuntimeCommandItem:
    kind: str
    command_name: str


@dataclass(frozen=True)
class SafetyGateInventory:
    required_ci_job_names: tuple[str, ...]
    smoke_gate: RunbookCiGate
    deploy_config_gate: RunbookCiGate
    outbound_enabled_required: bool
    outbound_enabled: bool
    live_providers_enabled: bool
    required_flag_names: tuple[str, ...]
    closed_provider_flag_names: tuple[str, ...]
    missing_credential_names: tuple[str, ...]
    env_example_defaults_present: bool
    dockerfile_defaults_present: bool
    compose_defaults_present: bool
    github_actions_called: bool


@dataclass(frozen=True)
class NoBuildNoDeployEvidence:
    build_allowed: bool
    artifact_publish_allowed: bool
    container_build_attempted: bool
    artifact_publish_attempted: bool
    deployment_allowed: bool
    deployment_attempted: bool
    deployed: bool
    runbook_is_not_deployment: bool
    manifest_is_not_a_build_or_deploy: bool
    github_actions_called: bool
    git_provider_called: bool


@dataclass(frozen=True)
class ManifestReusedSummaries:
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
    runbook_is_not_deployment: bool
    runbook_command: str
    runbook_route: str
    audit_timeline_matching_count: int
    audit_timeline_route: str


@dataclass(frozen=True)
class ReleaseArtifactManifest:
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
    manual_review_only: bool
    runbook_is_not_deployment: bool
    manifest_is_not_a_build_or_deploy: bool
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
    source_provenance: SourceProvenance
    artifact_inventory: tuple[ArtifactInventoryItem, ...]
    migration_inventory: tuple[MigrationInventoryItem, ...]
    runtime_command_inventory: tuple[RuntimeCommandItem, ...]
    safety_gate_inventory: SafetyGateInventory
    no_build_no_deploy: NoBuildNoDeployEvidence
    reused_summaries: ManifestReusedSummaries
    remaining_manual_owner_checklist: tuple[ManifestChecklistItem, ...]


class ReleaseArtifactManifestService:
    """Compose existing read-only evidence into a future-release manifest."""

    def __init__(
        self,
        *,
        runbook: ReleaseCandidateRunbookService | None = None,
    ) -> None:
        self.runbook = runbook or ReleaseCandidateRunbookService()

    def build(
        self,
        db: Session,
        settings: Settings,
        *,
        repo_root: Path | None = None,
    ) -> ReleaseArtifactManifest:
        root = repo_root or default_repo_root()
        halt_before = read_operator_halt(db)
        runbook = self.runbook.build(db, settings, repo_root=root)
        provenance = _source_provenance(root)
        artifacts = _artifact_inventory(root)
        migrations = _migration_inventory(root)
        commands = _runtime_commands()
        gates = _safety_gates(settings, runbook)
        reused = _reused_summaries(runbook)
        halt_after = read_operator_halt(db)
        if halt_after is not halt_before:
            raise RuntimeError("release artifact manifest must not change operator halt status")
        items = _remaining_checklist(
            runbook=runbook,
            artifacts=artifacts,
            gates=gates,
            outbound_enabled=settings.outbound_enabled,
            live_providers_enabled=any_live_provider_enabled(settings),
            halt=halt_after,
        )
        manifest = ReleaseArtifactManifest(
            generated_at=datetime.now(tz=UTC),
            packet_kind=PACKET_KIND,
            purpose=PACKET_PURPOSE,
            overall_status=runbook.overall_status,
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
            manual_review_only=True,
            runbook_is_not_deployment=True,
            manifest_is_not_a_build_or_deploy=True,
            operator_halt_status=halt_after.value,
            operator_halt_before=halt_before.value,
            operator_halt_after=halt_after.value,
            outbound_enabled=settings.outbound_enabled,
            live_providers_enabled=any_live_provider_enabled(settings),
            cli_command=CLI_COMMAND,
            http_route=HTTP_ROUTE,
            related_commands=RELATED_COMMANDS,
            related_routes=RELATED_ROUTES,
            blocker_codes=_unique_sorted(runbook.blocker_codes),
            missing_credential_names=tuple(runbook.missing_credential_names),
            closed_provider_flag_names=tuple(runbook.closed_provider_flag_names),
            source_provenance=provenance,
            artifact_inventory=artifacts,
            migration_inventory=migrations,
            runtime_command_inventory=commands,
            safety_gate_inventory=gates,
            no_build_no_deploy=_no_build_no_deploy(),
            reused_summaries=reused,
            remaining_manual_owner_checklist=items,
        )
        logger.info(
            "release_artifact_manifest_built",
            packet_kind=PACKET_KIND,
            purpose=PACKET_PURPOSE,
            overall_status=manifest.overall_status,
            read_only=True,
            no_execution=True,
            executed=0,
            settings_applied=False,
            owner_approved=False,
            live_action=False,
            execution_allowed=False,
            go_live_permitted=False,
            deployment_allowed=False,
            build_allowed=False,
            artifact_publish_allowed=False,
            runbook_is_not_deployment=True,
            manifest_is_not_a_build_or_deploy=True,
            future_execution_phase_exists=False,
            future_deployment_phase_exists=False,
            git_provider_called=False,
            github_actions_called=False,
        )
        return manifest


def format_release_artifact_manifest(
    manifest: ReleaseArtifactManifest,
    *,
    as_json: bool = False,
) -> str:
    payload = sanitize_mapping(manifest_payload(manifest))
    if as_json:
        return json.dumps(payload, sort_keys=True)
    return _format_markdown(manifest, payload)


def manifest_payload(manifest: ReleaseArtifactManifest) -> dict[str, Any]:
    return {
        "generated_at": manifest.generated_at.isoformat(),
        "packet_kind": PACKET_KIND,
        "purpose": PACKET_PURPOSE,
        "overall_status": manifest.overall_status,
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
        "manual_review_only": True,
        "runbook_is_not_deployment": True,
        "manifest_is_not_a_build_or_deploy": True,
        "operator_halt_status": manifest.operator_halt_status,
        "operator_halt_before": manifest.operator_halt_before,
        "operator_halt_after": manifest.operator_halt_after,
        "outbound_enabled": manifest.outbound_enabled,
        "live_providers_enabled": manifest.live_providers_enabled,
        "cli_command": CLI_COMMAND,
        "http_route": HTTP_ROUTE,
        "related_commands": list(RELATED_COMMANDS),
        "related_routes": list(RELATED_ROUTES),
        "blocker_codes": list(manifest.blocker_codes),
        "missing_credential_names": list(manifest.missing_credential_names),
        "closed_provider_flag_names": list(manifest.closed_provider_flag_names),
        "source_provenance": _provenance_payload(manifest.source_provenance),
        "artifact_inventory": [_artifact_payload(item) for item in manifest.artifact_inventory],
        "migration_inventory": [
            {"filename": item.filename, "revision_id": item.revision_id}
            for item in manifest.migration_inventory
        ],
        "runtime_command_inventory": [
            {"kind": item.kind, "command_name": item.command_name}
            for item in manifest.runtime_command_inventory
        ],
        "safety_gate_inventory": _gates_payload(manifest.safety_gate_inventory),
        "no_build_no_deploy": _no_build_payload(manifest.no_build_no_deploy),
        "reused_summaries": _reused_payload(manifest.reused_summaries),
        "remaining_manual_owner_checklist": [
            {
                "code": item.code,
                "severity": item.severity,
                "source_section": item.source_section,
                "status": item.status,
            }
            for item in manifest.remaining_manual_owner_checklist
        ],
    }


def inspect_local_git(repo_root: Path) -> LocalGitMetadata:
    """Read local .git metadata only. Does not call GitHub or git remotes."""

    unavailable = LocalGitMetadata(
        available=False,
        current_branch=GIT_UNAVAILABLE,
        current_sha=GIT_UNAVAILABLE,
        working_tree_status=GIT_UNAVAILABLE,
        git_provider_called=False,
        github_actions_called=False,
    )
    git_dir = _resolve_git_dir(repo_root)
    if git_dir is None:
        return unavailable
    head_text = _read_text(git_dir / "HEAD").strip()
    if not head_text:
        return unavailable
    if head_text.startswith("ref:"):
        ref_name = head_text.removeprefix("ref:").strip()
        branch = _safe_branch(ref_name.removeprefix("refs/heads/"))
        sha = _safe_sha(_read_ref_sha(git_dir, ref_name))
        if branch == GIT_UNAVAILABLE or sha == GIT_UNAVAILABLE:
            return unavailable
        return LocalGitMetadata(
            available=True,
            current_branch=branch,
            current_sha=sha,
            working_tree_status=GIT_NOT_INSPECTED,
            git_provider_called=False,
            github_actions_called=False,
        )
    sha = _safe_sha(head_text)
    if sha == GIT_UNAVAILABLE:
        return unavailable
    return LocalGitMetadata(
        available=True,
        current_branch="detached",
        current_sha=sha,
        working_tree_status=GIT_NOT_INSPECTED,
        git_provider_called=False,
        github_actions_called=False,
    )


def _source_provenance(repo_root: Path) -> SourceProvenance:
    local_git = inspect_local_git(repo_root)
    return SourceProvenance(
        expected_repo_name=EXPECTED_REPO_NAME,
        expected_base_branch=EXPECTED_BASE_BRANCH,
        expected_workflow_path=EXPECTED_WORKFLOW_PATH,
        expected_release_channel=EXPECTED_RELEASE_CHANNEL,
        sha_source="local_git_head",
        local_git=local_git,
        git_provider_called=False,
        github_actions_called=False,
    )


def _artifact_inventory(repo_root: Path) -> tuple[ArtifactInventoryItem, ...]:
    items: list[ArtifactInventoryItem] = []
    for kind, relative, is_directory in EXPECTED_ARTIFACTS:
        path = repo_root / relative
        present = path.is_dir() if is_directory else path.is_file()
        items.append(
            ArtifactInventoryItem(
                kind=kind,
                path=relative,
                present=present,
                is_directory=is_directory,
            )
        )
    return tuple(items)


def _migration_inventory(repo_root: Path) -> tuple[MigrationInventoryItem, ...]:
    directory = repo_root / MIGRATIONS_RELATIVE
    if not directory.is_dir():
        return ()
    items: list[MigrationInventoryItem] = []
    for path in sorted(directory.glob("*.py")):
        if path.name.startswith("__"):
            continue
        revision = _revision_id(path)
        items.append(MigrationInventoryItem(filename=path.name, revision_id=revision))
    return tuple(items)


def _runtime_commands() -> tuple[RuntimeCommandItem, ...]:
    return tuple(
        RuntimeCommandItem(kind=kind, command_name=command)
        for kind, command in RUNTIME_COMMANDS
    )


def _safety_gates(settings: Settings, runbook: ReleaseCandidateRunbook) -> SafetyGateInventory:
    ci = runbook.ci_gates_and_local_verification
    defaults = runbook.safe_environment_defaults
    return SafetyGateInventory(
        required_ci_job_names=REQUIRED_CI_JOB_NAMES,
        smoke_gate=RunbookCiGate(
            present=ci.smoke_gate.present,
            documented=ci.smoke_gate.documented,
            job_name=ci.smoke_gate.job_name,
            command_name=ci.smoke_gate.command_name,
        ),
        deploy_config_gate=RunbookCiGate(
            present=ci.deploy_config_gate.present,
            documented=ci.deploy_config_gate.documented,
            job_name=ci.deploy_config_gate.job_name,
            command_name=ci.deploy_config_gate.command_name,
        ),
        outbound_enabled_required=False,
        outbound_enabled=settings.outbound_enabled,
        live_providers_enabled=defaults.live_providers_enabled,
        required_flag_names=defaults.required_flag_names,
        closed_provider_flag_names=defaults.closed_provider_flag_names,
        missing_credential_names=defaults.missing_credential_names,
        env_example_defaults_present=defaults.env_example_defaults_present,
        dockerfile_defaults_present=defaults.dockerfile_defaults_present,
        compose_defaults_present=defaults.compose_defaults_present,
        github_actions_called=False,
    )


def _no_build_no_deploy() -> NoBuildNoDeployEvidence:
    return NoBuildNoDeployEvidence(
        build_allowed=False,
        artifact_publish_allowed=False,
        container_build_attempted=False,
        artifact_publish_attempted=False,
        deployment_allowed=False,
        deployment_attempted=False,
        deployed=False,
        runbook_is_not_deployment=True,
        manifest_is_not_a_build_or_deploy=True,
        github_actions_called=False,
        git_provider_called=False,
    )


def _reused_summaries(runbook: ReleaseCandidateRunbook) -> ManifestReusedSummaries:
    summaries = runbook.reused_summaries
    return ManifestReusedSummaries(
        launch_readiness_overall_status=summaries.launch_readiness_overall_status,
        launch_readiness_blocker_codes=summaries.launch_readiness_blocker_codes,
        settings_preflight_overall_status=summaries.settings_preflight_overall_status,
        settings_preflight_blocked_count=summaries.settings_preflight_blocked_count,
        settings_preflight_execution_allowed=False,
        owner_handoff_go_live_permitted=False,
        owner_handoff_execution_allowed=False,
        binder_is_not_go_live=True,
        binder_command=summaries.binder_command,
        binder_route=summaries.binder_route,
        runbook_is_not_deployment=True,
        runbook_command=runbook.cli_command,
        runbook_route=runbook.http_route,
        audit_timeline_matching_count=summaries.audit_timeline_matching_count,
        audit_timeline_route=summaries.audit_timeline_route,
    )


def _remaining_checklist(
    *,
    runbook: ReleaseCandidateRunbook,
    artifacts: Sequence[ArtifactInventoryItem],
    gates: SafetyGateInventory,
    outbound_enabled: bool,
    live_providers_enabled: bool,
    halt: HaltStatus,
) -> tuple[ManifestChecklistItem, ...]:
    selected: dict[str, ManifestChecklistItem] = {}

    def add(code: str, severity: str, source_section: str, status: str = "open") -> None:
        current = selected.get(code)
        if current is not None and _SEVERITY_RANK.get(current.severity, 0) >= _SEVERITY_RANK.get(
            severity, 0
        ):
            return
        selected[code] = ManifestChecklistItem(
            code=code,
            severity=severity,
            source_section=source_section,
            status=status,
        )

    add(MANIFEST_NOT_BUILD_OR_DEPLOY_CODE, FindingSeverity.INFO.value, SECTION_MANIFEST)
    add(EXECUTION_DISABLED_CODE, FindingSeverity.INFO.value, SECTION_MANIFEST)
    add(
        NextActionCode.RUNBOOK_IS_NOT_DEPLOYMENT.value,
        FindingSeverity.INFO.value,
        SECTION_MANIFEST,
    )
    add(NextActionCode.BINDER_IS_NOT_GO_LIVE.value, FindingSeverity.INFO.value, SECTION_MANIFEST)
    add(NextActionCode.HANDOFF_IS_NOT_GO_LIVE.value, FindingSeverity.INFO.value, SECTION_MANIFEST)
    for item in runbook.remaining_manual_owner_checklist:
        add(item.code, item.severity, item.source_section, item.status)
    missing_artifacts = tuple(item.path for item in artifacts if not item.present)
    if missing_artifacts:
        add("restore_expected_release_artifacts", FindingSeverity.BLOCKED.value, SECTION_ARTIFACTS)
    if not gates.smoke_gate.documented:
        add(
            NextActionCode.RESTORE_CI_SMOKE_GATE.value,
            FindingSeverity.BLOCKED.value,
            SECTION_GATES,
        )
    if not gates.deploy_config_gate.documented:
        add("restore_ci_deploy_config_gate", FindingSeverity.BLOCKED.value, SECTION_GATES)
    if outbound_enabled:
        add(NextActionCode.DISABLE_OUTBOUND.value, FindingSeverity.BLOCKED.value, SECTION_GATES)
    else:
        add(NextActionCode.KEEP_OUTBOUND_DISABLED.value, FindingSeverity.INFO.value, SECTION_GATES)
    if live_providers_enabled:
        add(
            NextActionCode.DISABLE_LIVE_PROVIDERS.value,
            FindingSeverity.BLOCKED.value,
            SECTION_GATES,
        )
    else:
        add(
            NextActionCode.KEEP_LIVE_PROVIDERS_DISABLED.value,
            FindingSeverity.INFO.value,
            SECTION_GATES,
        )
    match halt:
        case HaltStatus.HALTED:
            add(
                NextActionCode.KEEP_OPERATOR_HALT.value,
                FindingSeverity.WARNING.value,
                SECTION_GATES,
            )
        case HaltStatus.UNAVAILABLE:
            add(
                NextActionCode.RECORD_OPERATOR_HALT.value,
                FindingSeverity.BLOCKED.value,
                SECTION_GATES,
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


def _provenance_payload(provenance: SourceProvenance) -> dict[str, Any]:
    return {
        "expected_repo_name": provenance.expected_repo_name,
        "expected_base_branch": provenance.expected_base_branch,
        "expected_workflow_path": provenance.expected_workflow_path,
        "expected_release_channel": provenance.expected_release_channel,
        "sha_source": provenance.sha_source,
        "local_git": {
            "available": provenance.local_git.available,
            "current_branch": provenance.local_git.current_branch,
            "current_sha": provenance.local_git.current_sha,
            "working_tree_status": provenance.local_git.working_tree_status,
            "git_provider_called": False,
            "github_actions_called": False,
        },
        "git_provider_called": False,
        "github_actions_called": False,
    }


def _artifact_payload(item: ArtifactInventoryItem) -> dict[str, Any]:
    return {
        "kind": item.kind,
        "path": item.path,
        "present": item.present,
        "is_directory": item.is_directory,
    }


def _gate_payload(gate: RunbookCiGate) -> dict[str, Any]:
    return {
        "present": gate.present,
        "documented": gate.documented,
        "job_name": gate.job_name,
        "command_name": gate.command_name,
    }


def _gates_payload(gates: SafetyGateInventory) -> dict[str, Any]:
    return {
        "required_ci_job_names": list(gates.required_ci_job_names),
        "smoke_gate": _gate_payload(gates.smoke_gate),
        "deploy_config_gate": _gate_payload(gates.deploy_config_gate),
        "outbound_enabled_required": False,
        "outbound_enabled": gates.outbound_enabled,
        "live_providers_enabled": gates.live_providers_enabled,
        "required_flag_names": list(gates.required_flag_names),
        "closed_provider_flag_names": list(gates.closed_provider_flag_names),
        "missing_credential_names": list(gates.missing_credential_names),
        "env_example_defaults_present": gates.env_example_defaults_present,
        "dockerfile_defaults_present": gates.dockerfile_defaults_present,
        "compose_defaults_present": gates.compose_defaults_present,
        "github_actions_called": False,
    }


def _no_build_payload(evidence: NoBuildNoDeployEvidence) -> dict[str, Any]:
    return {
        "build_allowed": False,
        "artifact_publish_allowed": False,
        "container_build_attempted": False,
        "artifact_publish_attempted": False,
        "deployment_allowed": False,
        "deployment_attempted": False,
        "deployed": False,
        "runbook_is_not_deployment": True,
        "manifest_is_not_a_build_or_deploy": True,
        "github_actions_called": False,
        "git_provider_called": False,
    }


def _reused_payload(summary: ManifestReusedSummaries) -> dict[str, Any]:
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
        "runbook_is_not_deployment": True,
        "runbook_command": summary.runbook_command,
        "runbook_route": summary.runbook_route,
        "audit_timeline_matching_count": summary.audit_timeline_matching_count,
        "audit_timeline_route": summary.audit_timeline_route,
    }


def _format_markdown(manifest: ReleaseArtifactManifest, payload: dict[str, Any]) -> str:
    lines = [
        "# Release artifact manifest",
        "",
        "This manifest is for owner/operator review of a future release candidate. "
        "It is not a build, artifact publishing, deployment mechanism, or permission "
        "to go live.",
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
        (
            "- manifest_is_not_a_build_or_deploy: "
            f"{_bool_text(payload['manifest_is_not_a_build_or_deploy'])}"
        ),
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
        f"- blocker_codes: {_format_codes(manifest.blocker_codes)}",
        f"- missing_credential_names: {_format_codes(manifest.missing_credential_names)}",
        f"- closed_provider_flag_names: {_format_codes(manifest.closed_provider_flag_names)}",
        "",
        "## Source and provenance expectations",
        f"- expected_repo_name: {manifest.source_provenance.expected_repo_name}",
        f"- expected_base_branch: {manifest.source_provenance.expected_base_branch}",
        f"- expected_workflow_path: {manifest.source_provenance.expected_workflow_path}",
        f"- expected_release_channel: {manifest.source_provenance.expected_release_channel}",
        f"- sha_source: {manifest.source_provenance.sha_source}",
        f"- local_git_available: {_bool_text(manifest.source_provenance.local_git.available)}",
        f"- current_branch: {manifest.source_provenance.local_git.current_branch}",
        f"- current_sha: {manifest.source_provenance.local_git.current_sha}",
        (
            "- working_tree_status: "
            f"{manifest.source_provenance.local_git.working_tree_status}"
        ),
        (
            "- git_provider_called: "
            f"{_bool_text(manifest.source_provenance.git_provider_called)}"
        ),
        (
            "- github_actions_called: "
            f"{_bool_text(manifest.source_provenance.github_actions_called)}"
        ),
        "",
        "## Artifact inventory",
    ]
    for artifact in manifest.artifact_inventory:
        lines.append(
            f"- artifact: kind={artifact.kind} path={artifact.path} "
            f"present={_bool_text(artifact.present)} "
            f"directory={_bool_text(artifact.is_directory)}"
        )
    lines.extend(["", "## Migration inventory"])
    if manifest.migration_inventory:
        for migration in manifest.migration_inventory:
            lines.append(
                f"- migration: filename={migration.filename} revision_id={migration.revision_id}"
            )
    else:
        lines.append("- migration: none")
    lines.extend(["", "## Runtime command inventory"])
    for command in manifest.runtime_command_inventory:
        lines.append(f"- command: kind={command.kind} command={command.command_name}")
    gates = manifest.safety_gate_inventory
    lines.extend(
        [
            "",
            "## Safety gate inventory",
            f"- required_ci_job_names: {_format_codes(gates.required_ci_job_names)}",
            (
                "- smoke_gate: "
                f"present={_bool_text(gates.smoke_gate.present)} "
                f"documented={_bool_text(gates.smoke_gate.documented)} "
                f"job={gates.smoke_gate.job_name} "
                f"command={gates.smoke_gate.command_name}"
            ),
            (
                "- deploy_config_gate: "
                f"present={_bool_text(gates.deploy_config_gate.present)} "
                f"documented={_bool_text(gates.deploy_config_gate.documented)} "
                f"job={gates.deploy_config_gate.job_name} "
                f"command={gates.deploy_config_gate.command_name}"
            ),
            f"- outbound_enabled_required: {_bool_text(gates.outbound_enabled_required)}",
            f"- outbound_enabled: {_bool_text(gates.outbound_enabled)}",
            f"- live_providers_enabled: {_bool_text(gates.live_providers_enabled)}",
            f"- required_flag_names: {_format_codes(gates.required_flag_names)}",
            f"- missing_credential_names: {_format_codes(gates.missing_credential_names)}",
            f"- closed_provider_flag_names: {_format_codes(gates.closed_provider_flag_names)}",
            (
                "- env_example_defaults_present: "
                f"{_bool_text(gates.env_example_defaults_present)}"
            ),
            (
                "- dockerfile_defaults_present: "
                f"{_bool_text(gates.dockerfile_defaults_present)}"
            ),
            f"- compose_defaults_present: {_bool_text(gates.compose_defaults_present)}",
            f"- github_actions_called: {_bool_text(gates.github_actions_called)}",
            "",
            "## No-build and no-deploy evidence",
            f"- build_allowed: {_bool_text(manifest.no_build_no_deploy.build_allowed)}",
            (
                "- artifact_publish_allowed: "
                f"{_bool_text(manifest.no_build_no_deploy.artifact_publish_allowed)}"
            ),
            (
                "- container_build_attempted: "
                f"{_bool_text(manifest.no_build_no_deploy.container_build_attempted)}"
            ),
            (
                "- artifact_publish_attempted: "
                f"{_bool_text(manifest.no_build_no_deploy.artifact_publish_attempted)}"
            ),
            f"- deployment_allowed: {_bool_text(manifest.no_build_no_deploy.deployment_allowed)}",
            (
                "- runbook_is_not_deployment: "
                f"{_bool_text(manifest.no_build_no_deploy.runbook_is_not_deployment)}"
            ),
            (
                "- manifest_is_not_a_build_or_deploy: "
                f"{_bool_text(manifest.no_build_no_deploy.manifest_is_not_a_build_or_deploy)}"
            ),
            "",
            "## Reused read-only summaries",
            (
                "- launch_readiness: "
                f"overall={manifest.reused_summaries.launch_readiness_overall_status} "
                "blockers="
                f"{_format_codes(manifest.reused_summaries.launch_readiness_blocker_codes)}"
            ),
            (
                "- settings_execution_preflight: "
                f"overall={manifest.reused_summaries.settings_preflight_overall_status} "
                f"blocked={manifest.reused_summaries.settings_preflight_blocked_count} "
                "execution_allowed="
                f"{_bool_text(manifest.reused_summaries.settings_preflight_execution_allowed)}"
            ),
            (
                "- owner_handoff: "
                "go_live_permitted="
                f"{_bool_text(manifest.reused_summaries.owner_handoff_go_live_permitted)} "
                "execution_allowed="
                f"{_bool_text(manifest.reused_summaries.owner_handoff_execution_allowed)}"
            ),
            (
                "- compliance_evidence_binder: "
                "binder_is_not_go_live="
                f"{_bool_text(manifest.reused_summaries.binder_is_not_go_live)} "
                f"command={manifest.reused_summaries.binder_command} "
                f"route={manifest.reused_summaries.binder_route}"
            ),
            (
                "- release_candidate_runbook: "
                "runbook_is_not_deployment="
                f"{_bool_text(manifest.reused_summaries.runbook_is_not_deployment)} "
                f"command={manifest.reused_summaries.runbook_command} "
                f"route={manifest.reused_summaries.runbook_route}"
            ),
            (
                "- operator_audit_timeline: "
                f"matching={manifest.reused_summaries.audit_timeline_matching_count} "
                f"route={manifest.reused_summaries.audit_timeline_route}"
            ),
            "",
            "## Remaining unresolved blockers and manual owner checklist",
        ]
    )
    for checklist_item in manifest.remaining_manual_owner_checklist:
        lines.append(
            f"- [{checklist_item.status}] {checklist_item.code} "
            f"severity={checklist_item.severity} source={checklist_item.source_section}"
        )
    return "\n".join(lines)


def _resolve_git_dir(repo_root: Path) -> Path | None:
    git_path = repo_root / ".git"
    if git_path.is_dir():
        return git_path
    return None


def _read_ref_sha(git_dir: Path, ref_name: str) -> str:
    if not ref_name.startswith("refs/") or ".." in ref_name or ref_name.startswith("/"):
        return GIT_UNAVAILABLE
    direct = git_dir / ref_name
    if direct.is_file():
        return _read_text(direct).strip()
    packed = _read_text(git_dir / "packed-refs")
    for line in packed.splitlines():
        if not line or line.startswith("#") or line.startswith("^"):
            continue
        match = PACKED_REF_RE.match(line)
        if match is not None and match.group(2) == ref_name:
            return match.group(1)
    return GIT_UNAVAILABLE


def _revision_id(path: Path) -> str:
    text = _read_text(path)
    match = REVISION_RE.search(text)
    if match is not None:
        value = match.group(1).strip()
        if value and "@" not in value and len(value) <= 200:
            return value
    stem = path.stem
    if stem and "@" not in stem:
        return stem
    return GIT_UNAVAILABLE


def _safe_sha(value: str) -> str:
    candidate = value.strip().lower()
    if SHA_RE.fullmatch(candidate):
        return candidate
    return GIT_UNAVAILABLE


def _safe_branch(value: str) -> str:
    candidate = value.strip()
    if BRANCH_RE.fullmatch(candidate) and "@" not in candidate:
        return candidate
    return GIT_UNAVAILABLE


def _read_text(path: Path) -> str:
    if not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _format_codes(values: Sequence[str]) -> str:
    return ",".join(values) if values else "-"


def _unique_sorted(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(sorted(set(values)))


def _bool_text(value: object) -> str:
    return "true" if value else "false"


def _unreachable(value: object) -> Never:
    raise RuntimeError(f"unhandled release artifact manifest variant: {value!r}")
