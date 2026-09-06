"""Read-only operator go-live readiness index HTML shell.

Phase 41 renders a sanitized index of existing owner/operator readiness,
evidence, runbook, manifest, and audit surfaces. It never executes, builds,
publishes, deploys, applies settings, lifts halt, enables outbound, calls
providers, or changes live state. This page is an index/review view only,
not permission to go live and not an execution surface.
"""

from __future__ import annotations

from html import escape
from typing import Never

import structlog
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from vyro_growth.api.operator_ui import (
    COMPLIANCE_EVIDENCE_BINDER_JSON_PATH,
    GO_LIVE_READINESS_INDEX_JSON_PATH,
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
    OPERATOR_SUPERVISED_PILOT_PLAN_PATH,
    OPERATOR_UI_STYLES,
    OWNER_HANDOFF_JSON_PATH,
    RELEASE_ARTIFACT_MANIFEST_JSON_PATH,
    RELEASE_CANDIDATE_RUNBOOK_JSON_PATH,
    SETTINGS_EXECUTION_PREFLIGHT_JSON_PATH,
    format_dt,
    html_escape,
    metric,
    render_failure_page,
    render_operator_nav,
    titleize,
    yes_no,
)
from vyro_growth.config import Settings
from vyro_growth.domain import FindingSeverity
from vyro_growth.services.go_live_readiness_index import (
    GoLiveReadinessIndex,
    GoLiveReadinessIndexService,
    IndexChecklistItem,
    ReadinessSurfaceCard,
)

logger = structlog.get_logger(__name__)


def render_go_live_readiness_index_error() -> str:
    return render_failure_page(
        page_id="operator-go-live-readiness-index-error",
        title="Go-live readiness index unavailable",
        heading="Read-only go-live readiness index unavailable",
        banner="Unable to load the go-live readiness index.",
        detail=(
            "The sanitized owner-review index could not be rendered. "
            "Retry after checking database connectivity and runtime config. "
            "This page is an index/review view only, not permission to go live "
            "and not an execution surface."
        ),
    )


def render_go_live_readiness_index(index: GoLiveReadinessIndex) -> str:
    generated = html_escape(format_dt(index.generated_at))
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '  <meta charset="utf-8">\n'
        '  <meta name="viewport" content="width=device-width, initial-scale=1">\n'
        "  <title>Go-live readiness index</title>\n"
        f"{OPERATOR_UI_STYLES}\n"
        "</head>\n"
        "<body>\n"
        '  <main id="operator-go-live-readiness-index" data-read-only="true" '
        'data-dry-run-only="true" data-execution-allowed="false" '
        'data-go-live-permitted="false" data-deployment-allowed="false" '
        'data-build-allowed="false" data-artifact-publish-allowed="false" '
        'data-no-execution="true" data-manual-review-only="true" '
        'data-index-is-not-permission-to-go-live="true" '
        'data-handoff-is-not-go-live="true" data-binder-is-not-go-live="true" '
        'data-runbook-is-not-deployment="true" '
        'data-manifest-is-not-a-build-or-deploy="true">\n'
        f"{_render_header(index, generated)}\n"
        f"{render_operator_nav('go-live-readiness-index')}\n"
        f"{_render_related_links()}\n"
        f"{_render_live_blocking_flags(index)}\n"
        f"{_render_surfaces(index.surfaces)}\n"
        f"{_render_checklist(index.remaining_manual_owner_checklist)}\n"
        f"{_render_footer(index, generated)}\n"
        "  </main>\n"
        "</body>\n"
        "</html>\n"
    )


def build_operator_go_live_readiness_index_response(
    db: Session,
    settings: Settings,
    *,
    service: GoLiveReadinessIndexService | None = None,
) -> HTMLResponse:
    try:
        builder = service or GoLiveReadinessIndexService()
        index = builder.build(db, settings)
        html = render_go_live_readiness_index(index)
        return HTMLResponse(content=html, status_code=200, headers=NO_STORE_HEADERS)
    except Exception:
        logger.exception("operator_go_live_readiness_index_render_failed", read_only=True)
        return HTMLResponse(
            content=render_go_live_readiness_index_error(),
            status_code=500,
            headers=NO_STORE_HEADERS,
        )


