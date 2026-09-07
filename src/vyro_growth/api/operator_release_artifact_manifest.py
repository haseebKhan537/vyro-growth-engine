"""Read-only release artifact manifest HTML shell.

Phase 40 renders the Phase 39 release artifact manifest as an internal
HTML page. It never builds containers, publishes artifacts, deploys,
applies settings, lifts halt, enables outbound, executes requests,
packets, or approved items, sets live owner-approved state, or performs
any live action. This page is not a build, artifact publishing,
deployment mechanism, or permission to go live.
"""

from __future__ import annotations

from html import escape
from typing import Never

import structlog
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from vyro_growth.api.operator_ui import (
    COMPLIANCE_EVIDENCE_BINDER_JSON_PATH,
    LAUNCH_READINESS_JSON_PATH,
    NO_STORE_HEADERS,
    OPERATOR_AUDIT_TIMELINE_PATH,
    OPERATOR_COMPLIANCE_EVIDENCE_BINDER_PATH,
    OPERATOR_GO_LIVE_READINESS_INDEX_PATH,
    OPERATOR_GO_LIVE_REHEARSAL_CHECKLIST_PATH,
    OPERATOR_LAUNCH_BLOCKERS_PLAN_PATH,
    OPERATOR_OWNER_HANDOFF_PACKET_PATH,
    OPERATOR_OWNER_LAUNCH_DOSSIER_PATH,
    OPERATOR_PROVIDER_SETUP_CHECKLIST_PATH,
    OPERATOR_REHEARSAL_OUTCOME_REPORT_PATH,
    OPERATOR_RELEASE_CANDIDATE_RUNBOOK_PATH,
    OPERATOR_SETTINGS_EXECUTION_PREFLIGHT_PATH,
    OPERATOR_STAGED_ROLLOUT_PLAN_PATH,
    OPERATOR_SUPERVISED_PILOT_CANDIDATES_PATH,
    OPERATOR_SUPERVISED_PILOT_FIRST_SEND_PREFLIGHT_PATH,
    OPERATOR_SUPERVISED_PILOT_GO_NO_GO_PATH,
    OPERATOR_SUPERVISED_PILOT_LAUNCH_REHEARSAL_CONTROL_MAP_PATH,
    OPERATOR_SUPERVISED_PILOT_PLAN_PATH,
    OPERATOR_UI_STYLES,
    RELEASE_ARTIFACT_MANIFEST_JSON_PATH,
    format_dt,
    html_escape,
    metric,
    render_failure_page,
    render_operator_nav,
    titleize,
    yes_no,
)
from vyro_growth.api.release_artifact_manifest import (
    ArtifactInventoryItemResponse,
    LocalGitMetadataResponse,
    ManifestChecklistItemResponse,
    ManifestCiGateResponse,
    ManifestReusedSummariesResponse,
    MigrationInventoryItemResponse,
    NoBuildNoDeployEvidenceResponse,
    ReleaseArtifactManifestResponse,
    RuntimeCommandItemResponse,
    SafetyGateInventoryResponse,
    SourceProvenanceResponse,
    build_release_artifact_manifest_response,
)
from vyro_growth.config import Settings
from vyro_growth.domain import FindingSeverity
from vyro_growth.services.release_artifact_manifest import ReleaseArtifactManifestService

logger = structlog.get_logger(__name__)


def render_release_artifact_manifest_error() -> str:
    return render_failure_page(
        page_id="operator-release-artifact-manifest-error",
        title="Release artifact manifest unavailable",
        heading="Read-only release artifact manifest unavailable",
        banner="Unable to load the release artifact manifest.",
        detail=(
            "The sanitized owner-review manifest could not be rendered. "
            "Retry after checking database connectivity and runtime config. "
            "This page is not a build, artifact publishing, deployment "
            "mechanism, or permission to go live."
        ),
    )


