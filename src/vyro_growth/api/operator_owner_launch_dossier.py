"""Read-only operator owner launch dossier HTML shell.

Phase 48 renders a sanitized view of the existing Phase 47 owner launch
dossier. It reuses OwnerLaunchDossierService and never recalculates
readiness. It never executes, builds, publishes, deploys, applies settings,
lifts halt, enables outbound, calls providers, or changes live state. This
page is a launch dossier review view only, not permission to go live and
not an execution surface.
"""

from __future__ import annotations

from html import escape

import structlog
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from vyro_growth.api.operator_ui import (
    COMPLIANCE_EVIDENCE_BINDER_JSON_PATH,
    GO_LIVE_READINESS_INDEX_JSON_PATH,
    LAUNCH_BLOCKERS_PLAN_JSON_PATH,
    LAUNCH_READINESS_JSON_PATH,
    NO_STORE_HEADERS,
    OPERATOR_AUDIT_TIMELINE_PATH,
    OPERATOR_COMPLIANCE_EVIDENCE_BINDER_PATH,
    OPERATOR_DASHBOARD_PATH,
    OPERATOR_GO_LIVE_READINESS_INDEX_PATH,
    OPERATOR_LAUNCH_BLOCKERS_PLAN_PATH,
    OPERATOR_OWNER_HANDOFF_PACKET_PATH,
    OPERATOR_OWNER_LAUNCH_DOSSIER_PATH,
    OPERATOR_RELEASE_ARTIFACT_MANIFEST_PATH,
    OPERATOR_RELEASE_CANDIDATE_RUNBOOK_PATH,
    OPERATOR_SETTINGS_EXECUTION_PREFLIGHT_PATH,
    OPERATOR_STAGED_ROLLOUT_PLAN_PATH,
    OPERATOR_UI_STYLES,
    OWNER_HANDOFF_JSON_PATH,
    OWNER_LAUNCH_DOSSIER_JSON_PATH,
    RELEASE_ARTIFACT_MANIFEST_JSON_PATH,
    RELEASE_CANDIDATE_RUNBOOK_JSON_PATH,
    SETTINGS_EXECUTION_PREFLIGHT_JSON_PATH,
    STAGED_ROLLOUT_PLAN_JSON_PATH,
    format_dt,
    html_escape,
    metric,
    render_failure_page,
    render_operator_nav,
    yes_no,
)
from vyro_growth.config import Settings
from vyro_growth.domain import FindingSeverity
from vyro_growth.services.owner_launch_dossier import (
    DossierAuditSummary,
    DossierNextAction,
    DossierSettingsPreflightSummary,
    DossierSourceSurface,
    OwnerLaunchDossier,
    OwnerLaunchDossierService,
)
from vyro_growth.services.release_artifact_manifest import LocalGitMetadata

logger = structlog.get_logger(__name__)


def render_owner_launch_dossier_error() -> str:
    return render_failure_page(
        page_id="operator-owner-launch-dossier-error",
        title="Owner launch dossier unavailable",
        heading="Read-only owner launch dossier unavailable",
        banner="Unable to load the owner launch dossier.",
        detail=(
            "The sanitized launch-dossier review view could not be rendered. "
            "Retry after checking database connectivity and runtime config. "
            "This page is a launch dossier review view only, not permission "
            "to go live and not an execution surface."
        ),
    )


def render_owner_launch_dossier(dossier: OwnerLaunchDossier) -> str:
    generated = html_escape(format_dt(dossier.generated_at))
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '  <meta charset="utf-8">\n'
        '  <meta name="viewport" content="width=device-width, initial-scale=1">\n'
        "  <title>Owner launch dossier</title>\n"
        f"{OPERATOR_UI_STYLES}\n"
        "</head>\n"
        "<body>\n"
        '  <main id="operator-owner-launch-dossier" data-read-only="true" '
        'data-dry-run-only="true" data-execution-allowed="false" '
        'data-go-live-permitted="false" data-deployment-allowed="false" '
        'data-build-allowed="false" data-artifact-publish-allowed="false" '
        'data-no-execution="true" data-no-go-live="true" '
        'data-no-deployment="true" data-manual-review-only="true" '
        'data-owner-launch-dossier-is-not-go-live="true" '
        'data-dossier-is-not-permission-to-go-live="true" '
        'data-dossier-is-not-execution="true" '
        'data-index-is-not-permission-to-go-live="true" '
        'data-handoff-is-not-go-live="true" data-binder-is-not-go-live="true" '
        'data-runbook-is-not-deployment="true" '
        'data-manifest-is-not-a-build-or-deploy="true" '
        'data-staged-rollout-plan-is-not-go-live="true">\n'
        f"{_render_header(dossier, generated)}\n"
        f"{render_operator_nav('owner-launch-dossier')}\n"
        f"{_render_related_links()}\n"
        f"{_render_live_blocking_flags(dossier)}\n"
        f"{_render_source_references(dossier)}\n"
        f"{_render_included_surfaces(dossier.sources)}\n"
        f"{_render_related_inventory(dossier)}\n"
        f"{_render_local_git(dossier.local_git)}\n"
        f"{_render_settings_preflight(dossier.settings_preflight)}\n"
        f"{_render_operator_audit(dossier.operator_audit)}\n"
        f"{_render_next_actions(dossier.next_actions)}\n"
        f"{_render_footer(dossier, generated)}\n"
        "  </main>\n"
        "</body>\n"
        "</html>\n"
    )