def _render_header(index: GoLiveReadinessIndex, generated: str) -> str:
    git = index.local_git
    git_meta = (
        f" · git {html_escape(git.current_branch)}@{html_escape(git.current_sha)}"
        if git.available
        else " · local git unavailable"
    )
    return (
        '    <header class="page-header">\n'
        "      <div>\n"
        "        <h1>Go-live readiness index</h1>\n"
        '        <p class="lede">Read-only owner/operator index of existing '
        "readiness, evidence, runbook, manifest, and audit surfaces. Execution "
        "remains disabled. This page does not build, publish, deploy, apply "
        "settings, or lift halt. OUTBOUND_ENABLED=false. "
        "go_live_permitted=false. execution_allowed=false. "
        "deployment_allowed=false. build_allowed=false. "
        "artifact_publish_allowed=false. This page is an index/review view "
        "only, not permission to go live and not an execution surface.</p>\n"
        "      </div>\n"
        f'      <p class="meta">Generated {generated} · overall '
        f"{html_escape(index.overall_status)} · halt "
        f"{html_escape(index.operator_halt_status)} · "
        f"{html_escape(index.packet_kind)} · {html_escape(index.purpose)}"
        f"{git_meta}</p>\n"
        "    </header>"
    )


def _render_related_links() -> str:
    dashboard_href = escape(OPERATOR_DASHBOARD_PATH)
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
    index_json_href = escape(GO_LIVE_READINESS_INDEX_JSON_PATH)
    plan_href = escape(OPERATOR_LAUNCH_BLOCKERS_PLAN_PATH)
    staged_href = escape(OPERATOR_STAGED_ROLLOUT_PLAN_PATH)
    dossier_href = escape(OPERATOR_OWNER_LAUNCH_DOSSIER_PATH)
    checklist_href = escape(OPERATOR_PROVIDER_SETUP_CHECKLIST_PATH)
    rehearsal_href = escape(OPERATOR_GO_LIVE_REHEARSAL_CHECKLIST_PATH)
    outcome_href = escape(OPERATOR_REHEARSAL_OUTCOME_REPORT_PATH)
    pilot_href = escape(OPERATOR_SUPERVISED_PILOT_PLAN_PATH)
    timeline_href = escape(OPERATOR_AUDIT_TIMELINE_PATH)
    return (
        '    <nav class="filter-nav" aria-label="Linked readiness surfaces">\n'
        f'      <a class="nav-link" href="{dashboard_href}">Dashboard</a>\n'
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
        f'      <a class="nav-link" href="{index_json_href}">JSON index</a>\n'
        f'      <a class="nav-link" href="{plan_href}">Launch blockers</a>\n'
        f'      <a class="nav-link" href="{staged_href}">Staged rollout</a>\n'
        f'      <a class="nav-link" href="{dossier_href}">Owner launch dossier</a>\n'
        f'      <a class="nav-link" href="{checklist_href}">Provider setup</a>\n'
        f'      <a class="nav-link" href="{rehearsal_href}">Go-live rehearsal</a>\n'
        f'      <a class="nav-link" href="{outcome_href}">Rehearsal outcome</a>\n'
        f'      <a class="nav-link" href="{pilot_href}">Supervised pilot</a>\n'
        f'      <a class="nav-link" href="{timeline_href}">Audit timeline</a>\n'
        "    </nav>"
    )


