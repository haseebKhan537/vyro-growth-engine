"""Read-only operator provider setup checklist HTML shell.

Phase 50 renders a sanitized view of the existing Phase 49 provider
credential/setup checklist. It reuses ProviderSetupChecklistService and
never recalculates readiness. It never executes, builds, publishes,
deploys, applies settings, lifts halt, enables outbound, calls providers,
or changes live state. This page is a provider setup review view only,
not permission to go live and not an execution surface.
"""

from __future__ import annotations

from html import escape

import structlog
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from vyro_growth.api.operator_ui import (
    COMPLIANCE_EVIDENCE_BINDER_JSON_PATH,
    GO_LIVE_READINESS_INDEX_JSON_PATH,
    GO_LIVE_REHEARSAL_CHECKLIST_JSON_PATH,
    LAUNCH_BLOCKERS_PLAN_JSON_PATH,
    LAUNCH_READINESS_JSON_PATH,
    NO_STORE_HEADERS,
    OPERATOR_AUDIT_TIMELINE_PATH,
    OPERATOR_COMPLIANCE_EVIDENCE_BINDER_PATH,
    OPERATOR_DASHBOARD_PATH,
    OPERATOR_GO_LIVE_READINESS_INDEX_PATH,
    OPERATOR_GO_LIVE_REHEARSAL_CHECKLIST_PATH,
    OPERATOR_LAUNCH_BLOCKERS_PLAN_PATH,
    OPERATOR_OWNER_HANDOFF_PACKET_PATH,
    OPERATOR_OWNER_LAUNCH_DOSSIER_PATH,
    OPERATOR_PROVIDER_SETUP_CHECKLIST_PATH,
    OPERATOR_REHEARSAL_OUTCOME_REPORT_PATH,
    OPERATOR_RELEASE_ARTIFACT_MANIFEST_PATH,
    OPERATOR_RELEASE_CANDIDATE_RUNBOOK_PATH,
    OPERATOR_SETTINGS_EXECUTION_PREFLIGHT_PATH,
    OPERATOR_STAGED_ROLLOUT_PLAN_PATH,
    OPERATOR_UI_STYLES,
    OWNER_HANDOFF_JSON_PATH,
    OWNER_LAUNCH_DOSSIER_JSON_PATH,
    PROVIDER_SETUP_CHECKLIST_JSON_PATH,
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
from vyro_growth.services.provider_setup_checklist import (
    LocalVerificationGate,
    ProviderCredentialStatus,
    ProviderFlagState,
    ProviderSetupCategory,
    ProviderSetupChecklist,
    ProviderSetupChecklistService,
    ProviderSetupNextAction,
)
from vyro_growth.services.release_artifact_manifest import LocalGitMetadata

logger = structlog.get_logger(__name__)


def render_provider_setup_checklist_error() -> str:
    return render_failure_page(
        page_id="operator-provider-setup-checklist-error",
        title="Provider setup checklist unavailable",
        heading="Read-only provider setup checklist unavailable",
        banner="Unable to load the provider setup checklist.",
        detail=(
            "The sanitized provider-setup review view could not be rendered. "
            "Retry after checking database connectivity and runtime config. "
            "This page is a provider setup review view only, not permission "
            "to go live and not an execution surface."
        ),
    )


def render_provider_setup_checklist(checklist: ProviderSetupChecklist) -> str:
    generated = html_escape(format_dt(checklist.generated_at))
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '  <meta charset="utf-8">\n'
        '  <meta name="viewport" content="width=device-width, initial-scale=1">\n'
        "  <title>Provider setup checklist</title>\n"
        f"{OPERATOR_UI_STYLES}\n"
        "</head>\n"
        "<body>\n"
        '  <main id="operator-provider-setup-checklist" data-read-only="true" '
        'data-dry-run-only="true" data-execution-allowed="false" '
        'data-go-live-permitted="false" data-deployment-allowed="false" '
        'data-build-allowed="false" data-artifact-publish-allowed="false" '
        'data-no-execution="true" data-no-go-live="true" '
        'data-no-deployment="true" data-manual-review-only="true" '
        'data-provider-setup-checklist-is-not-go-live="true" '
        'data-checklist-is-not-permission-to-go-live="true" '
        'data-checklist-is-not-execution="true" '
        'data-index-is-not-permission-to-go-live="true" '
        'data-dossier-is-not-permission-to-go-live="true" '
        'data-staged-rollout-plan-is-not-go-live="true" '
        'data-runbook-is-not-deployment="true">\n'
        f"{_render_header(checklist, generated)}\n"
        f"{render_operator_nav('provider-setup-checklist')}\n"
        f"{_render_related_links()}\n"
        f"{_render_live_blocking_flags(checklist)}\n"
        f"{_render_source_references(checklist)}\n"
        f"{_render_categories(checklist.categories)}\n"
        f"{_render_related_inventory(checklist)}\n"
        f"{_render_local_git(checklist.local_git)}\n"
        f"{_render_verification_gates(checklist.local_verification_gates)}\n"
        f"{_render_next_actions(checklist.next_actions)}\n"
        f"{_render_footer(checklist, generated)}\n"
        "  </main>\n"
        "</body>\n"
        "</html>\n"
    )