def render_release_artifact_manifest(manifest: ReleaseArtifactManifestResponse) -> str:
    generated = html_escape(format_dt(manifest.generated_at))
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '  <meta charset="utf-8">\n'
        '  <meta name="viewport" content="width=device-width, initial-scale=1">\n'
        "  <title>Release artifact manifest</title>\n"
        f"{OPERATOR_UI_STYLES}\n"
        "</head>\n"
        "<body>\n"
        '  <main id="operator-release-artifact-manifest" data-read-only="true" '
        'data-dry-run-only="true" data-execution-allowed="false" '
        'data-go-live-permitted="false" data-deployment-allowed="false" '
        'data-build-allowed="false" data-artifact-publish-allowed="false" '
        'data-no-execution="true" data-manual-review-only="true" '
        'data-runbook-is-not-deployment="true" '
        'data-manifest-is-not-a-build-or-deploy="true">\n'
        f"{_render_header(manifest, generated)}\n"
        f"{render_operator_nav('release-artifact-manifest')}\n"
        f"{_render_related_links()}\n"
        f"{_render_overall(manifest)}\n"
        f"{_render_provenance(manifest.source_provenance)}\n"
        f"{_render_artifacts(manifest.artifact_inventory)}\n"
        f"{_render_migrations(manifest.migration_inventory)}\n"
        f"{_render_commands(manifest.runtime_command_inventory)}\n"
        f"{_render_gates(manifest.safety_gate_inventory)}\n"
        f"{_render_no_build(manifest.no_build_no_deploy)}\n"
        f"{_render_reused_summaries(manifest.reused_summaries)}\n"
        f"{_render_checklist(manifest.remaining_manual_owner_checklist)}\n"
        f"{_render_footer(manifest, generated)}\n"
        "  </main>\n"
        "</body>\n"
        "</html>\n"
    )


def build_operator_release_artifact_manifest_response(
    db: Session,
    settings: Settings,
    *,
    service: ReleaseArtifactManifestService | None = None,
) -> HTMLResponse:
    try:
        manifest = build_release_artifact_manifest_response(db, settings, service=service)
        html = render_release_artifact_manifest(manifest)
        return HTMLResponse(content=html, status_code=200, headers=NO_STORE_HEADERS)
    except Exception:
        logger.exception("operator_release_artifact_manifest_render_failed", read_only=True)
        return HTMLResponse(
            content=render_release_artifact_manifest_error(),
            status_code=500,
            headers=NO_STORE_HEADERS,
        )


def _render_header(manifest: ReleaseArtifactManifestResponse, generated: str) -> str:
    return (
        '    <header class="page-header">\n'
        "      <div>\n"
        "        <h1>Release artifact manifest</h1>\n"
        '        <p class="lede">Read-only owner-review view of expected source, '
        "artifacts, migrations, runtime commands, and safety gates. Execution "
        "remains disabled. This page does not build, publish, or deploy. "
        "go_live_permitted=false. execution_allowed=false. "
        "deployment_allowed=false. build_allowed=false. "
        "artifact_publish_allowed=false. runbook_is_not_deployment=true. "
        "manifest_is_not_a_build_or_deploy=true. This page is not a build, "
        "artifact publishing, deployment mechanism, or permission to go live.</p>\n"
        "      </div>\n"
        f'      <p class="meta">Generated {generated} · overall '
        f"{html_escape(manifest.overall_status)} · halt "
        f"{html_escape(manifest.operator_halt_status)} · "
        f"{html_escape(manifest.packet_kind)} · {html_escape(manifest.purpose)}</p>\n"
        "    </header>"
    )


