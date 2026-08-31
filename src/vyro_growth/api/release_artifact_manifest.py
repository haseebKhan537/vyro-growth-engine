from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from vyro_growth.config import Settings
from vyro_growth.services.release_artifact_manifest import (
    ArtifactInventoryItem,
    LocalGitMetadata,
    ManifestChecklistItem,
    ManifestReusedSummaries,
    MigrationInventoryItem,
    NoBuildNoDeployEvidence,
    ReleaseArtifactManifest,
    ReleaseArtifactManifestService,
    RuntimeCommandItem,
    SafetyGateInventory,
    SourceProvenance,
)
from vyro_growth.services.release_candidate_runbook import RunbookCiGate


class ManifestChecklistItemResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    severity: str
    source_section: str
    status: str


class LocalGitMetadataResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    available: bool = False
    current_branch: str
    current_sha: str
    working_tree_status: str
    git_provider_called: bool = False
    github_actions_called: bool = False


class SourceProvenanceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_repo_name: str
    expected_base_branch: str
    expected_workflow_path: str
    expected_release_channel: str
    sha_source: str
    local_git: LocalGitMetadataResponse
    git_provider_called: bool = False
    github_actions_called: bool = False


class ArtifactInventoryItemResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str
    path: str
    present: bool = False
    is_directory: bool = False


class MigrationInventoryItemResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filename: str
    revision_id: str


class RuntimeCommandItemResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str
    command_name: str


class ManifestCiGateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    present: bool = False
    documented: bool = False
    job_name: str
    command_name: str


class SafetyGateInventoryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    required_ci_job_names: list[str] = Field(default_factory=list)
    smoke_gate: ManifestCiGateResponse
    deploy_config_gate: ManifestCiGateResponse
    outbound_enabled_required: bool = False
    outbound_enabled: bool = False
    live_providers_enabled: bool = False
    required_flag_names: list[str] = Field(default_factory=list)
    closed_provider_flag_names: list[str] = Field(default_factory=list)
    missing_credential_names: list[str] = Field(default_factory=list)
    env_example_defaults_present: bool = False
    dockerfile_defaults_present: bool = False
    compose_defaults_present: bool = False
    github_actions_called: bool = False


class NoBuildNoDeployEvidenceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    build_allowed: bool = False
    artifact_publish_allowed: bool = False
    container_build_attempted: bool = False
    artifact_publish_attempted: bool = False
    deployment_allowed: bool = False
    deployment_attempted: bool = False
    deployed: bool = False
    runbook_is_not_deployment: bool = True
    manifest_is_not_a_build_or_deploy: bool = True
    github_actions_called: bool = False
    git_provider_called: bool = False


class ManifestReusedSummariesResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    launch_readiness_overall_status: str
    launch_readiness_blocker_codes: list[str] = Field(default_factory=list)
    settings_preflight_overall_status: str
    settings_preflight_blocked_count: int = 0
    settings_preflight_execution_allowed: bool = False
    owner_handoff_go_live_permitted: bool = False
    owner_handoff_execution_allowed: bool = False
    binder_is_not_go_live: bool = True
    binder_command: str
    binder_route: str
    runbook_is_not_deployment: bool = True
    runbook_command: str
    runbook_route: str
    audit_timeline_matching_count: int = 0
    audit_timeline_route: str


class ReleaseArtifactManifestResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    generated_at: datetime
    packet_kind: str = "release_artifact_manifest"
    purpose: str = "future_manual_owner_review_only"
    overall_status: str
    read_only: bool = True
    no_execution: bool = True
    dry_run_only: bool = True
    executed: int = 0
    execution_attempted: bool = False
    outbound_attempted: bool = False
    live_call_attempted: bool = False
    recommendation_applied: bool = False
    spend_attempted: bool = False
    campaign_launched: bool = False
    pages_published: bool = False
    ads_launched: bool = False
    owner_approved: bool = False
    settings_applied: bool = False
    halt_changed: bool = False
    live_action: bool = False
    execution_allowed: bool = False
    future_execution_phase_exists: bool = False
    future_deployment_phase_exists: bool = False
    go_live_permitted: bool = False
    deployment_allowed: bool = False
    deployment_attempted: bool = False
    deployed: bool = False
    build_allowed: bool = False
    artifact_publish_allowed: bool = False
    container_build_attempted: bool = False
    artifact_publish_attempted: bool = False
    manual_review_only: bool = True
    runbook_is_not_deployment: bool = True
    manifest_is_not_a_build_or_deploy: bool = True
    operator_halt_status: str
    operator_halt_before: str
    operator_halt_after: str
    outbound_enabled: bool = False
    live_providers_enabled: bool = False
    cli_command: str = "release-artifact-manifest"
    http_route: str = "/internal/release-artifact-manifest"
    related_commands: list[str] = Field(default_factory=list)
    related_routes: list[str] = Field(default_factory=list)
    blocker_codes: list[str] = Field(default_factory=list)
    missing_credential_names: list[str] = Field(default_factory=list)
    closed_provider_flag_names: list[str] = Field(default_factory=list)
    source_provenance: SourceProvenanceResponse
    artifact_inventory: list[ArtifactInventoryItemResponse] = Field(default_factory=list)
    migration_inventory: list[MigrationInventoryItemResponse] = Field(default_factory=list)
    runtime_command_inventory: list[RuntimeCommandItemResponse] = Field(default_factory=list)
    safety_gate_inventory: SafetyGateInventoryResponse
    no_build_no_deploy: NoBuildNoDeployEvidenceResponse
    reused_summaries: ManifestReusedSummariesResponse
    remaining_manual_owner_checklist: list[ManifestChecklistItemResponse] = Field(
        default_factory=list
    )


def _git_to_response(metadata: LocalGitMetadata) -> LocalGitMetadataResponse:
    return LocalGitMetadataResponse(
        available=metadata.available,
        current_branch=metadata.current_branch,
        current_sha=metadata.current_sha,
        working_tree_status=metadata.working_tree_status,
        git_provider_called=False,
        github_actions_called=False,
    )


def _provenance_to_response(provenance: SourceProvenance) -> SourceProvenanceResponse:
    return SourceProvenanceResponse(
        expected_repo_name=provenance.expected_repo_name,
        expected_base_branch=provenance.expected_base_branch,
        expected_workflow_path=provenance.expected_workflow_path,
        expected_release_channel=provenance.expected_release_channel,
        sha_source=provenance.sha_source,
        local_git=_git_to_response(provenance.local_git),
        git_provider_called=False,
        github_actions_called=False,
    )


def _artifact_to_response(item: ArtifactInventoryItem) -> ArtifactInventoryItemResponse:
    return ArtifactInventoryItemResponse(
        kind=item.kind,
        path=item.path,
        present=item.present,
        is_directory=item.is_directory,
    )


def _migration_to_response(item: MigrationInventoryItem) -> MigrationInventoryItemResponse:
    return MigrationInventoryItemResponse(
        filename=item.filename,
        revision_id=item.revision_id,
    )


def _command_to_response(item: RuntimeCommandItem) -> RuntimeCommandItemResponse:
    return RuntimeCommandItemResponse(kind=item.kind, command_name=item.command_name)


def _gate_to_response(gate: RunbookCiGate) -> ManifestCiGateResponse:
    return ManifestCiGateResponse(
        present=gate.present,
        documented=gate.documented,
        job_name=gate.job_name,
        command_name=gate.command_name,
    )