def build_operator_owner_launch_dossier_response(
    db: Session,
    settings: Settings,
    *,
    service: OwnerLaunchDossierService | None = None,
) -> HTMLResponse:
    try:
        builder = service or OwnerLaunchDossierService()
        dossier = builder.build(db, settings)
        html = render_owner_launch_dossier(dossier)
        return HTMLResponse(content=html, status_code=200, headers=NO_STORE_HEADERS)
    except Exception:
        logger.exception("operator_owner_launch_dossier_render_failed", read_only=True)
        return HTMLResponse(
            content=render_owner_launch_dossier_error(),
            status_code=500,
            headers=NO_STORE_HEADERS,
        )


def _render_header(dossier: OwnerLaunchDossier, generated: str) -> str:
    git = dossier.local_git
    git_meta = (
        f" · git {html_escape(git.current_branch)}@{html_escape(git.current_sha)}"
        if git.available
        else " · local git unavailable"
    )
    return (
        '    <header class="page-header">\n'
        "      <div>\n"
        "        <h1>Owner launch dossier</h1>\n"
        '        <p class="lede">Read-only owner/operator review view of the '
        "existing launch dossier. Execution remains disabled. This page does "
        "not build, publish, deploy, apply settings, or lift halt. "
        "OUTBOUND_ENABLED=false. go_live_permitted=false. "
        "execution_allowed=false. deployment_allowed=false. "
        "build_allowed=false. artifact_publish_allowed=false. "
        "owner_launch_dossier_is_not_go_live=true. This page is a launch "
        "dossier review view only, not permission to go live and not an "
        "execution surface.</p>\n"
        "      </div>\n"
        f'      <p class="meta">Generated {generated} · overall '
        f"{html_escape(dossier.overall_status)} · halt "
        f"{html_escape(dossier.operator_halt_status)} · "
        f"{html_escape(dossier.packet_kind)} · {html_escape(dossier.purpose)}"
        f"{git_meta}</p>\n"
        "    </header>"
    )