def _render_related_links() -> str:
    json_href = escape(RELEASE_ARTIFACT_MANIFEST_JSON_PATH)
    runbook_href = escape(OPERATOR_RELEASE_CANDIDATE_RUNBOOK_PATH)
    binder_href = escape(OPERATOR_COMPLIANCE_EVIDENCE_BINDER_PATH)
    binder_json_href = escape(COMPLIANCE_EVIDENCE_BINDER_JSON_PATH)
    launch_href = escape(LAUNCH_READINESS_JSON_PATH)
    preflight_href = escape(OPERATOR_SETTINGS_EXECUTION_PREFLIGHT_PATH)
    handoff_href = escape(OPERATOR_OWNER_HANDOFF_PACKET_PATH)
    timeline_href = escape(OPERATOR_AUDIT_TIMELINE_PATH)
    index_href = escape(OPERATOR_GO_LIVE_READINESS_INDEX_PATH)
    plan_href = escape(OPERATOR_LAUNCH_BLOCKERS_PLAN_PATH)
    staged_href = escape(OPERATOR_STAGED_ROLLOUT_PLAN_PATH)
    dossier_href = escape(OPERATOR_OWNER_LAUNCH_DOSSIER_PATH)
    checklist_href = escape(OPERATOR_PROVIDER_SETUP_CHECKLIST_PATH)
    rehearsal_href = escape(OPERATOR_GO_LIVE_REHEARSAL_CHECKLIST_PATH)
    outcome_href = escape(OPERATOR_REHEARSAL_OUTCOME_REPORT_PATH)
    pilot_href = escape(OPERATOR_SUPERVISED_PILOT_PLAN_PATH)
    candidates_href = escape(OPERATOR_SUPERVISED_PILOT_CANDIDATES_PATH)
    go_no_go_href = escape(OPERATOR_SUPERVISED_PILOT_GO_NO_GO_PATH)
    first_send_href = escape(OPERATOR_SUPERVISED_PILOT_FIRST_SEND_PREFLIGHT_PATH)
    control_map_href = escape(OPERATOR_SUPERVISED_PILOT_LAUNCH_REHEARSAL_CONTROL_MAP_PATH)
    return (
        '    <nav class="filter-nav" aria-label="Related read-only surfaces">\n'
        f'      <a class="nav-link nav-json" href="{json_href}">JSON manifest</a>\n'
        f'      <a class="nav-link" href="{runbook_href}">Release runbook</a>\n'
        f'      <a class="nav-link" href="{binder_href}">Compliance binder</a>\n'
        f'      <a class="nav-link" href="{binder_json_href}">JSON binder</a>\n'
        f'      <a class="nav-link" href="{launch_href}">Launch readiness JSON</a>\n'
        f'      <a class="nav-link" href="{preflight_href}">Settings preflight</a>\n'
        f'      <a class="nav-link" href="{handoff_href}">Owner handoff</a>\n'
        f'      <a class="nav-link" href="{timeline_href}">Audit timeline</a>\n'
        f'      <a class="nav-link" href="{index_href}">Go-live index</a>\n'
        f'      <a class="nav-link" href="{plan_href}">Launch blockers</a>\n'
        f'      <a class="nav-link" href="{staged_href}">Staged rollout</a>\n'
        f'      <a class="nav-link" href="{dossier_href}">Owner launch dossier</a>\n'
        f'      <a class="nav-link" href="{checklist_href}">Provider setup</a>\n'
        f'      <a class="nav-link" href="{rehearsal_href}">Go-live rehearsal</a>\n'
        f'      <a class="nav-link" href="{outcome_href}">Rehearsal outcome</a>\n'
        f'      <a class="nav-link" href="{pilot_href}">Supervised pilot</a>\n'
        f'      <a class="nav-link" href="{candidates_href}">Pilot candidates</a>\n'
        f'      <a class="nav-link" href="{go_no_go_href}">Pilot go/no-go</a>\n'
        f'      <a class="nav-link" href="{first_send_href}">First-send preflight</a>\n'
        f'      <a class="nav-link" href="{control_map_href}">Rehearsal control map</a>\n'
        "    </nav>"
    )


