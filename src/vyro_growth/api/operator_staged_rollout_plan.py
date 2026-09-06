"""Read-only operator staged go-live rollout plan HTML shell.

Phase 46 renders a sanitized view of the existing Phase 45 staged go-live
rollout plan. It reuses StagedRolloutPlanService and never recalculates
readiness. It never executes, builds, publishes, deploys, applies settings,
lifts halt, enables outbound, calls providers, or changes live state. This
page is a staged rollout planning view only, not permission to go live and
not an execution surface.
"""

from __future__ import annotations

from html import escape

import structlog
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from vyro_growth.api.operator_ui import (
    COMMAND_CENTER_JSON_PATH,
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
    RELEASE_ARTIFACT_MANIFEST_JSON_PATH,
    RELEASE_CANDIDATE_RUNBOOK_JSON_PATH,
    SETTINGS_EXECUTION_PREFLIGHT_JSON_PATH,
    STAGED_ROLLOUT_PLAN_JSON_PATH,
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
from vyro_growth.services.staged_rollout_plan import (
    StagedRolloutChecklistItem,
    StagedRolloutPlan,
    StagedRolloutPlanService,
    StagedRolloutStage,
)

logger = structlog.get_logger(__name__)


def render_staged_rollout_plan_error() -> str:
    return render_failure_page(
        page_id="operator-staged-rollout-plan-error",
        title="Staged go-live rollout plan unavailable",
        heading="Read-only staged go-live rollout plan unavailable",
        banner="Unable to load the staged go-live rollout plan.",
        detail=(
            "The sanitized staged-rollout-planning view could not be rendered. "
            "Retry after checking database connectivity and runtime config. "
            "This page is a staged rollout planning view only, not permission "
            "to go live and not an execution surface."
        ),
    )


def render_staged_rollout_plan(plan: StagedRolloutPlan) -> str:
    generated = html_escape(format_dt(plan.generated_at))
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '  <meta charset="utf-8">\n'
        '  <meta name="viewport" content="width=device-width, initial-scale=1">\n'
        "  <title>Staged go-live rollout plan</title>\n"
        f"{OPERATOR_UI_STYLES}\n"
        "</head>\n"
        "<body>\n"
        '  <main id="operator-staged-rollout-plan" data-read-only="true" '
        'data-dry-run-only="true" data-execution-allowed="false" '
        'data-go-live-permitted="false" data-deployment-allowed="false" '
        'data-build-allowed="false" data-artifact-publish-allowed="false" '
        'data-no-execution="true" data-manual-review-only="true" '
        'data-staged-rollout-plan-is-not-go-live="true" '
        'data-plan-is-not-permission-to-go-live="true" '
        'data-plan-is-not-execution="true" '
        'data-index-is-not-permission-to-go-live="true" '
        'data-handoff-is-not-go-live="true" data-binder-is-not-go-live="true" '
        'data-runbook-is-not-deployment="true" '
        'data-manifest-is-not-a-build-or-deploy="true">\n'
        f"{_render_header(plan, generated)}\n"
        f"{render_operator_nav('staged-rollout-plan')}\n"
        f"{_render_related_links()}\n"
        f"{_render_live_blocking_flags(plan)}\n"
        f"{_render_source_references(plan)}\n"
        f"{_render_related_inventory(plan)}\n"
        f"{_render_stages(plan.stages)}\n"
        f"{_render_footer(plan, generated)}\n"
        "  </main>\n"
        "</body>\n"
        "</html>\n"
    )


def build_operator_staged_rollout_plan_response(
    db: Session,
    settings: Settings,
    *,
    service: StagedRolloutPlanService | None = None,
) -> HTMLResponse:
    try:
        builder = service or StagedRolloutPlanService()
        plan = builder.build(db, settings)
        html = render_staged_rollout_plan(plan)
        return HTMLResponse(content=html, status_code=200, headers=NO_STORE_HEADERS)
    except Exception:
        logger.exception("operator_staged_rollout_plan_render_failed", read_only=True)
        return HTMLResponse(
            content=render_staged_rollout_plan_error(),
            status_code=500,
            headers=NO_STORE_HEADERS,
        )