def _render_related_links() -> str:
    dashboard_href = escape(OPERATOR_DASHBOARD_PATH)
    index_href = escape(OPERATOR_GO_LIVE_READINESS_INDEX_PATH)
    index_json_href = escape(GO_LIVE_READINESS_INDEX_JSON_PATH)
    blockers_href = escape(OPERATOR_LAUNCH_BLOCKERS_PLAN_PATH)
    blockers_json_href = escape(LAUNCH_BLOCKERS_PLAN_JSON_PATH)
    staged_href = escape(OPERATOR_STAGED_ROLLOUT_PLAN_PATH)
    staged_json_href = escape(STAGED_ROLLOUT_PLAN_JSON_PATH)
    dossier_json_href = escape(OWNER_LAUNCH_DOSSIER_JSON_PATH)
    launch_href = escape(LAUNCH_READINESS_JSON_PATH)
    preflight_href = escape(OPERATOR_SETTINGS_EXECUTION_PREFLIGHT_PATH)
    preflight_json_href = escape(SETTINGS_EXECUTION_PREFLIGHT_JSON_PATH)
    handoff_href = escape(OPERATOR_OWNER_HANDOFF_PACKET_PATH)
    handoff_json_href = escape(OWNER_HANDOFF_JSON_PATH)
    binder_href = escape(OPERATOR_COMPLIANCE_EVIDENCE_BINDER_PATH)
    binder_json_href = escape(COMPLIANCE_EVIDENCE_BINDER_JSON_PATH)
    runbook_href = escape(OPERATOR_RELEASE_CANDIDATE_RUNBOOK_PATH)
    runbook_json_href = escape(RELEASE_CANDIDATE_RUNBOOK_JSON_PATH)
    manifest_href = escape(OPERATOR_RELEASE_ARTIFACT_MANIFEST_PATH)
    manifest_json_href = escape(RELEASE_ARTIFACT_MANIFEST_JSON_PATH)
    timeline_href = escape(OPERATOR_AUDIT_TIMELINE_PATH)
    return (
        '    <nav class="filter-nav" aria-label="Linked readiness surfaces">\n'
        f'      <a class="nav-link" href="{dashboard_href}">Dashboard</a>\n'
        f'      <a class="nav-link" href="{index_href}">Go-live index</a>\n'
        f'      <a class="nav-link" href="{index_json_href}">JSON index</a>\n'
        f'      <a class="nav-link" href="{blockers_href}">Launch blockers</a>\n'
        f'      <a class="nav-link" href="{blockers_json_href}">JSON blockers</a>\n'
        f'      <a class="nav-link" href="{staged_href}">Staged rollout</a>\n'
        f'      <a class="nav-link" href="{staged_json_href}">JSON staged plan</a>\n'
        f'      <a class="nav-link" href="{dossier_json_href}">JSON dossier</a>\n'
        f'      <a class="nav-link" href="{launch_href}">Launch readiness JSON</a>\n'
        f'      <a class="nav-link" href="{preflight_href}">Settings preflight</a>\n'
        f'      <a class="nav-link" href="{preflight_json_href}">JSON preflight</a>\n'
        f'      <a class="nav-link" href="{handoff_href}">Owner handoff</a>\n'
        f'      <a class="nav-link" href="{handoff_json_href}">JSON handoff</a>\n'
        f'      <a class="nav-link" href="{binder_href}">Compliance binder</a>\n'
        f'      <a class="nav-link" href="{binder_json_href}">JSON binder</a>\n'
        f'      <a class="nav-link" href="{runbook_href}">Release runbook</a>\n'
        f'      <a class="nav-link" href="{runbook_json_href}">JSON runbook</a>\n'
        f'      <a class="nav-link" href="{manifest_href}">Release manifest</a>\n'
        f'      <a class="nav-link" href="{manifest_json_href}">JSON manifest</a>\n'
        f'      <a class="nav-link" href="{timeline_href}">Audit timeline</a>\n'
        "    </nav>"
    )