def _render_overall(manifest: ReleaseArtifactManifestResponse) -> str:
    return (
        '    <section class="status-strip" aria-label="Manifest flags">\n'
        f"      {metric('Overall', manifest.overall_status)}\n"
        f"      {metric('Go live permitted', yes_no(manifest.go_live_permitted))}\n"
        f"      {metric('Execution allowed', yes_no(manifest.execution_allowed))}\n"
        f"      {metric('Deployment allowed', yes_no(manifest.deployment_allowed))}\n"
        f"      {metric('Build allowed', yes_no(manifest.build_allowed))}\n"
        f"      {metric('Artifact publish allowed',
            yes_no(manifest.artifact_publish_allowed))}\n"
        f"      {metric('Runbook is not deployment',
            yes_no(manifest.runbook_is_not_deployment))}\n"
        f"      {metric('Manifest is not a build or deploy',
            yes_no(manifest.manifest_is_not_a_build_or_deploy))}\n"
        f"      {metric('Manual review only', yes_no(manifest.manual_review_only))}\n"
        f"      {metric('Read only', yes_no(manifest.read_only))}\n"
        f"      {metric('Dry-run only', yes_no(manifest.dry_run_only))}\n"
        f"      {metric('No execution', yes_no(manifest.no_execution))}\n"
        f"      {metric('Executed', manifest.executed)}\n"
        "    </section>\n"
        '    <section class="panel" id="manifest-gates">\n'
        "      <h2>Manual-review gates</h2>\n"
        '      <div class="metric-grid">\n'
        f"        {metric('Outbound enabled', yes_no(manifest.outbound_enabled))}\n"
        f"        {metric('Live providers', yes_no(manifest.live_providers_enabled))}\n"
        f"        {metric('Operator halt', manifest.operator_halt_status)}\n"
        f"        {metric('Halt before', manifest.operator_halt_before)}\n"
        f"        {metric('Halt after', manifest.operator_halt_after)}\n"
        f"        {metric('Halt changed', yes_no(manifest.halt_changed))}\n"
        f"        {metric('Settings applied', yes_no(manifest.settings_applied))}\n"
        f"        {metric('Owner approved live', yes_no(manifest.owner_approved))}\n"
        f"        {metric('Live action', yes_no(manifest.live_action))}\n"
        f"        {metric('Deployed', yes_no(manifest.deployed))}\n"
        f"        {metric('Deployment attempted', yes_no(manifest.deployment_attempted))}\n"
        f"        {metric('Container build attempted',
            yes_no(manifest.container_build_attempted))}\n"
        f"        {metric('Artifact publish attempted',
            yes_no(manifest.artifact_publish_attempted))}\n"
        f"        {metric('Future execution phase',
            yes_no(manifest.future_execution_phase_exists))}\n"
        f"        {metric('Future deployment phase',
            yes_no(manifest.future_deployment_phase_exists))}\n"
        f"        {metric('Outbound attempted', yes_no(manifest.outbound_attempted))}\n"
        f"        {metric('Spend attempted', yes_no(manifest.spend_attempted))}\n"
        f"        {metric('CLI command', manifest.cli_command)}\n"
        f"        {metric('HTTP route', manifest.http_route)}\n"
        "      </div>\n"
        "      <h3>Blocker codes</h3>\n"
        f"      {_render_codes(manifest.blocker_codes, empty='No blocker codes.')}\n"
        "      <h3>Missing credential variable names</h3>\n"
        f"      {_render_codes(manifest.missing_credential_names, empty='None missing.')}\n"
        "      <h3>Closed provider flag names</h3>\n"
        f"      {_render_codes(manifest.closed_provider_flag_names, empty='None closed.')}\n"
        "      <h3>Related commands</h3>\n"
        f"      {_render_codes(manifest.related_commands, empty='No related commands.')}\n"
        "      <h3>Related routes</h3>\n"
        f"      {_render_codes(manifest.related_routes, empty='No related routes.')}\n"
        '      <p class="hint">This page never shows secret values, environment '
        "values, API keys, tokens, message bodies, emails, phones, evidence "
        "snippets, or unsafe error text. go_live_permitted=false, "
        "execution_allowed=false, deployment_allowed=false, build_allowed=false, "
        "artifact_publish_allowed=false, runbook_is_not_deployment=true, and "
        "manifest_is_not_a_build_or_deploy=true. This is a read-only owner-review "
        "view, not a build, artifact publishing, deployment mechanism, or "
        "permission to go live.</p>\n"
        "    </section>"
    )