def _render_header(plan: StagedRolloutPlan, generated: str) -> str:
    git = plan.local_git
    git_meta = (
        f" · git {html_escape(git.current_branch)}@{html_escape(git.current_sha)}"
        if git.available
        else " · local git unavailable"
    )
    return (
        '    <header class="page-header">\n'
        "      <div>\n"
        "        <h1>Staged go-live rollout plan</h1>\n"
        '        <p class="lede">Read-only owner/operator staged-rollout-planning '
        "view of existing readiness, blocker, binder, runbook, and manifest "
        "surfaces. Execution remains disabled. This page does not build, "
        "publish, deploy, apply settings, or lift halt. OUTBOUND_ENABLED=false. "
        "go_live_permitted=false. execution_allowed=false. "
        "deployment_allowed=false. build_allowed=false. "
        "artifact_publish_allowed=false. staged_rollout_plan_is_not_go_live=true. "
        "This page is a staged rollout planning view only, not permission to "
        "go live and not an execution surface.</p>\n"
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
    command_center_href = escape(COMMAND_CENTER_JSON_PATH)
    index_href = escape(OPERATOR_GO_LIVE_READINESS_INDEX_PATH)
    index_json_href = escape(GO_LIVE_READINESS_INDEX_JSON_PATH)
    blockers_href = escape(OPERATOR_LAUNCH_BLOCKERS_PLAN_PATH)
    blockers_json_href = escape(LAUNCH_BLOCKERS_PLAN_JSON_PATH)
    plan_json_href = escape(STAGED_ROLLOUT_PLAN_JSON_PATH)
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
    dossier_href = escape(OPERATOR_OWNER_LAUNCH_DOSSIER_PATH)
    return (
        '    <nav class="filter-nav" aria-label="Linked readiness surfaces">\n'
        f'      <a class="nav-link" href="{dashboard_href}">Dashboard</a>\n'
        f'      <a class="nav-link" href="{command_center_href}">JSON command center</a>\n'
        f'      <a class="nav-link" href="{index_href}">Go-live index</a>\n'
        f'      <a class="nav-link" href="{index_json_href}">JSON index</a>\n'
        f'      <a class="nav-link" href="{blockers_href}">Launch blockers</a>\n'
        f'      <a class="nav-link" href="{blockers_json_href}">JSON blockers</a>\n'
        f'      <a class="nav-link" href="{plan_json_href}">JSON staged plan</a>\n'
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
        f'      <a class="nav-link" href="{dossier_href}">Owner launch dossier</a>\n'
        "    </nav>"
    )


def _render_live_blocking_flags(plan: StagedRolloutPlan) -> str:
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
        f"      {metric('Staged rollout plan is not go-live',
            yes_no(plan.staged_rollout_plan_is_not_go_live))}\n"
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
        "read-only staged rollout planning view, not permission to go live.</p>\n"
        "    </section>"
    )


def _render_source_references(plan: StagedRolloutPlan) -> str:
    rows = "".join(
        (
            _source_row(
                "Go-live readiness index",
                plan.source_index_command,
                plan.source_index_route,
                plan.source_index_overall_status,
                OPERATOR_GO_LIVE_READINESS_INDEX_PATH,
            ),
            _source_row(
                "Launch blockers remediation plan",
                plan.source_blockers_plan_command,
                plan.source_blockers_plan_route,
                plan.source_blockers_plan_overall_status,
                OPERATOR_LAUNCH_BLOCKERS_PLAN_PATH,
            ),
            _source_row(
                "Launch readiness",
                plan.source_launch_readiness_command,
                plan.source_launch_readiness_route,
                plan.source_launch_readiness_overall_status,
                None,
            ),
            _source_row(
                "Compliance evidence binder",
                plan.source_binder_command,
                plan.source_binder_route,
                plan.source_binder_overall_status,
                OPERATOR_COMPLIANCE_EVIDENCE_BINDER_PATH,
            ),
            _source_row(
                "Release-candidate runbook",
                plan.source_runbook_command,
                plan.source_runbook_route,
                plan.source_runbook_overall_status,
                OPERATOR_RELEASE_CANDIDATE_RUNBOOK_PATH,
            ),
            _source_row(
                "Release artifact manifest",
                plan.source_manifest_command,
                plan.source_manifest_route,
                plan.source_manifest_overall_status,
                OPERATOR_RELEASE_ARTIFACT_MANIFEST_PATH,
            ),
        )
    )
    return (
        '    <section class="panel" id="source-references">\n'
        "      <h2>Source references</h2>\n"
        '      <p class="hint">This plan reuses the existing Phase 45 / Phase 43 '
        "/ Phase 42 payloads. It does not recalculate readiness or execute.</p>\n"
        '<table class="dense"><thead><tr>'
        "<th>Source</th><th>Command</th><th>JSON route</th><th>Overall status</th>"
        "<th>HTML route</th>"
        f"</tr></thead><tbody>{rows}</tbody></table>\n"
        "    </section>"
    )