def _render_live_blocking_flags(dossier: OwnerLaunchDossier) -> str:
    return (
        '    <section class="status-strip" id="live-blocking-flags" '
        'aria-label="Live-blocking flags">\n'
        f"      {metric('Overall', dossier.overall_status)}\n"
        f"      {metric('OUTBOUND_ENABLED', yes_no(dossier.outbound_enabled))}\n"
        f"      {metric('Operator halt', dossier.operator_halt_status)}\n"
        f"      {metric('Live providers', yes_no(dossier.live_providers_enabled))}\n"
        f"      {metric('Go live permitted', yes_no(dossier.go_live_permitted))}\n"
        f"      {metric('Execution allowed', yes_no(dossier.execution_allowed))}\n"
        f"      {metric('Deployment allowed', yes_no(dossier.deployment_allowed))}\n"
        f"      {metric('Build allowed', yes_no(dossier.build_allowed))}\n"
        f"      {metric('Artifact publish allowed',
            yes_no(dossier.artifact_publish_allowed))}\n"
        f"      {metric('Owner launch dossier is not go-live',
            yes_no(dossier.owner_launch_dossier_is_not_go_live))}\n"
        f"      {metric('Dossier is not permission to go live',
            yes_no(dossier.dossier_is_not_permission_to_go_live))}\n"
        f"      {metric('Dossier is not execution',
            yes_no(dossier.dossier_is_not_execution))}\n"
        "    </section>\n"
        '    <section class="panel" id="dossier-gates">\n'
        "      <h2>Read-only flags and closed defaults</h2>\n"
        '      <div class="metric-grid">\n'
        f"        {metric('Packet kind', dossier.packet_kind)}\n"
        f"        {metric('Purpose', dossier.purpose)}\n"
        f"        {metric('OUTBOUND_ENABLED',
            'false' if not dossier.outbound_enabled else 'true')}\n"
        f"        {metric('Operator halt', dossier.operator_halt_status)}\n"
        f"        {metric('Halt before', dossier.operator_halt_before)}\n"
        f"        {metric('Halt after', dossier.operator_halt_after)}\n"
        f"        {metric('Halt changed', yes_no(dossier.halt_changed))}\n"
        f"        {metric('Live providers enabled',
            yes_no(dossier.live_providers_enabled))}\n"
        f"        {metric('Settings applied', yes_no(dossier.settings_applied))}\n"
        f"        {metric('Owner approved live', yes_no(dossier.owner_approved))}\n"
        f"        {metric('Live action', yes_no(dossier.live_action))}\n"
        f"        {metric('Read only', yes_no(dossier.read_only))}\n"
        f"        {metric('No execution', yes_no(dossier.no_execution))}\n"
        f"        {metric('No go-live', yes_no(dossier.no_go_live))}\n"
        f"        {metric('No deployment', yes_no(dossier.no_deployment))}\n"
        f"        {metric('Executed', dossier.executed)}\n"
        "      </div>\n"
        "      <h3>Blocker codes</h3>\n"
        f"      {_render_codes(dossier.blocker_codes, empty='No blocker codes.')}\n"
        "      <h3>Gate codes</h3>\n"
        f"      {_render_codes(dossier.gate_codes, empty='No gate codes.')}\n"
        "      <h3>Missing credential variable names</h3>\n"
        f"      {_render_codes(dossier.missing_credential_names, empty='None missing.')}\n"
        "      <h3>Closed provider flag names</h3>\n"
        f"      {_render_codes(dossier.closed_provider_flag_names, empty='None closed.')}\n"
        '      <p class="hint">This page never shows secret values, environment '
        "values, API keys, tokens, message bodies, emails, phones, evidence "
        "snippets, or unsafe error text. OUTBOUND_ENABLED=false. "
        "go_live_permitted=false and execution_allowed=false. This is a "
        "read-only launch dossier review view, not permission to go live.</p>\n"
        "    </section>"
    )


def _render_source_references(dossier: OwnerLaunchDossier) -> str:
    rows = "".join(
        (
            _source_row(
                "Go-live readiness index",
                dossier.source_index_command,
                dossier.source_index_route,
                dossier.source_index_overall_status,
                OPERATOR_GO_LIVE_READINESS_INDEX_PATH,
            ),
            _source_row(
                "Launch blockers remediation plan",
                dossier.source_blockers_plan_command,
                dossier.source_blockers_plan_route,
                dossier.source_blockers_plan_overall_status,
                OPERATOR_LAUNCH_BLOCKERS_PLAN_PATH,
            ),
            _source_row(
                "Staged go-live rollout plan",
                dossier.source_staged_rollout_command,
                dossier.source_staged_rollout_route,
                dossier.source_staged_rollout_overall_status,
                OPERATOR_STAGED_ROLLOUT_PLAN_PATH,
            ),
            _source_row(
                "Owner go-live handoff packet",
                dossier.source_handoff_command,
                dossier.source_handoff_route,
                dossier.source_handoff_overall_status,
                OPERATOR_OWNER_HANDOFF_PACKET_PATH,
            ),
            _source_row(
                "Compliance evidence binder",
                dossier.source_binder_command,
                dossier.source_binder_route,
                dossier.source_binder_overall_status,
                OPERATOR_COMPLIANCE_EVIDENCE_BINDER_PATH,
            ),
            _source_row(
                "Release-candidate runbook",
                dossier.source_runbook_command,
                dossier.source_runbook_route,
                dossier.source_runbook_overall_status,
                OPERATOR_RELEASE_CANDIDATE_RUNBOOK_PATH,
            ),
            _source_row(
                "Release artifact manifest",
                dossier.source_manifest_command,
                dossier.source_manifest_route,
                dossier.source_manifest_overall_status,
                OPERATOR_RELEASE_ARTIFACT_MANIFEST_PATH,
            ),
            _source_row(
                "Settings execution preflight",
                dossier.source_preflight_command,
                dossier.source_preflight_route,
                dossier.source_preflight_overall_status,
                OPERATOR_SETTINGS_EXECUTION_PREFLIGHT_PATH,
            ),
            _source_row(
                "Operator audit timeline",
                None,
                None,
                str(dossier.source_audit_matching_count),
                dossier.source_audit_route,
            ),
        )
    )
    return (
        '    <section class="panel" id="source-references">\n'
        "      <h2>Source references</h2>\n"
        '      <p class="hint">This page reuses the existing Phase 47 owner '
        "launch dossier payload. It does not recalculate readiness or "
        "execute.</p>\n"
        '<table class="dense"><thead><tr>'
        "<th>Source</th><th>Command</th><th>JSON route</th><th>Overall status</th>"
        "<th>HTML route</th>"
        f"</tr></thead><tbody>{rows}</tbody></table>\n"
        "    </section>"
    )


