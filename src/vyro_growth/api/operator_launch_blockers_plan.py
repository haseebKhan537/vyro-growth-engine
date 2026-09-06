"""Read-only operator launch blockers remediation plan HTML shell.

Phase 44 renders a sanitized view of the existing Phase 43 launch blockers
remediation plan. It reuses LaunchBlockersPlanService and never recalculates
readiness. It never executes, builds, publishes, deploys, applies settings,
lifts halt, enables outbound, calls providers, or changes live state. This
page is a remediation planning view only, not permission to go live and not
an execution surface.
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
from vyro_growth.services.launch_blockers_plan import (
    LaunchBlockersPlan,
    LaunchBlockersPlanService,
    RemediationGroup,
    RemediationStep,
)

logger = structlog.get_logger(__name__)


def render_launch_blockers_plan_error() -> str:
    return render_failure_page(
        page_id="operator-launch-blockers-plan-error",
        title="Launch blockers remediation plan unavailable",
        heading="Read-only launch blockers remediation plan unavailable",
        banner="Unable to load the launch blockers remediation plan.",
        detail=(
            "The sanitized remediation-planning view could not be rendered. "
            "Retry after checking database connectivity and runtime config. "
            "This page is a remediation planning view only, not permission to "
            "go live and not an execution surface."
        ),
    )


def render_launch_blockers_plan(plan: LaunchBlockersPlan) -> str:
    generated = html_escape(format_dt(plan.generated_at))
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '  <meta charset="utf-8">\n'
        '  <meta name="viewport" content="width=device-width, initial-scale=1">\n'
        "  <title>Launch blockers remediation plan</title>\n"
        f"{OPERATOR_UI_STYLES}\n"
        "</head>\n"
        "<body>\n"
        '  <main id="operator-launch-blockers-plan" data-read-only="true" '
        'data-dry-run-only="true" data-execution-allowed="false" '
        'data-go-live-permitted="false" data-deployment-allowed="false" '
        'data-build-allowed="false" data-artifact-publish-allowed="false" '
        'data-no-execution="true" data-manual-review-only="true" '
        'data-plan-is-not-permission-to-go-live="true" '
        'data-plan-is-not-execution="true" '
        'data-index-is-not-permission-to-go-live="true" '
        'data-handoff-is-not-go-live="true" data-binder-is-not-go-live="true" '
        'data-runbook-is-not-deployment="true" '
        'data-manifest-is-not-a-build-or-deploy="true">\n'
        f"{_render_header(plan, generated)}\n"
        f"{render_operator_nav('launch-blockers-plan')}\n"
        f"{_render_related_links()}\n"
        f"{_render_live_blocking_flags(plan)}\n"
        f"{_render_source_index(plan)}\n"
        f"{_render_related_inventory(plan)}\n"
        f"{_render_groups(plan.groups)}\n"
        f"{_render_footer(plan, generated)}\n"
        "  </main>\n"
        "</body>\n"
        "</html>\n"
    )


def build_operator_launch_blockers_plan_response(
    db: Session,
    settings: Settings,
    *,
    service: LaunchBlockersPlanService | None = None,
) -> HTMLResponse:
    try:
        builder = service or LaunchBlockersPlanService()
        plan = builder.build(db, settings)
        html = render_launch_blockers_plan(plan)
        return HTMLResponse(content=html, status_code=200, headers=NO_STORE_HEADERS)
    except Exception:
        logger.exception("operator_launch_blockers_plan_render_failed", read_only=True)
        return HTMLResponse(
            content=render_launch_blockers_plan_error(),
            status_code=500,
            headers=NO_STORE_HEADERS,
        )


def _render_header(plan: LaunchBlockersPlan, generated: str) -> str:
    git = plan.local_git
    git_meta = (
        f" · git {html_escape(git.current_branch)}@{html_escape(git.current_sha)}"
        if git.available
        else " · local git unavailable"
    )
    return (
        '    <header class="page-header">\n'
        "      <div>\n"
        "        <h1>Launch blockers remediation plan</h1>\n"
        '        <p class="lede">Read-only owner/operator remediation-planning '
        "view of existing go-live readiness index blockers. Execution remains "
        "disabled. This page does not build, publish, deploy, apply settings, "
        "or lift halt. OUTBOUND_ENABLED=false. "
        "go_live_permitted=false. execution_allowed=false. "
        "deployment_allowed=false. build_allowed=false. "
        "artifact_publish_allowed=false. This page is a remediation planning "
        "view only, not permission to go live and not an execution surface.</p>\n"
        "      </div>\n"
        f'      <p class="meta">Generated {generated} · overall '
        f"{html_escape(plan.overall_status)} · halt "
        f"{html_escape(plan.operator_halt_status)} · "
        f"{html_escape(plan.packet_kind)} · {html_escape(plan.purpose)}"
        f"{git_meta}</p>\n"
        "    </header>"
    )


def _render_related_links() -> str:
    dashboard_href = escape(OPERATOR_DASHBOARD_PATH)
    index_href = escape(OPERATOR_GO_LIVE_READINESS_INDEX_PATH)
    index_json_href = escape(GO_LIVE_READINESS_INDEX_JSON_PATH)
    plan_json_href = escape(LAUNCH_BLOCKERS_PLAN_JSON_PATH)
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
    staged_href = escape(OPERATOR_STAGED_ROLLOUT_PLAN_PATH)
    dossier_href = escape(OPERATOR_OWNER_LAUNCH_DOSSIER_PATH)
    checklist_href = escape(OPERATOR_PROVIDER_SETUP_CHECKLIST_PATH)
    rehearsal_href = escape(OPERATOR_GO_LIVE_REHEARSAL_CHECKLIST_PATH)
    outcome_href = escape(OPERATOR_REHEARSAL_OUTCOME_REPORT_PATH)
    return (
        '    <nav class="filter-nav" aria-label="Linked readiness surfaces">\n'
        f'      <a class="nav-link" href="{dashboard_href}">Dashboard</a>\n'
        f'      <a class="nav-link" href="{index_href}">Go-live index</a>\n'
        f'      <a class="nav-link" href="{index_json_href}">JSON index</a>\n'
        f'      <a class="nav-link" href="{plan_json_href}">JSON plan</a>\n'
        f'      <a class="nav-link" href="{staged_href}">Staged rollout</a>\n'
        f'      <a class="nav-link" href="{dossier_href}">Owner launch dossier</a>\n'
        f'      <a class="nav-link" href="{checklist_href}">Provider setup</a>\n'
        f'      <a class="nav-link" href="{rehearsal_href}">Go-live rehearsal</a>\n'
        f'      <a class="nav-link" href="{outcome_href}">Rehearsal outcome</a>\n'
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


def _render_live_blocking_flags(plan: LaunchBlockersPlan) -> str:
    return (
        '    <section class="status-strip" id="live-blocking-flags" '
        'aria-label="Live-blocking flags">\n'
        f"      {metric('Overall', plan.overall_status)}\n"
        f"      {metric('OUTBOUND_ENABLED', yes_no(plan.outbound_enabled))}\n"
        f"      {metric('Operator halt', plan.operator_halt_status)}\n"
        f"      {metric('Live providers', yes_no(plan.live_providers_enabled))}\n"
        f"      {metric('Go live permitted', yes_no(plan.go_live_permitted))}\n"
        f"      {metric('Execution allowed', yes_no(plan.execution_allowed))}\n"
        f"      {metric('Deployment allowed', yes_no(plan.deployment_allowed))}\n"
        f"      {metric('Build allowed', yes_no(plan.build_allowed))}\n"
        f"      {metric('Artifact publish allowed',
            yes_no(plan.artifact_publish_allowed))}\n"
        f"      {metric('Plan is not permission to go live',
            yes_no(plan.plan_is_not_permission_to_go_live))}\n"
        f"      {metric('Plan is not execution', yes_no(plan.plan_is_not_execution))}\n"
        "    </section>\n"
        '    <section class="panel" id="plan-gates">\n'
        "      <h2>Read-only flags and closed defaults</h2>\n"
        '      <div class="metric-grid">\n'
        f"        {metric('OUTBOUND_ENABLED', 'false' if not plan.outbound_enabled else 'true')}\n"
        f"        {metric('Operator halt', plan.operator_halt_status)}\n"
        f"        {metric('Halt before', plan.operator_halt_before)}\n"
        f"        {metric('Halt after', plan.operator_halt_after)}\n"
        f"        {metric('Halt changed', yes_no(plan.halt_changed))}\n"
        f"        {metric('Live providers enabled', yes_no(plan.live_providers_enabled))}\n"
        f"        {metric('Settings applied', yes_no(plan.settings_applied))}\n"
        f"        {metric('Owner approved live', yes_no(plan.owner_approved))}\n"
        f"        {metric('Live action', yes_no(plan.live_action))}\n"
        f"        {metric('Read only', yes_no(plan.read_only))}\n"
        f"        {metric('No execution', yes_no(plan.no_execution))}\n"
        f"        {metric('Executed', plan.executed)}\n"
        "      </div>\n"
        "      <h3>Blocker codes</h3>\n"
        f"      {_render_codes(plan.blocker_codes, empty='No blocker codes.')}\n"
        "      <h3>Missing credential variable names</h3>\n"
        f"      {_render_codes(plan.missing_credential_names, empty='None missing.')}\n"
        "      <h3>Closed provider flag names</h3>\n"
        f"      {_render_codes(plan.closed_provider_flag_names, empty='None closed.')}\n"
        '      <p class="hint">This page never shows secret values, environment '
        "values, API keys, tokens, message bodies, emails, phones, evidence "
        "snippets, or unsafe error text. OUTBOUND_ENABLED=false. "
        "go_live_permitted=false and execution_allowed=false. This is a "
        "read-only remediation planning view, not permission to go live.</p>\n"
        "    </section>"
    )


def _render_source_index(plan: LaunchBlockersPlan) -> str:
    index_href = escape(OPERATOR_GO_LIVE_READINESS_INDEX_PATH)
    index_json_href = escape(plan.source_index_route)
    return (
        '    <section class="panel" id="source-index">\n'
        "      <h2>Source go-live readiness index</h2>\n"
        '      <p class="hint">This plan reuses the existing Phase 43 / Phase 42 '
        "index payload. It does not recalculate readiness or execute.</p>\n"
        '      <div class="metric-grid">\n'
        f"        {metric('Source command', plan.source_index_command)}\n"
        f"        {metric('Source JSON route', plan.source_index_route)}\n"
        f"        {metric('Source overall status', plan.source_index_overall_status)}\n"
        "      </div>\n"
        '      <p class="hint">'
        f'<a class="nav-link" href="{index_href}">Open HTML index</a> '
        f'<a class="nav-link" href="{index_json_href}">Open JSON index</a></p>\n'
        "    </section>"
    )


def _render_related_inventory(plan: LaunchBlockersPlan) -> str:
    return (
        '    <section class="panel" id="related-routes">\n'
        "      <h2>Related safe routes</h2>\n"
        f"      {_render_route_links(plan.related_routes, empty='No related routes.')}\n"
        "    </section>\n"
        '    <section class="panel" id="related-commands">\n'
        "      <h2>Related CLI commands</h2>\n"
        f"      {_render_codes(plan.related_commands, empty='No related commands.')}\n"
        "    </section>"
    )


def _render_groups(groups: tuple[RemediationGroup, ...]) -> str:
    if not groups:
        body = '<p class="empty-state">No grouped remediation steps.</p>'
    else:
        body = "".join(_render_group(group) for group in groups)
    return (
        '    <section class="panel" id="remediation-groups">\n'
        "      <h2>Grouped remediation steps</h2>\n"
        '      <p class="hint">Each step is a manual owner/operator action. '
        "Opening a linked page does not execute, apply, build, publish, or "
        "deploy.</p>\n"
        f"{body}"
        "    </section>"
    )


def _render_group(group: RemediationGroup) -> str:
    rows = "".join(_step_row(step) for step in group.steps)
    table = (
        '<table class="dense"><thead><tr>'
        "<th>Blocker code</th><th>Status</th><th>Kind</th><th>Owner approval</th>"
        "<th>Config name</th><th>Route</th><th>Command</th><th>Recommended step</th>"
        f"</tr></thead><tbody>{rows}</tbody></table>"
        if group.steps
        else '<p class="empty-state">No steps in this group.</p>'
    )
    return (
        f'      <section class="panel" id="group-{escape(group.group_key)}">\n'
        f"        <h3>{html_escape(group.group_label)}</h3>\n"
        '        <p class="hint">Group '
        f'<span class="mono">{html_escape(group.group_key)}</span> · '
        f"{titleize(group.group_kind)} · status "
        f"{html_escape(group.overall_status)} · steps "
        f"{html_escape(group.step_count)}</p>\n"
        f"        {table}\n"
        "      </section>\n"
    )


def _step_row(step: RemediationStep) -> str:
    route = step.html_route or step.json_route
    route_cell = (
        f'<a class="row-link mono" href="{escape(route)}">{html_escape(route)}</a>'
        if route
        else html_escape("—")
    )
    return (
        f'<tr class="{_status_class(step.current_status)}">'
        f'<td class="mono">{html_escape(step.blocker_code)}</td>'
        f"<td>{html_escape(step.current_status)}</td>"
        f"<td>{titleize(step.step_kind)}</td>"
        f"<td>{titleize(step.owner_approval_type)}</td>"
        f'<td class="mono">{html_escape(step.config_name)}</td>'
        f"<td>{route_cell}</td>"
        f'<td class="mono">{html_escape(step.command_name)}</td>'
        f"<td>{html_escape(step.recommended_step)}</td>"
        "</tr>"
    )


def _render_footer(plan: LaunchBlockersPlan, generated: str) -> str:
    return (
        '    <footer class="footnote" id="side-effects">\n'
        f"      <p>Generated {generated}. Read-only={yes_no(plan.read_only)}. "
        f"Manual review only={yes_no(plan.manual_review_only)}. "
        f"Dry-run only={yes_no(plan.dry_run_only)}. "
        f"No execution={yes_no(plan.no_execution)}. "
        f"Executed={html_escape(plan.executed)}. "
        f"Settings applied={yes_no(plan.settings_applied)}. "
        f"Halt changed={yes_no(plan.halt_changed)}. "
        f"Owner approved={yes_no(plan.owner_approved)}. "
        f"Live action={yes_no(plan.live_action)}. "
        f"Execution allowed={yes_no(plan.execution_allowed)}. "
        f"Go live permitted={yes_no(plan.go_live_permitted)}. "
        f"Deployment allowed={yes_no(plan.deployment_allowed)}. "
        f"Build allowed={yes_no(plan.build_allowed)}. "
        f"Artifact publish allowed={yes_no(plan.artifact_publish_allowed)}. "
        f"Plan is not permission to go live="
        f"{yes_no(plan.plan_is_not_permission_to_go_live)}. "
        f"Plan is not execution={yes_no(plan.plan_is_not_execution)}. "
        "There are no apply, execute, lift-halt, enable-outbound, provider, "
        "build, publish, deploy, campaign, booking, call, or spend controls on "
        "this page. This is a read-only remediation planning view, not "
        "permission to go live and not an execution surface. Current route "
        f"{html_escape(OPERATOR_LAUNCH_BLOCKERS_PLAN_PATH)}.</p>\n"
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