def _render_live_blocking_flags(index: GoLiveReadinessIndex) -> str:
    return (
        '    <section class="status-strip" id="live-blocking-flags" '
        'aria-label="Live-blocking flags">\n'
        f"      {metric('Overall', index.overall_status)}\n"
        f"      {metric('OUTBOUND_ENABLED', yes_no(index.outbound_enabled))}\n"
        f"      {metric('Operator halt', index.operator_halt_status)}\n"
        f"      {metric('Live providers', yes_no(index.live_providers_enabled))}\n"
        f"      {metric('Go live permitted', yes_no(index.go_live_permitted))}\n"
        f"      {metric('Execution allowed', yes_no(index.execution_allowed))}\n"
        f"      {metric('Deployment allowed', yes_no(index.deployment_allowed))}\n"
        f"      {metric('Build allowed', yes_no(index.build_allowed))}\n"
        f"      {metric('Artifact publish allowed',
            yes_no(index.artifact_publish_allowed))}\n"
        f"      {metric('Handoff is not go-live', yes_no(index.handoff_is_not_go_live))}\n"
        f"      {metric('Binder is not go-live', yes_no(index.binder_is_not_go_live))}\n"
        f"      {metric('Runbook is not deployment',
            yes_no(index.runbook_is_not_deployment))}\n"
        f"      {metric('Manifest is not a build or deploy',
            yes_no(index.manifest_is_not_a_build_or_deploy))}\n"
        f"      {metric('Index is not permission to go live',
            yes_no(index.index_is_not_permission_to_go_live))}\n"
        "    </section>\n"
        '    <section class="panel" id="index-gates">\n'
        "      <h2>Live-blocking flags and closed defaults</h2>\n"
        '      <div class="metric-grid">\n'
        f"        {metric('OUTBOUND_ENABLED', 'false' if not index.outbound_enabled else 'true')}\n"
        f"        {metric('Operator halt', index.operator_halt_status)}\n"
        f"        {metric('Halt before', index.operator_halt_before)}\n"
        f"        {metric('Halt after', index.operator_halt_after)}\n"
        f"        {metric('Halt changed', yes_no(index.halt_changed))}\n"
        f"        {metric('Live providers enabled', yes_no(index.live_providers_enabled))}\n"
        f"        {metric('Settings applied', yes_no(index.settings_applied))}\n"
        f"        {metric('Owner approved live', yes_no(index.owner_approved))}\n"
        f"        {metric('Live action', yes_no(index.live_action))}\n"
        f"        {metric('Read only', yes_no(index.read_only))}\n"
        f"        {metric('No execution', yes_no(index.no_execution))}\n"
        f"        {metric('Executed', index.executed)}\n"
        "      </div>\n"
        "      <h3>Blocker codes</h3>\n"
        f"      {_render_codes(index.blocker_codes, empty='No blocker codes.')}\n"
        "      <h3>Missing credential variable names</h3>\n"
        f"      {_render_codes(index.missing_credential_names, empty='None missing.')}\n"
        "      <h3>Closed provider flag names</h3>\n"
        f"      {_render_codes(index.closed_provider_flag_names, empty='None closed.')}\n"
        '      <p class="hint">This page never shows secret values, environment '
        "values, API keys, tokens, message bodies, emails, phones, evidence "
        "snippets, or unsafe error text. OUTBOUND_ENABLED=false. "
        "go_live_permitted=false and execution_allowed=false. This is a "
        "read-only index/review view, not permission to go live.</p>\n"
        "    </section>"
    )


def _render_surfaces(surfaces: tuple[ReadinessSurfaceCard, ...]) -> str:
    cards = "".join(_render_surface_card(card) for card in surfaces)
    return (
        '    <section class="panel" id="readiness-surfaces">\n'
        "      <h2>Readiness surfaces</h2>\n"
        '      <p class="hint">Each card links to an existing JSON or HTML '
        "read-only surface. Opening a linked page does not execute, apply, "
        "build, publish, or deploy.</p>\n"
        f"{cards}"
        "    </section>"
    )