def _source_row(
    label: str,
    command: str | None,
    json_route: str | None,
    overall_status: str,
    html_route: str | None,
) -> str:
    json_cell = (
        f'<a class="row-link mono" href="{escape(json_route)}">'
        f"{html_escape(json_route)}</a>"
        if json_route
        else html_escape("—")
    )
    html_cell = (
        f'<a class="row-link mono" href="{escape(html_route)}">'
        f"{html_escape(html_route)}</a>"
        if html_route
        else html_escape("—")
    )
    return (
        f'<tr class="{_status_class(overall_status)}">'
        f"<td>{html_escape(label)}</td>"
        f'<td class="mono">{html_escape(command)}</td>'
        f"<td>{json_cell}</td>"
        f"<td>{html_escape(overall_status)}</td>"
        f"<td>{html_cell}</td>"
        "</tr>"
    )


def _render_included_surfaces(sources: tuple[DossierSourceSurface, ...]) -> str:
    if not sources:
        body = '<p class="empty-state">No included source surfaces.</p>'
    else:
        body = "".join(_render_source_card(source) for source in sources)
    return (
        '    <section class="panel" id="included-surfaces">\n'
        "      <h2>Included source surfaces</h2>\n"
        '      <p class="hint">Each card is a Phase 47 source surface. '
        "Opening a linked page does not execute, apply, build, publish, or "
        "deploy.</p>\n"
        f"{body}"
        "    </section>"
    )


def _render_source_card(source: DossierSourceSurface) -> str:
    html_link = (
        f'<a class="nav-link" href="{escape(source.html_route)}">Open HTML</a>'
        if source.html_route
        else ""
    )
    json_link = (
        f'<a class="nav-link" href="{escape(source.json_route)}">JSON</a>'
        if source.json_route
        else ""
    )
    command = (
        f'<span class="mono">{html_escape(source.command_name)}</span>'
        if source.command_name
        else html_escape("—")
    )
    return (
        f'      <section class="panel" id="surface-{escape(source.key)}">\n'
        f"        <h3>{html_escape(source.label)}</h3>\n"
        '        <p class="hint">'
        f"{html_link} {json_link} Command {command} · status "
        f"{html_escape(source.overall_status)} · purpose "
        f"{html_escape(source.purpose)}</p>\n"
        '        <div class="metric-grid">\n'
        f"          {metric('Read only', yes_no(source.read_only))}\n"
        f"          {metric('No execution', yes_no(source.no_execution))}\n"
        f"          {metric('Go live permitted', yes_no(source.go_live_permitted))}\n"
        f"          {metric('Deployment allowed', yes_no(source.deployment_allowed))}\n"
        "        </div>\n"
        "        <h3>Blocker codes</h3>\n"
        f"        {_render_codes(source.blocker_codes, empty='No blocker codes.')}\n"
        "        <h3>Gate codes</h3>\n"
        f"        {_render_codes(source.gate_codes, empty='No gate codes.')}\n"
        "        <h3>Missing credential variable names</h3>\n"
        f"        {_render_codes(source.missing_credential_names, empty='None missing.')}\n"
        "      </section>\n"
    )


def _render_related_inventory(dossier: OwnerLaunchDossier) -> str:
    return (
        '    <section class="panel" id="related-routes">\n'
        "      <h2>Related safe routes</h2>\n"
        f"      {_render_route_links(dossier.related_routes, empty='No related routes.')}\n"
        "    </section>\n"
        '    <section class="panel" id="related-commands">\n'
        "      <h2>Related CLI commands</h2>\n"
        f"      {_render_codes(dossier.related_commands, empty='No related commands.')}\n"
        "    </section>"
    )