def _gates_to_response(gates: SafetyGateInventory) -> SafetyGateInventoryResponse:
    return SafetyGateInventoryResponse(
        required_ci_job_names=list(gates.required_ci_job_names),
        smoke_gate=_gate_to_response(gates.smoke_gate),
        deploy_config_gate=_gate_to_response(gates.deploy_config_gate),
        outbound_enabled_required=False,
        outbound_enabled=gates.outbound_enabled,
        live_providers_enabled=gates.live_providers_enabled,
        required_flag_names=list(gates.required_flag_names),
        closed_provider_flag_names=list(gates.closed_provider_flag_names),
        missing_credential_names=list(gates.missing_credential_names),
        env_example_defaults_present=gates.env_example_defaults_present,
        dockerfile_defaults_present=gates.dockerfile_defaults_present,
        compose_defaults_present=gates.compose_defaults_present,
        github_actions_called=False,
    )


def _no_build_to_response(evidence: NoBuildNoDeployEvidence) -> NoBuildNoDeployEvidenceResponse:
    return NoBuildNoDeployEvidenceResponse(
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


def _reused_to_response(summary: ManifestReusedSummaries) -> ManifestReusedSummariesResponse:
    return ManifestReusedSummariesResponse(
        launch_readiness_overall_status=summary.launch_readiness_overall_status,
        launch_readiness_blocker_codes=list(summary.launch_readiness_blocker_codes),
        settings_preflight_overall_status=summary.settings_preflight_overall_status,
        settings_preflight_blocked_count=summary.settings_preflight_blocked_count,
        settings_preflight_execution_allowed=False,
        owner_handoff_go_live_permitted=False,
        owner_handoff_execution_allowed=False,
        binder_is_not_go_live=True,
        binder_command=summary.binder_command,
        binder_route=summary.binder_route,
        runbook_is_not_deployment=True,
        runbook_command=summary.runbook_command,
        runbook_route=summary.runbook_route,
        audit_timeline_matching_count=summary.audit_timeline_matching_count,
        audit_timeline_route=summary.audit_timeline_route,
    )


def _checklist_to_response(item: ManifestChecklistItem) -> ManifestChecklistItemResponse:
    return ManifestChecklistItemResponse(
        code=item.code,
        severity=item.severity,
        source_section=item.source_section,
        status=item.status,
    )


def manifest_to_response(manifest: ReleaseArtifactManifest) -> ReleaseArtifactManifestResponse:
    return ReleaseArtifactManifestResponse(
        generated_at=manifest.generated_at,
        packet_kind="release_artifact_manifest",
        purpose="future_manual_owner_review_only",
        overall_status=manifest.overall_status,
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
        operator_halt_status=manifest.operator_halt_status,
        operator_halt_before=manifest.operator_halt_before,
        operator_halt_after=manifest.operator_halt_after,
        outbound_enabled=manifest.outbound_enabled,
        live_providers_enabled=manifest.live_providers_enabled,
        cli_command="release-artifact-manifest",
        http_route="/internal/release-artifact-manifest",
        related_commands=list(manifest.related_commands),
        related_routes=list(manifest.related_routes),
        blocker_codes=list(manifest.blocker_codes),
        missing_credential_names=list(manifest.missing_credential_names),
        closed_provider_flag_names=list(manifest.closed_provider_flag_names),
        source_provenance=_provenance_to_response(manifest.source_provenance),
        artifact_inventory=[_artifact_to_response(item) for item in manifest.artifact_inventory],
        migration_inventory=[
            _migration_to_response(item) for item in manifest.migration_inventory
        ],
        runtime_command_inventory=[
            _command_to_response(item) for item in manifest.runtime_command_inventory
        ],
        safety_gate_inventory=_gates_to_response(manifest.safety_gate_inventory),
        no_build_no_deploy=_no_build_to_response(manifest.no_build_no_deploy),
        reused_summaries=_reused_to_response(manifest.reused_summaries),
        remaining_manual_owner_checklist=[
            _checklist_to_response(item) for item in manifest.remaining_manual_owner_checklist
        ],
    )


def build_release_artifact_manifest_response(
    db: Session,
    settings: Settings,
    *,
    service: ReleaseArtifactManifestService | None = None,
) -> ReleaseArtifactManifestResponse:
    builder = service or ReleaseArtifactManifestService()
    return manifest_to_response(builder.build(db, settings))