def _render_provenance(provenance: SourceProvenanceResponse) -> str:
    return (
        '    <section class="panel" id="source-and-provenance-expectations">\n'
        "      <h2>Source and provenance expectations</h2>\n"
        '      <div class="metric-grid">\n'
        f"        {metric('Expected repo name', provenance.expected_repo_name)}\n"
        f"        {metric('Expected base branch', provenance.expected_base_branch)}\n"
        f"        {metric('Expected workflow path', provenance.expected_workflow_path)}\n"
        f"        {metric('Expected release channel', provenance.expected_release_channel)}\n"
        f"        {metric('SHA source', provenance.sha_source)}\n"
        f"        {metric('Git provider called', yes_no(provenance.git_provider_called))}\n"
        f"        {metric('GitHub Actions called',
            yes_no(provenance.github_actions_called))}\n"
        "      </div>\n"
        f"      {_render_local_git(provenance.local_git)}\n"
        '      <p class="hint">Local git metadata is read from .git files when '
        "present. This page does not call GitHub Actions or git remotes, and it "
        "does not build or deploy from this manifest.</p>\n"
        "    </section>"
    )


def _render_local_git(metadata: LocalGitMetadataResponse) -> str:
    return (
        "      <h3>Local git metadata</h3>\n"
        '      <div class="metric-grid">\n'
        f"        {metric('Available', yes_no(metadata.available))}\n"
        f"        {metric('Current branch', metadata.current_branch)}\n"
        f"        {metric('Current SHA', metadata.current_sha)}\n"
        f"        {metric('Working tree', metadata.working_tree_status)}\n"
        f"        {metric('Git provider called', yes_no(metadata.git_provider_called))}\n"
        f"        {metric('GitHub Actions called',
            yes_no(metadata.github_actions_called))}\n"
        "      </div>"
    )


def _render_artifacts(items: list[ArtifactInventoryItemResponse]) -> str:
    if not items:
        return (
            '    <section class="panel" id="artifact-inventory">\n'
            "      <h2>Artifact inventory</h2>\n"
            '      <p class="empty-state" id="empty-artifact-inventory">'
            "No expected artifacts were inspected. This page does not build or "
            "publish artifacts.</p>\n"
            "    </section>"
        )
    rows = "".join(_artifact_row(item) for item in items)
    return (
        '    <section class="panel" id="artifact-inventory">\n'
        "      <h2>Artifact inventory</h2>\n"
        '      <table class="dense"><thead><tr>'
        "<th>Kind</th><th>Path</th><th>Present</th><th>Directory</th>"
        f"</tr></thead><tbody>{rows}</tbody></table>\n"
        '      <p class="hint">Filenames and presence only. This page does not '
        "build containers or publish artifacts.</p>\n"
        "    </section>"
    )


def _artifact_row(item: ArtifactInventoryItemResponse) -> str:
    return (
        "<tr>"
        f'<td class="mono">{html_escape(item.kind)}</td>'
        f'<td class="mono">{html_escape(item.path)}</td>'
        f"<td>{yes_no(item.present)}</td>"
        f"<td>{yes_no(item.is_directory)}</td>"
        "</tr>"
    )


def _render_migrations(items: list[MigrationInventoryItemResponse]) -> str:
    if not items:
        return (
            '    <section class="panel" id="migration-inventory">\n'
            "      <h2>Migration inventory</h2>\n"
            '      <p class="empty-state" id="empty-migration-inventory">'
            "No migration revision files were inspected. This page does not apply "
            "migrations.</p>\n"
            "    </section>"
        )
    rows = "".join(_migration_row(item) for item in items)
    return (
        '    <section class="panel" id="migration-inventory">\n'
        "      <h2>Migration inventory</h2>\n"
        '      <table class="dense"><thead><tr>'
        "<th>Filename</th><th>Revision id</th>"
        f"</tr></thead><tbody>{rows}</tbody></table>\n"
        '      <p class="hint">Revision filenames and ids only. This page does '
        "not run Alembic or apply schema changes.</p>\n"
        "    </section>"
    )