def _render_surface_card(card: ReadinessSurfaceCard) -> str:
    html_href = escape(card.html_route)
    json_link = (
        f'<a class="nav-link" href="{escape(card.json_route)}">JSON</a>'
        if card.json_route
        else ""
    )
    command = (
        f'<span class="mono">{html_escape(card.command_name)}</span>'
        if card.command_name
        else html_escape("—")
    )
    counts = "".join(metric(item.label, item.value) for item in card.counts)
    if not counts:
        counts = '<p class="empty-state">No counts for this surface.</p>'
    else:
        counts = f'<div class="metric-grid">{counts}</div>'
    return (
        f'      <section class="panel" id="surface-{escape(card.key)}">\n'
        f"        <h3>{html_escape(card.label)}</h3>\n"
        '        <p class="hint">'
        f'<a class="nav-link" href="{html_href}">Open HTML</a> {json_link} '
        f"Command {command} · status {html_escape(card.overall_status)}</p>\n"
        f"        {counts}\n"
        "        <h3>Flag states</h3>\n"
        f"        {_render_codes(card.flag_states, empty='No flag states.')}\n"
        "        <h3>Blocker codes</h3>\n"
        f"        {_render_codes(card.blocker_codes, empty='No blocker codes.')}\n"
        "      </section>\n"
    )


def _render_checklist(items: tuple[IndexChecklistItem, ...]) -> str:
    if not items:
        body = '<p class="empty-state">No remaining checklist items.</p>'
    else:
        rows = "".join(_checklist_row(item) for item in items)
        body = (
            '<table class="dense"><thead><tr>'
            "<th>Code</th><th>Severity</th><th>Source</th><th>Status</th>"
            "<th>Route</th><th>Command</th><th>Label</th>"
            f"</tr></thead><tbody>{rows}</tbody></table>"
        )
    return (
        '    <section class="panel" id="remaining-manual-owner-checklist">\n'
        "      <h2>Manual owner checklist rollup</h2>\n"
        f"      {body}\n"
        "    </section>"
    )


def _checklist_row(item: IndexChecklistItem) -> str:
    route = item.html_route or item.json_route
    route_cell = (
        f'<a class="row-link mono" href="{escape(route)}">{html_escape(route)}</a>'
        if route
        else html_escape("—")
    )
    return (
        f'<tr class="{_severity_class(item.severity)}">'
        f'<td class="mono">{html_escape(item.code)}</td>'
        f"<td>{html_escape(item.severity)}</td>"
        f"<td>{titleize(item.source_section)}</td>"
        f"<td>{html_escape(item.status)}</td>"
        f"<td>{route_cell}</td>"
        f'<td class="mono">{html_escape(item.command_name)}</td>'
        f"<td>{html_escape(item.label)}</td>"
        "</tr>"
    )


def _render_footer(index: GoLiveReadinessIndex, generated: str) -> str:
    return (
        '    <footer class="footnote" id="side-effects">\n'
        f"      <p>Generated {generated}. Read-only={yes_no(index.read_only)}. "
        f"Manual review only={yes_no(index.manual_review_only)}. "
        f"Dry-run only={yes_no(index.dry_run_only)}. "
        f"No execution={yes_no(index.no_execution)}. "
        f"Executed={html_escape(index.executed)}. "
        f"Settings applied={yes_no(index.settings_applied)}. "
        f"Halt changed={yes_no(index.halt_changed)}. "
        f"Owner approved={yes_no(index.owner_approved)}. "
        f"Live action={yes_no(index.live_action)}. "
        f"Execution allowed={yes_no(index.execution_allowed)}. "
        f"Go live permitted={yes_no(index.go_live_permitted)}. "
        f"Deployment allowed={yes_no(index.deployment_allowed)}. "
        f"Build allowed={yes_no(index.build_allowed)}. "
        f"Artifact publish allowed={yes_no(index.artifact_publish_allowed)}. "
        f"Index is not permission to go live="
        f"{yes_no(index.index_is_not_permission_to_go_live)}. "
        "There are no apply, execute, lift-halt, enable-outbound, provider, "
        "build, publish, deploy, campaign, booking, call, or spend controls on "
        "this page. This is a read-only index/review view, not permission to "
        f"go live and not an execution surface. Current route "
        f"{html_escape(OPERATOR_GO_LIVE_READINESS_INDEX_PATH)}.</p>\n"
        "    </footer>"
    )


def _render_codes(codes: tuple[str, ...] | list[str], *, empty: str) -> str:
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
    raise RuntimeError(f"unhandled go-live readiness index checklist severity: {value!r}")