def _render_local_git(git: LocalGitMetadata) -> str:
    return (
        '    <section class="panel" id="local-git">\n'
        "      <h2>Safe local git metadata</h2>\n"
        '      <div class="metric-grid">\n'
        f"        {metric('Available', yes_no(git.available))}\n"
        f"        {metric('Current branch', git.current_branch)}\n"
        f"        {metric('Current SHA', git.current_sha)}\n"
        f"        {metric('Working tree', git.working_tree_status)}\n"
        f"        {metric('Git provider called', yes_no(git.git_provider_called))}\n"
        f"        {metric('GitHub Actions called', yes_no(git.github_actions_called))}\n"
        "      </div>\n"
        '      <p class="hint">Local git metadata is branch name and SHA only. '
        "Remotes, commit messages, author emails, and secret values are never "
        "shown. GitHub Actions are not called.</p>\n"
        "    </section>"
    )


def _render_settings_preflight(summary: DossierSettingsPreflightSummary) -> str:
    return (
        '    <section class="panel" id="settings-preflight">\n'
        "      <h2>Settings execution preflight summary</h2>\n"
        '      <p class="hint">Dry-run counts only. This page does not apply '
        "settings or execute approved requests.</p>\n"
        '      <div class="metric-grid">\n'
        f"        {metric('Overall', summary.overall_status)}\n"
        f"        {metric('Requests', summary.request_count)}\n"
        f"        {metric('Pending decisions', summary.pending_decision_count)}\n"
        f"        {metric('Approved decisions', summary.approved_decision_count)}\n"
        f"        {metric('Blocked', summary.blocked_count)}\n"
        f"        {metric('Executable', summary.executable_count)}\n"
        f"        {metric('No execution', yes_no(summary.no_execution))}\n"
        f"        {metric('Dry-run only', yes_no(summary.dry_run_only))}\n"
        f"        {metric('Executed', summary.executed)}\n"
        f"        {metric('Settings applied', yes_no(summary.settings_applied))}\n"
        f"        {metric('Execution allowed', yes_no(summary.execution_allowed))}\n"
        "      </div>\n"
        "      <h3>Blocker codes</h3>\n"
        f"      {_render_codes(summary.blocker_codes, empty='No blocker codes.')}\n"
        "      <h3>Missing gate codes</h3>\n"
        f"      {_render_codes(summary.missing_gate_codes, empty='No missing gates.')}\n"
        "      <h3>Missing credential variable names</h3>\n"
        f"      {_render_codes(summary.missing_credential_names, empty='None missing.')}\n"
        "      <h3>Closed provider flag names</h3>\n"
        f"      {_render_codes(summary.closed_provider_flag_names, empty='None closed.')}\n"
        "    </section>"
    )


def _render_operator_audit(summary: DossierAuditSummary) -> str:
    return (
        '    <section class="panel" id="operator-audit">\n'
        "      <h2>Operator audit summary</h2>\n"
        '      <p class="hint">Read-only activity counts only. This page does '
        "not execute or change operator halt.</p>\n"
        '      <div class="metric-grid">\n'
        f"        {metric('Matching', summary.matching_count)}\n"
        f"        {metric('Shown', summary.shown_count)}\n"
        f"        {metric('Truncated', yes_no(summary.truncated))}\n"
        f"        {metric('Read only', yes_no(summary.read_only))}\n"
        f"        {metric('No execution', yes_no(summary.no_execution))}\n"
        f"        {metric('Executed', summary.executed)}\n"
        f"        {metric('Halt changed', yes_no(summary.halt_changed))}\n"
        f"        {metric('OUTBOUND_ENABLED', yes_no(summary.outbound_enabled))}\n"
        f"        {metric('Operator halt', summary.operator_halt_status)}\n"
        "      </div>\n"
        "      <h3>Available event types</h3>\n"
        f"      {_render_codes(summary.available_event_types, empty='No event types.')}\n"
        "      <h3>Available sources</h3>\n"
        f"      {_render_codes(summary.available_sources, empty='No sources.')}\n"
        "      <h3>Available statuses</h3>\n"
        f"      {_render_codes(summary.available_statuses, empty='No statuses.')}\n"
        "    </section>"
    )