def _migration_row(item: MigrationInventoryItemResponse) -> str:
    return (
        "<tr>"
        f'<td class="mono">{html_escape(item.filename)}</td>'
        f'<td class="mono">{html_escape(item.revision_id)}</td>'
        "</tr>"
    )


def _render_commands(items: list[RuntimeCommandItemResponse]) -> str:
    if not items:
        return (
            '    <section class="panel" id="runtime-command-inventory">\n'
            "      <h2>Runtime command inventory</h2>\n"
            '      <p class="empty-state" id="empty-runtime-command-inventory">'
            "No runtime commands were listed. This page does not run commands.</p>\n"
            "    </section>"
        )
    rows = "".join(_command_row(item) for item in items)
    return (
        '    <section class="panel" id="runtime-command-inventory">\n'
        "      <h2>Runtime command inventory</h2>\n"
        '      <table class="dense"><thead><tr>'
        "<th>Kind</th><th>Command</th>"
        f"</tr></thead><tbody>{rows}</tbody></table>\n"
        '      <p class="hint">Command names for owner review only. This page '
        "does not run them.</p>\n"
        "    </section>"
    )


def _command_row(item: RuntimeCommandItemResponse) -> str:
    return (
        "<tr>"
        f'<td class="mono">{html_escape(item.kind)}</td>'
        f'<td class="mono">{html_escape(item.command_name)}</td>'
        "</tr>"
    )


def _render_gates(gates: SafetyGateInventoryResponse) -> str:
    return (
        '    <section class="panel" id="safety-gate-inventory">\n'
        "      <h2>Safety gate inventory</h2>\n"
        "      <h3>Required CI job names</h3>\n"
        f"      {_render_codes(gates.required_ci_job_names, empty='No CI job names.')}\n"
        "      <h3>Smoke-dry-run gate</h3>\n"
        f"      {_render_gate(gates.smoke_gate)}\n"
        "      <h3>Deploy-config gate</h3>\n"
        f"      {_render_gate(gates.deploy_config_gate)}\n"
        '      <div class="metric-grid">\n'
        f"        {metric('Outbound enabled required',
            yes_no(gates.outbound_enabled_required))}\n"
        f"        {metric('Outbound enabled', yes_no(gates.outbound_enabled))}\n"
        f"        {metric('Live providers', yes_no(gates.live_providers_enabled))}\n"
        f"        {metric('.env.example defaults',
            yes_no(gates.env_example_defaults_present))}\n"
        f"        {metric('Dockerfile defaults',
            yes_no(gates.dockerfile_defaults_present))}\n"
        f"        {metric('Compose defaults', yes_no(gates.compose_defaults_present))}\n"
        f"        {metric('GitHub Actions called', yes_no(gates.github_actions_called))}\n"
        "      </div>\n"
        "      <h3>Required flag names</h3>\n"
        f"      {_render_codes(gates.required_flag_names, empty='None required.')}\n"
        "      <h3>Closed provider flag names</h3>\n"
        f"      {_render_codes(gates.closed_provider_flag_names, empty='None closed.')}\n"
        "      <h3>Missing credential variable names</h3>\n"
        f"      {_render_codes(gates.missing_credential_names, empty='None missing.')}\n"
        '      <p class="hint">Only flag names, states, missing credential '
        "variable names, and CI job/command names are shown. Secret values and "
        "raw environment values are never included. OUTBOUND_ENABLED remains "
        "false by default. This page does not run CI or call GitHub Actions.</p>\n"
        "    </section>"
    )


def _render_gate(status: ManifestCiGateResponse) -> str:
    return (
        '<div class="metric-grid">\n'
        f"        {metric('Present', yes_no(status.present))}\n"
        f"        {metric('Documented', yes_no(status.documented))}\n"
        f"        {metric('Job name', status.job_name)}\n"
        f"        {metric('Command name', status.command_name)}\n"
        "      </div>"
    )