def _source_row(
    label: str,
    command: str,
    json_route: str,
    overall_status: str,
    html_route: str | None,
) -> str:
    json_cell = (
        f'<a class="row-link mono" href="{escape(json_route)}">'
        f"{html_escape(json_route)}</a>"
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


def _render_related_inventory(plan: StagedRolloutPlan) -> str:
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


def _render_stages(stages: tuple[StagedRolloutStage, ...]) -> str:
    if not stages:
        body = '<p class="empty-state">No staged rollout groups.</p>'
    else:
        body = "".join(_render_stage(stage) for stage in stages)
    return (
        '    <section class="panel" id="rollout-stages">\n'
        "      <h2>Staged rollout groups</h2>\n"
        '      <p class="hint">Stages 0-5 are a manual owner/operator planning '
        "sequence. Opening a linked page does not execute, apply, build, "
        "publish, or deploy.</p>\n"
        f"{body}"
        "    </section>"
    )


def _render_stage(stage: StagedRolloutStage) -> str:
    rows = "".join(_checklist_row(item) for item in stage.checklist_items)
    table = (
        '<table class="dense"><thead><tr>'
        "<th>Code</th><th>Status</th><th>Owner approval</th>"
        "<th>Config name</th><th>Route</th><th>Command</th><th>Checklist item</th>"
        f"</tr></thead><tbody>{rows}</tbody></table>"
        if stage.checklist_items
        else '<p class="empty-state">No checklist items in this stage.</p>'
    )
    return (
        f'      <section class="panel" id="stage-{escape(stage.stage_key)}">\n'
        f"        <h3>{html_escape(stage.stage_label)}</h3>\n"
        '        <p class="hint">Stage '
        f'<span class="mono">{html_escape(stage.stage_key)}</span> · status '
        f"{html_escape(stage.status)} · required approval "
        f"{titleize(stage.required_owner_approval_type)}</p>\n"
        '        <div class="metric-grid">\n'
        f"          {metric('Read only', yes_no(stage.read_only))}\n"
        f"          {metric('No execution', yes_no(stage.no_execution))}\n"
        f"          {metric('Execution allowed', yes_no(stage.execution_allowed))}\n"
        f"          {metric('Go live permitted', yes_no(stage.go_live_permitted))}\n"
        f"          {metric('Deployment allowed', yes_no(stage.deployment_allowed))}\n"
        f"          {metric('Settings applied', yes_no(stage.settings_applied))}\n"
        f"          {metric('Halt changed', yes_no(stage.halt_changed))}\n"
        f"          {metric('OUTBOUND_ENABLED', yes_no(stage.outbound_enabled))}\n"
        f"          {metric('Owner approved', yes_no(stage.owner_approved))}\n"
        f"          {metric('Staged rollout plan is not go-live',
            yes_no(stage.staged_rollout_plan_is_not_go_live))}\n"
        "        </div>\n"
        "        <h3>Blocker codes</h3>\n"
        f"        {_render_codes(stage.blocker_codes, empty='No blocker codes.')}\n"
        "        <h3>Gate codes</h3>\n"
        f"        {_render_codes(stage.gate_codes, empty='No gate codes.')}\n"
        "        <h3>Related routes</h3>\n"
        f"        {_render_route_links(stage.related_routes, empty='No related routes.')}\n"
        "        <h3>Related commands</h3>\n"
        f"        {_render_codes(stage.related_commands, empty='No related commands.')}\n"
        "        <h3>Related config names</h3>\n"
        f"        {_render_codes(stage.related_config_names, empty='No related config names.')}\n"
        "        <h3>Checklist items</h3>\n"
        f"        {table}\n"
        "      </section>\n"
    )


def _checklist_row(item: StagedRolloutChecklistItem) -> str:
    route = item.html_route or item.json_route
    route_cell = (
        f'<a class="row-link mono" href="{escape(route)}">{html_escape(route)}</a>'
        if route
        else html_escape("—")
    )
    return (
        f'<tr class="{_status_class(item.status)}">'
        f'<td class="mono">{html_escape(item.code)}</td>'
        f"<td>{html_escape(item.status)}</td>"
        f"<td>{titleize(item.owner_approval_type)}</td>"
        f'<td class="mono">{html_escape(item.config_name)}</td>'
        f"<td>{route_cell}</td>"
        f'<td class="mono">{html_escape(item.command_name)}</td>'
        f"<td>{html_escape(item.label)}</td>"
        "</tr>"
    )


def _render_footer(plan: StagedRolloutPlan, generated: str) -> str:
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
        f"Staged rollout plan is not go-live="
        f"{yes_no(plan.staged_rollout_plan_is_not_go_live)}. "
        f"Plan is not permission to go live="
        f"{yes_no(plan.plan_is_not_permission_to_go_live)}. "
        f"Plan is not execution={yes_no(plan.plan_is_not_execution)}. "
        "There are no apply, execute, lift-halt, enable-outbound, provider, "
        "build, publish, deploy, campaign, booking, call, or spend controls on "
        "this page. This is a read-only staged rollout planning view, not "
        "permission to go live and not an execution surface. Current route "
        f"{html_escape(OPERATOR_STAGED_ROLLOUT_PLAN_PATH)}.</p>\n"
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