def _render_next_actions(actions: tuple[DossierNextAction, ...]) -> str:
    if not actions:
        body = '<p class="empty-state">No owner next actions.</p>'
    else:
        rows = "".join(_next_action_row(action) for action in actions)
        body = (
            '<table class="dense"><thead><tr>'
            "<th>Code</th><th>Status</th><th>Command</th><th>Route</th>"
            "<th>Config name</th><th>Label</th>"
            f"</tr></thead><tbody>{rows}</tbody></table>"
        )
    return (
        '    <section class="panel" id="owner-next-actions">\n'
        "      <h2>Non-executable owner next-action summary</h2>\n"
        '      <p class="hint">These labels are review reminders only. They do '
        "not execute, approve, apply, deploy, or lift halt.</p>\n"
        f"      {body}\n"
        "    </section>"
    )


def _next_action_row(action: DossierNextAction) -> str:
    route = action.html_route or action.json_route
    route_cell = (
        f'<a class="row-link mono" href="{escape(route)}">{html_escape(route)}</a>'
        if route
        else html_escape("—")
    )
    return (
        f'<tr class="{_status_class(action.status)}">'
        f'<td class="mono">{html_escape(action.code)}</td>'
        f"<td>{html_escape(action.status)}</td>"
        f'<td class="mono">{html_escape(action.command_name)}</td>'
        f"<td>{route_cell}</td>"
        f'<td class="mono">{html_escape(action.config_name)}</td>'
        f"<td>{html_escape(action.label)}</td>"
        "</tr>"
    )


def _render_footer(dossier: OwnerLaunchDossier, generated: str) -> str:
    return (
        '    <footer class="footnote" id="side-effects">\n'
        f"      <p>Generated {generated}. Read-only={yes_no(dossier.read_only)}. "
        f"Manual review only={yes_no(dossier.manual_review_only)}. "
        f"Dry-run only={yes_no(dossier.dry_run_only)}. "
        f"No execution={yes_no(dossier.no_execution)}. "
        f"No go-live={yes_no(dossier.no_go_live)}. "
        f"No deployment={yes_no(dossier.no_deployment)}. "
        f"Executed={html_escape(dossier.executed)}. "
        f"Settings applied={yes_no(dossier.settings_applied)}. "
        f"Halt changed={yes_no(dossier.halt_changed)}. "
        f"Owner approved={yes_no(dossier.owner_approved)}. "
        f"Live action={yes_no(dossier.live_action)}. "
        f"Execution allowed={yes_no(dossier.execution_allowed)}. "
        f"Go live permitted={yes_no(dossier.go_live_permitted)}. "
        f"Deployment allowed={yes_no(dossier.deployment_allowed)}. "
        f"Build allowed={yes_no(dossier.build_allowed)}. "
        f"Artifact publish allowed={yes_no(dossier.artifact_publish_allowed)}. "
        f"Owner launch dossier is not go-live="
        f"{yes_no(dossier.owner_launch_dossier_is_not_go_live)}. "
        f"Dossier is not permission to go live="
        f"{yes_no(dossier.dossier_is_not_permission_to_go_live)}. "
        f"Dossier is not execution={yes_no(dossier.dossier_is_not_execution)}. "
        "There are no apply, execute, lift-halt, enable-outbound, provider, "
        "build, publish, deploy, campaign, booking, call, or spend controls on "
        "this page. This is a read-only launch dossier review view, not "
        "permission to go live and not an execution surface. Current route "
        f"{html_escape(OPERATOR_OWNER_LAUNCH_DOSSIER_PATH)}.</p>\n"
        "    </footer>"
    )


def _render_codes(codes: tuple[str, ...] | list[str], *, empty: str) -> str:
    unique = [code for code in dict.fromkeys(codes) if code]
    if not unique:
        return f'<p class="empty-state">{escape(empty)}</p>'
    rows = "".join(f'<li class="mono">{html_escape(code)}</li>' for code in unique)
    return f'<ul class="plain">{rows}</ul>'


def _render_route_links(routes: tuple[str, ...] | list[str], *, empty: str) -> str:
    unique = [route for route in dict.fromkeys(routes) if route]
    if not unique:
        return f'<p class="empty-state">{escape(empty)}</p>'
    rows = "".join(
        f'<li class="mono"><a class="row-link" href="{escape(route)}">'
        f"{html_escape(route)}</a></li>"
        for route in unique
    )
    return f'<ul class="plain">{rows}</ul>'


def _status_class(status: str) -> str:
    match status:
        case FindingSeverity.BLOCKED.value | "closed" | "missing":
            return "severity-blocked"
        case FindingSeverity.WARNING.value:
            return "severity-warning"
        case FindingSeverity.INFO.value | "ready_for_owner_review" | "open":
            return "severity-info"
        case _:
            return "severity-info"