def _render_no_build(evidence: NoBuildNoDeployEvidenceResponse) -> str:
    return (
        '    <section class="panel" id="no-build-no-deploy-evidence">\n'
        "      <h2>No-build and no-deploy evidence</h2>\n"
        '      <div class="metric-grid">\n'
        f"        {metric('Build allowed', yes_no(evidence.build_allowed))}\n"
        f"        {metric('Artifact publish allowed',
            yes_no(evidence.artifact_publish_allowed))}\n"
        f"        {metric('Container build attempted',
            yes_no(evidence.container_build_attempted))}\n"
        f"        {metric('Artifact publish attempted',
            yes_no(evidence.artifact_publish_attempted))}\n"
        f"        {metric('Deployment allowed', yes_no(evidence.deployment_allowed))}\n"
        f"        {metric('Deployment attempted', yes_no(evidence.deployment_attempted))}\n"
        f"        {metric('Deployed', yes_no(evidence.deployed))}\n"
        f"        {metric('Runbook is not deployment',
            yes_no(evidence.runbook_is_not_deployment))}\n"
        f"        {metric('Manifest is not a build or deploy',
            yes_no(evidence.manifest_is_not_a_build_or_deploy))}\n"
        f"        {metric('GitHub Actions called',
            yes_no(evidence.github_actions_called))}\n"
        f"        {metric('Git provider called', yes_no(evidence.git_provider_called))}\n"
        "      </div>\n"
        '      <p class="hint">This page never builds containers, publishes '
        "artifacts, or deploys. There is no build, publish, or deploy control.</p>\n"
        "    </section>"
    )


def _render_reused_summaries(evidence: ManifestReusedSummariesResponse) -> str:
    return (
        '    <section class="panel" id="reused-summaries">\n'
        "      <h2>Reused read-only summaries</h2>\n"
        '      <div class="metric-grid">\n'
        f"        {metric('Launch readiness', evidence.launch_readiness_overall_status)}\n"
        f"        {metric('Settings preflight', evidence.settings_preflight_overall_status)}\n"
        f"        {metric('Preflight blocked', evidence.settings_preflight_blocked_count)}\n"
        f"        {metric('Preflight execution allowed',
            yes_no(evidence.settings_preflight_execution_allowed))}\n"
        f"        {metric('Handoff go live permitted',
            yes_no(evidence.owner_handoff_go_live_permitted))}\n"
        f"        {metric('Handoff execution allowed',
            yes_no(evidence.owner_handoff_execution_allowed))}\n"
        f"        {metric('Binder is not go-live', yes_no(evidence.binder_is_not_go_live))}\n"
        f"        {metric('Binder command', evidence.binder_command)}\n"
        f"        {metric('Binder route', evidence.binder_route)}\n"
        f"        {metric('Runbook is not deployment',
            yes_no(evidence.runbook_is_not_deployment))}\n"
        f"        {metric('Runbook command', evidence.runbook_command)}\n"
        f"        {metric('Runbook route', evidence.runbook_route)}\n"
        f"        {metric('Audit timeline matching', evidence.audit_timeline_matching_count)}\n"
        f"        {metric('Audit timeline route', evidence.audit_timeline_route)}\n"
        "      </div>\n"
        "      <h3>Launch readiness blocker codes</h3>\n"
        f"      {_render_codes(
            evidence.launch_readiness_blocker_codes, empty='No blocker codes.'
        )}\n"
        "    </section>"
    )