def build_operator_provider_setup_checklist_response(
    db: Session,
    settings: Settings,
    *,
    service: ProviderSetupChecklistService | None = None,
) -> HTMLResponse:
    try:
        builder = service or ProviderSetupChecklistService()
        checklist = builder.build(db, settings)
        html = render_provider_setup_checklist(checklist)
        return HTMLResponse(content=html, status_code=200, headers=NO_STORE_HEADERS)
    except Exception:
        logger.exception("operator_provider_setup_checklist_render_failed", read_only=True)
        return HTMLResponse(
            content=render_provider_setup_checklist_error(),
            status_code=500,
            headers=NO_STORE_HEADERS,
        )


def _render_header(checklist: ProviderSetupChecklist, generated: str) -> str:
    git = checklist.local_git
    git_meta = (
        f" · git {html_escape(git.current_branch)}@{html_escape(git.current_sha)}"
        if git.available
        else " · local git unavailable"
    )
    return (
        '    <header class="page-header">\n'
        "      <div>\n"
        "        <h1>Provider setup checklist</h1>\n"
        '        <p class="lede">Read-only owner/operator review view of the '
        "existing provider credential/setup checklist. Execution remains "
        "disabled. This page does not build, publish, deploy, apply "
        "settings, or lift halt. OUTBOUND_ENABLED=false. "
        "go_live_permitted=false. execution_allowed=false. "
        "deployment_allowed=false. build_allowed=false. "
        "artifact_publish_allowed=false. "
        "provider_setup_checklist_is_not_go_live=true. This page is a "
        "provider setup review view only, not permission to go live and "
        "not an execution surface.</p>\n"
        "      </div>\n"
        f'      <p class="meta">Generated {generated} · overall '
        f"{html_escape(checklist.overall_status)} · halt "
        f"{html_escape(checklist.operator_halt_status)} · "
        f"{html_escape(checklist.packet_kind)} · {html_escape(checklist.purpose)}"
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
    dossier_href = escape(OPERATOR_OWNER_LAUNCH_DOSSIER_PATH)
    dossier_json_href = escape(OWNER_LAUNCH_DOSSIER_JSON_PATH)
    checklist_json_href = escape(PROVIDER_SETUP_CHECKLIST_JSON_PATH)
    rehearsal_href = escape(OPERATOR_GO_LIVE_REHEARSAL_CHECKLIST_PATH)
    outcome_href = escape(OPERATOR_REHEARSAL_OUTCOME_REPORT_PATH)
    rehearsal_json_href = escape(GO_LIVE_REHEARSAL_CHECKLIST_JSON_PATH)
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
        f'      <a class="nav-link" href="{dossier_href}">Owner launch dossier</a>\n'
        f'      <a class="nav-link" href="{dossier_json_href}">JSON dossier</a>\n'
        f'      <a class="nav-link" href="{checklist_json_href}">JSON checklist</a>\n'
        f'      <a class="nav-link" href="{rehearsal_href}">Go-live rehearsal</a>\n'
        f'      <a class="nav-link" href="{outcome_href}">Rehearsal outcome</a>\n'
        f'      <a class="nav-link" href="{rehearsal_json_href}">JSON rehearsal</a>\n'
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


def _render_live_blocking_flags(checklist: ProviderSetupChecklist) -> str:
    return (
        '    <section class="status-strip" id="live-blocking-flags" '
        'aria-label="Live-blocking flags">\n'
        f"      {metric('Overall', checklist.overall_status)}\n"
        f"      {metric('OUTBOUND_ENABLED', yes_no(checklist.outbound_enabled))}\n"
        f"      {metric('Operator halt', checklist.operator_halt_status)}\n"
        f"      {metric('Live providers', yes_no(checklist.live_providers_enabled))}\n"
        f"      {metric('Go live permitted', yes_no(checklist.go_live_permitted))}\n"
        f"      {metric('Execution allowed', yes_no(checklist.execution_allowed))}\n"
        f"      {metric('Deployment allowed', yes_no(checklist.deployment_allowed))}\n"
        f"      {metric('Build allowed', yes_no(checklist.build_allowed))}\n"
        f"      {metric('Artifact publish allowed',
            yes_no(checklist.artifact_publish_allowed))}\n"
        f"      {metric('Provider setup checklist is not go-live',
            yes_no(checklist.provider_setup_checklist_is_not_go_live))}\n"
        f"      {metric('Checklist is not permission to go live',
            yes_no(checklist.checklist_is_not_permission_to_go_live))}\n"
        f"      {metric('Checklist is not execution',
            yes_no(checklist.checklist_is_not_execution))}\n"
        "    </section>\n"
        '    <section class="panel" id="checklist-gates">\n'
        "      <h2>Read-only flags and closed defaults</h2>\n"
        '      <div class="metric-grid">\n'
        f"        {metric('Packet kind', checklist.packet_kind)}\n"
        f"        {metric('Purpose', checklist.purpose)}\n"
        f"        {metric('OUTBOUND_ENABLED',
            'false' if not checklist.outbound_enabled else 'true')}\n"
        f"        {metric('Operator halt', checklist.operator_halt_status)}\n"
        f"        {metric('Halt before', checklist.operator_halt_before)}\n"
        f"        {metric('Halt after', checklist.operator_halt_after)}\n"
        f"        {metric('Halt changed', yes_no(checklist.halt_changed))}\n"
        f"        {metric('Live providers enabled',
            yes_no(checklist.live_providers_enabled))}\n"
        f"        {metric('Settings applied', yes_no(checklist.settings_applied))}\n"
        f"        {metric('Owner approved live', yes_no(checklist.owner_approved))}\n"
        f"        {metric('Live action', yes_no(checklist.live_action))}\n"
        f"        {metric('Read only', yes_no(checklist.read_only))}\n"
        f"        {metric('No execution', yes_no(checklist.no_execution))}\n"
        f"        {metric('No go-live', yes_no(checklist.no_go_live))}\n"
        f"        {metric('No deployment', yes_no(checklist.no_deployment))}\n"
        f"        {metric('Executed', checklist.executed)}\n"
        "      </div>\n"
        "      <h3>Blocker codes</h3>\n"
        f"      {_render_codes(checklist.blocker_codes, empty='No blocker codes.')}\n"
        "      <h3>Gate codes</h3>\n"
        f"      {_render_codes(checklist.gate_codes, empty='No gate codes.')}\n"
        "      <h3>Missing credential variable names</h3>\n"
        f"      {_render_codes(checklist.missing_credential_names, empty='None missing.')}\n"
        "      <h3>Closed provider flag names</h3>\n"
        f"      {_render_codes(checklist.closed_provider_flag_names, empty='None closed.')}\n"
        '      <p class="hint">This page never shows secret values, environment '
        "values, API keys, tokens, message bodies, emails, phones, evidence "
        "snippets, or unsafe error text. OUTBOUND_ENABLED=false. "
        "go_live_permitted=false and execution_allowed=false. This is a "
        "read-only provider setup review view, not permission to go live.</p>\n"
        "    </section>"
    )