def _render_checklist(items: list[ManifestChecklistItemResponse]) -> str:
    if not items:
        return (
            '    <section class="panel" id="remaining-manual-owner-checklist">\n'
            "      <h2>Remaining unresolved blockers and manual owner checklist</h2>\n"
            '      <p class="empty-state" id="empty-remaining-manual-owner-checklist">'
            "No remaining checklist items. This page still does not permit "
            "building, publishing, deploying, going live, or executing anything.</p>\n"
            "    </section>"
        )
    rows = "".join(_checklist_row(item) for item in items)
    return (
        '    <section class="panel" id="remaining-manual-owner-checklist">\n'
        "      <h2>Remaining unresolved blockers and manual owner checklist</h2>\n"
        '      <table class="dense"><thead><tr>'
        "<th>Code</th><th>Severity</th><th>Source</th><th>Status</th>"
        f"</tr></thead><tbody>{rows}</tbody></table>\n"
        "    </section>"
    )


def _checklist_row(item: ManifestChecklistItemResponse) -> str:
    return (
        f'<tr class="{_severity_class(item.severity)}">'
        f'<td class="mono">{html_escape(item.code)}</td>'
        f"<td>{html_escape(item.severity)}</td>"
        f"<td>{titleize(item.source_section)}</td>"
        f"<td>{html_escape(item.status)}</td>"
        "</tr>"
    )


def _render_footer(manifest: ReleaseArtifactManifestResponse, generated: str) -> str:
    return (
        '    <footer class="footnote" id="side-effects">\n'
        f"      <p>Generated {generated}. Read-only={yes_no(manifest.read_only)}. "
        f"Manual review only={yes_no(manifest.manual_review_only)}. "
        f"Dry-run only={yes_no(manifest.dry_run_only)}. "
        f"No execution={yes_no(manifest.no_execution)}. "
        f"Executed={html_escape(manifest.executed)}. "
        f"Settings applied={yes_no(manifest.settings_applied)}. "
        f"Halt changed={yes_no(manifest.halt_changed)}. "
        f"Owner approved={yes_no(manifest.owner_approved)}. "
        f"Live action={yes_no(manifest.live_action)}. "
        f"Execution allowed={yes_no(manifest.execution_allowed)}. "
        f"Go live permitted={yes_no(manifest.go_live_permitted)}. "
        f"Deployment allowed={yes_no(manifest.deployment_allowed)}. "
        f"Deployment attempted={yes_no(manifest.deployment_attempted)}. "
        f"Deployed={yes_no(manifest.deployed)}. "
        f"Build allowed={yes_no(manifest.build_allowed)}. "
        f"Artifact publish allowed={yes_no(manifest.artifact_publish_allowed)}. "
        f"Container build attempted={yes_no(manifest.container_build_attempted)}. "
        f"Artifact publish attempted={yes_no(manifest.artifact_publish_attempted)}. "
        f"Runbook is not deployment={yes_no(manifest.runbook_is_not_deployment)}. "
        f"Manifest is not a build or deploy="
        f"{yes_no(manifest.manifest_is_not_a_build_or_deploy)}. "
        f"Future execution phase exists="
        f"{yes_no(manifest.future_execution_phase_exists)}. "
        f"Future deployment phase exists="
        f"{yes_no(manifest.future_deployment_phase_exists)}. "
        "There are no apply, execute, lift-halt, enable-outbound, provider, "
        "build, publish, deploy, campaign, booking, call, or spend controls on "
        "this page. This is a read-only owner-review view, not a build, artifact "
        "publishing, deployment mechanism, or permission to go live.</p>\n"
        "    </footer>"
    )


def _render_codes(codes: list[str], *, empty: str) -> str:
    unique = [code for code in dict.fromkeys(codes) if code]
    if not unique:
        return f'<p class="empty-state">{escape(empty)}</p>'
    rows = "".join(f'<li class="mono">{html_escape(code)}</li>' for code in unique)
    return f'<ul class="plain">{rows}</ul>'


def _severity_class(severity: str) -> str:
    match severity:
        case FindingSeverity.BLOCKED.value:
            return "severity-blocked"
        case FindingSeverity.WARNING.value:
            return "severity-warning"
        case FindingSeverity.INFO.value:
            return "severity-info"
        case _:
            return _unreachable_severity(severity)


def _unreachable_severity(value: str) -> Never:
    raise RuntimeError(f"unhandled release artifact manifest checklist severity: {value!r}")