def _render_source_references(checklist: ProviderSetupChecklist) -> str:
    rows = "".join(
        (
            _source_row(
                "Launch readiness",
                checklist.source_launch_readiness_command,
                checklist.source_launch_readiness_route,
                checklist.source_launch_readiness_overall_status,
                LAUNCH_READINESS_JSON_PATH,
            ),
            _source_row(
                "Go-live readiness index",
                checklist.source_index_command,
                checklist.source_index_route,
                checklist.source_index_overall_status,
                OPERATOR_GO_LIVE_READINESS_INDEX_PATH,
            ),
            _source_row(
                "Launch blockers remediation plan",
                checklist.source_blockers_plan_command,
                checklist.source_blockers_plan_route,
                checklist.source_blockers_plan_overall_status,
                OPERATOR_LAUNCH_BLOCKERS_PLAN_PATH,
            ),
            _source_row(
                "Staged go-live rollout plan",
                checklist.source_staged_rollout_command,
                checklist.source_staged_rollout_route,
                checklist.source_staged_rollout_overall_status,
                OPERATOR_STAGED_ROLLOUT_PLAN_PATH,
            ),
            _source_row(
                "Owner launch dossier",
                checklist.source_dossier_command,
                checklist.source_dossier_route,
                checklist.source_dossier_overall_status,
                OPERATOR_OWNER_LAUNCH_DOSSIER_PATH,
            ),
            _source_row(
                "Settings execution preflight",
                checklist.source_preflight_command,
                checklist.source_preflight_route,
                checklist.source_preflight_overall_status,
                OPERATOR_SETTINGS_EXECUTION_PREFLIGHT_PATH,
            ),
            _source_row(
                "Release-candidate runbook",
                checklist.source_runbook_command,
                checklist.source_runbook_route,
                checklist.source_runbook_overall_status,
                OPERATOR_RELEASE_CANDIDATE_RUNBOOK_PATH,
            ),
        )
    )
    return (
        '    <section class="panel" id="source-references">\n'
        "      <h2>Source references</h2>\n"
        '      <p class="hint">This page reuses the existing Phase 49 '
        "provider setup checklist payload. It does not recalculate "
        "readiness or execute.</p>\n"
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


def _render_categories(categories: tuple[ProviderSetupCategory, ...]) -> str:
    if not categories:
        body = '<p class="empty-state">No provider setup categories.</p>'
    else:
        body = "".join(_render_category_card(category) for category in categories)
    return (
        '    <section class="panel" id="provider-setup-categories">\n'
        "      <h2>Provider setup categories</h2>\n"
        '      <p class="hint">Each card is a Phase 49 provider setup '
        "category. Opening a linked page does not execute, apply, build, "
        "publish, or deploy. Credential names and flag names are shown; "
        "values are never shown.</p>\n"
        f"{body}"
        "    </section>"
    )


def _render_category_card(category: ProviderSetupCategory) -> str:
    return (
        f'      <section class="panel" id="category-{escape(category.key)}">\n'
        f"        <h3>{html_escape(category.label)}</h3>\n"
        '        <p class="hint">Required owner approval type '
        f"{html_escape(category.required_owner_approval_type)} · status "
        f"{html_escape(category.overall_status)} · "
        f"{html_escape(category.preparation_label)}</p>\n"
        '        <div class="metric-grid">\n'
        f"          {metric('Key', category.key)}\n"
        f"          {metric('Approval type', category.required_owner_approval_type)}\n"
        f"          {metric('Read only', yes_no(category.read_only))}\n"
        f"          {metric('No execution', yes_no(category.no_execution))}\n"
        f"          {metric('Go live permitted', yes_no(category.go_live_permitted))}\n"
        f"          {metric('Deployment allowed', yes_no(category.deployment_allowed))}\n"
        "        </div>\n"
        "        <h3>Config names</h3>\n"
        f"        {_render_codes(category.config_names, empty='No config names.')}\n"
        "        <h3>Missing credential variable names</h3>\n"
        f"        {_render_codes(category.missing_credential_names, empty='None missing.')}\n"
        "        <h3>Closed provider flag names</h3>\n"
        f"        {_render_codes(category.closed_provider_flag_names, empty='None closed.')}\n"
        "        <h3>Credential statuses</h3>\n"
        f"        {_render_credential_statuses(category.credential_statuses)}\n"
        "        <h3>Flag states</h3>\n"
        f"        {_render_flag_states(category.flag_states)}\n"
        "        <h3>Blocker codes</h3>\n"
        f"        {_render_codes(category.blocker_codes, empty='No blocker codes.')}\n"
        "        <h3>Gate codes</h3>\n"
        f"        {_render_codes(category.gate_codes, empty='No gate codes.')}\n"
        "        <h3>Related commands</h3>\n"
        f"        {_render_codes(category.related_commands, empty='No related commands.')}\n"
        "        <h3>Related routes</h3>\n"
        f"        {_render_route_links(category.related_routes, empty='No related routes.')}\n"
        "      </section>\n"
    )


def _render_credential_statuses(
    statuses: tuple[ProviderCredentialStatus, ...],
) -> str:
    if not statuses:
        return '<p class="empty-state">No credential statuses.</p>'
    rows = "".join(
        (
            f'<tr class="{_status_class(item.status)}">'
            f'<td class="mono">{html_escape(item.name)}</td>'
            f"<td>{yes_no(item.present)}</td>"
            f"<td>{html_escape(item.status)}</td>"
            f"<td>{yes_no(item.required)}</td>"
            "</tr>"
        )
        for item in statuses
    )
    return (
        '<table class="dense"><thead><tr>'
        "<th>Name</th><th>Present</th><th>Status</th><th>Required</th>"
        f"</tr></thead><tbody>{rows}</tbody></table>"
    )


def _render_flag_states(flags: tuple[ProviderFlagState, ...]) -> str:
    if not flags:
        return '<p class="empty-state">No flag states.</p>'
    rows = "".join(
        (
            f'<tr class="{_status_class("closed" if not item.enabled else "open")}">'
            f'<td class="mono">{html_escape(item.name)}</td>'
            f"<td>{yes_no(item.enabled)}</td>"
            "</tr>"
        )
        for item in flags
    )
    return (
        '<table class="dense"><thead><tr>'
        "<th>Name</th><th>Enabled</th>"
        f"</tr></thead><tbody>{rows}</tbody></table>"
    )


def _render_related_inventory(checklist: ProviderSetupChecklist) -> str:
    return (
        '    <section class="panel" id="related-routes">\n'
        "      <h2>Related safe routes</h2>\n"
        f"      {_render_route_links(checklist.related_routes, empty='No related routes.')}\n"
        "    </section>\n"
        '    <section class="panel" id="related-commands">\n'
        "      <h2>Related CLI commands</h2>\n"
        f"      {_render_codes(checklist.related_commands, empty='No related commands.')}\n"
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


def _render_verification_gates(gates: tuple[LocalVerificationGate, ...]) -> str:
    if not gates:
        body = '<p class="empty-state">No local verification gates.</p>'
    else:
        rows = "".join(_verification_gate_row(gate) for gate in gates)
        body = (
            '<table class="dense"><thead><tr>'
            "<th>Code</th><th>Status</th><th>Command</th><th>Route</th>"
            "<th>Label</th>"
            f"</tr></thead><tbody>{rows}</tbody></table>"
        )
    return (
        '    <section class="panel" id="local-verification-gates">\n'
        "      <h2>Local verification gates</h2>\n"
        '      <p class="hint">These gates are review reminders only. This '
        "page does not run CI, call GitHub Actions, or change live flags.</p>\n"
        f"      {body}\n"
        "    </section>"
    )


def _verification_gate_row(gate: LocalVerificationGate) -> str:
    route_cell = (
        f'<a class="row-link mono" href="{escape(gate.json_route)}">'
        f"{html_escape(gate.json_route)}</a>"
        if gate.json_route
        else html_escape("—")
    )
    return (
        f'<tr class="{_status_class(gate.status)}">'
        f'<td class="mono">{html_escape(gate.code)}</td>'
        f"<td>{html_escape(gate.status)}</td>"
        f'<td class="mono">{html_escape(gate.command_name)}</td>'
        f"<td>{route_cell}</td>"
        f"<td>{html_escape(gate.label)}</td>"
        "</tr>"
    )


def _render_next_actions(actions: tuple[ProviderSetupNextAction, ...]) -> str:
    if not actions:
        body = '<p class="empty-state">No owner preparation steps.</p>'
    else:
        rows = "".join(_next_action_row(action) for action in actions)
        body = (
            '<table class="dense"><thead><tr>'
            "<th>Code</th><th>Status</th><th>Command</th><th>Route</th>"
            "<th>Config name</th><th>Label</th>"
            f"</tr></thead><tbody>{rows}</tbody></table>"
        )
    return (
        '    <section class="panel" id="owner-preparation-steps">\n'
        "      <h2>Non-executable owner preparation steps</h2>\n"
        '      <p class="hint">These labels are review reminders only. They do '
        "not execute, approve, apply, deploy, or lift halt.</p>\n"
        f"      {body}\n"
        "    </section>"
    )


def _next_action_row(action: ProviderSetupNextAction) -> str:
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


def _render_footer(checklist: ProviderSetupChecklist, generated: str) -> str:
    return (
        '    <footer class="footnote" id="side-effects">\n'
        f"      <p>Generated {generated}. Read-only={yes_no(checklist.read_only)}. "
        f"Manual review only={yes_no(checklist.manual_review_only)}. "
        f"Dry-run only={yes_no(checklist.dry_run_only)}. "
        f"No execution={yes_no(checklist.no_execution)}. "
        f"No go-live={yes_no(checklist.no_go_live)}. "
        f"No deployment={yes_no(checklist.no_deployment)}. "
        f"Executed={html_escape(checklist.executed)}. "
        f"Settings applied={yes_no(checklist.settings_applied)}. "
        f"Halt changed={yes_no(checklist.halt_changed)}. "
        f"Owner approved={yes_no(checklist.owner_approved)}. "
        f"Live action={yes_no(checklist.live_action)}. "
        f"Execution allowed={yes_no(checklist.execution_allowed)}. "
        f"Go live permitted={yes_no(checklist.go_live_permitted)}. "
        f"Deployment allowed={yes_no(checklist.deployment_allowed)}. "
        f"Build allowed={yes_no(checklist.build_allowed)}. "
        f"Artifact publish allowed={yes_no(checklist.artifact_publish_allowed)}. "
        f"Provider setup checklist is not go-live="
        f"{yes_no(checklist.provider_setup_checklist_is_not_go_live)}. "
        f"Checklist is not permission to go live="
        f"{yes_no(checklist.checklist_is_not_permission_to_go_live)}. "
        f"Checklist is not execution={yes_no(checklist.checklist_is_not_execution)}. "
        "There are no apply, execute, lift-halt, enable-outbound, provider, "
        "build, publish, deploy, campaign, booking, call, or spend controls on "
        "this page. This is a read-only provider setup review view, not "
        "permission to go live and not an execution surface. Current route "
        f"{html_escape(OPERATOR_PROVIDER_SETUP_CHECKLIST_PATH)}.</p>\n"
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
