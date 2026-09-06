"""Read-only operator go-live rehearsal checklist HTML shell.

Phase 52 renders a sanitized view of the existing Phase 51 manual go-live
rehearsal checklist. It reuses GoLiveRehearsalChecklistService and never
recalculates readiness. It never executes, builds, publishes, deploys,
applies settings, lifts halt, enables outbound, calls providers, or changes
live state. This page is a manual rehearsal review view only, not a script
runner, not permission to go live, and not an execution surface.
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
    OPERATOR_SUPERVISED_PILOT_CANDIDATES_PATH,
    OPERATOR_SUPERVISED_PILOT_PLAN_PATH,
    OPERATOR_UI_STYLES,
    OWNER_HANDOFF_JSON_PATH,
    OWNER_LAUNCH_DOSSIER_JSON_PATH,
    PROVIDER_SETUP_CHECKLIST_JSON_PATH,
    REHEARSAL_OUTCOME_REPORT_JSON_PATH,
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
from vyro_growth.services.go_live_rehearsal_checklist import (
    GoLiveRehearsalChecklist,
    GoLiveRehearsalChecklistService,
    RehearsalAssertion,
    RehearsalNextAction,
    RehearsalRollbackNote,
    RehearsalSourceSurface,
    RehearsalStep,
)
from vyro_growth.services.release_artifact_manifest import LocalGitMetadata

logger = structlog.get_logger(__name__)


def render_go_live_rehearsal_checklist_error() -> str:
    return render_failure_page(
        page_id="operator-go-live-rehearsal-checklist-error",
        title="Go-live rehearsal checklist unavailable",
        heading="Read-only go-live rehearsal checklist unavailable",
        banner="Unable to load the go-live rehearsal checklist.",
        detail=(
            "The sanitized manual-rehearsal review view could not be rendered. "
            "Retry after checking database connectivity and runtime config. "
            "This page is a manual rehearsal review view only, not permission "
            "to go live and not an execution surface."
        ),
    )


def render_go_live_rehearsal_checklist(checklist: GoLiveRehearsalChecklist) -> str:
    generated = html_escape(format_dt(checklist.generated_at))
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '  <meta charset="utf-8">\n'
        '  <meta name="viewport" content="width=device-width, initial-scale=1">\n'
        "  <title>Go-live rehearsal checklist</title>\n"
        f"{OPERATOR_UI_STYLES}\n"
        "</head>\n"
        "<body>\n"
        '  <main id="operator-go-live-rehearsal-checklist" data-read-only="true" '
        'data-dry-run-only="true" data-execution-allowed="false" '
        'data-go-live-permitted="false" data-deployment-allowed="false" '
        'data-build-allowed="false" data-artifact-publish-allowed="false" '
        'data-no-execution="true" data-no-go-live="true" '
        'data-no-deployment="true" data-manual-review-only="true" '
        'data-go-live-rehearsal-checklist-is-not-go-live="true" '
        'data-checklist-is-not-permission-to-go-live="true" '
        'data-checklist-is-not-execution="true" '
        'data-rehearsal-is-not-a-script-runner="true" '
        'data-index-is-not-permission-to-go-live="true" '
        'data-dossier-is-not-permission-to-go-live="true" '
        'data-staged-rollout-plan-is-not-go-live="true" '
        'data-provider-setup-checklist-is-not-go-live="true" '
        'data-runbook-is-not-deployment="true" '
        'data-manifest-is-not-a-build-or-deploy="true">\n'
        f"{_render_header(checklist, generated)}\n"
        f"{render_operator_nav('go-live-rehearsal-checklist')}\n"
        f"{_render_related_links()}\n"
        f"{_render_live_blocking_flags(checklist)}\n"
        f"{_render_expected_assertions(checklist.expected_safe_assertions)}\n"
        f"{_render_source_references(checklist)}\n"
        f"{_render_included_surfaces(checklist.sources)}\n"
        f"{_render_rehearsal_steps(checklist.rehearsal_steps)}\n"
        f"{_render_rollback_guidance(checklist.rollback_guidance)}\n"
        f"{_render_related_inventory(checklist)}\n"
        f"{_render_local_git(checklist.local_git)}\n"
        f"{_render_next_actions(checklist.next_actions)}\n"
        f"{_render_footer(checklist, generated)}\n"
        "  </main>\n"
        "</body>\n"
        "</html>\n"
    )


def build_operator_go_live_rehearsal_checklist_response(
    db: Session,
    settings: Settings,
    *,
    service: GoLiveRehearsalChecklistService | None = None,
) -> HTMLResponse:
    try:
        builder = service or GoLiveRehearsalChecklistService()
        checklist = builder.build(db, settings)
        html = render_go_live_rehearsal_checklist(checklist)
        return HTMLResponse(content=html, status_code=200, headers=NO_STORE_HEADERS)
    except Exception:
        logger.exception("operator_go_live_rehearsal_checklist_render_failed", read_only=True)
        return HTMLResponse(
            content=render_go_live_rehearsal_checklist_error(),
            status_code=500,
            headers=NO_STORE_HEADERS,
        )


def _render_header(checklist: GoLiveRehearsalChecklist, generated: str) -> str:
    git = checklist.local_git
    git_meta = (
        f" · git {html_escape(git.current_branch)}@{html_escape(git.current_sha)}"
        if git.available
        else " · local git unavailable"
    )
    return (
        '    <header class="page-header">\n'
        "      <div>\n"
        "        <h1>Go-live rehearsal checklist</h1>\n"
        '        <p class="lede">Read-only owner/operator review view of the '
        "existing manual go-live rehearsal checklist. Execution remains "
        "disabled. This page does not build, publish, deploy, apply "
        "settings, or lift halt. OUTBOUND_ENABLED=false. "
        "go_live_permitted=false. execution_allowed=false. "
        "deployment_allowed=false. build_allowed=false. "
        "artifact_publish_allowed=false. owner_approved=false. "
        "go_live_rehearsal_checklist_is_not_go_live=true. "
        "rehearsal_is_not_a_script_runner=true. This page is a "
        "manual rehearsal review view only, not permission to go live and "
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
    checklist_href = escape(OPERATOR_PROVIDER_SETUP_CHECKLIST_PATH)
    checklist_json_href = escape(PROVIDER_SETUP_CHECKLIST_JSON_PATH)
    rehearsal_json_href = escape(GO_LIVE_REHEARSAL_CHECKLIST_JSON_PATH)
    outcome_href = escape(OPERATOR_REHEARSAL_OUTCOME_REPORT_PATH)
    pilot_href = escape(OPERATOR_SUPERVISED_PILOT_PLAN_PATH)
    candidates_href = escape(OPERATOR_SUPERVISED_PILOT_CANDIDATES_PATH)
    outcome_json_href = escape(REHEARSAL_OUTCOME_REPORT_JSON_PATH)
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
        f'      <a class="nav-link" href="{checklist_href}">Provider setup</a>\n'
        f'      <a class="nav-link" href="{checklist_json_href}">JSON checklist</a>\n'
        f'      <a class="nav-link" href="{rehearsal_json_href}">JSON rehearsal</a>\n'
        f'      <a class="nav-link" href="{outcome_href}">Rehearsal outcome</a>\n'
        f'      <a class="nav-link" href="{outcome_json_href}">JSON outcome</a>\n'
        f'      <a class="nav-link" href="{pilot_href}">Supervised pilot</a>\n'
        f'      <a class="nav-link" href="{candidates_href}">Pilot candidates</a>\n'
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


def _render_live_blocking_flags(checklist: GoLiveRehearsalChecklist) -> str:
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
        f"      {metric('Go-live rehearsal checklist is not go-live',
            yes_no(checklist.go_live_rehearsal_checklist_is_not_go_live))}\n"
        f"      {metric('Checklist is not permission to go live',
            yes_no(checklist.checklist_is_not_permission_to_go_live))}\n"
        f"      {metric('Checklist is not execution',
            yes_no(checklist.checklist_is_not_execution))}\n"
        f"      {metric('Rehearsal is not a script runner',
            yes_no(checklist.rehearsal_is_not_a_script_runner))}\n"
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
        "read-only manual rehearsal review view, not permission to go live.</p>\n"
        "    </section>"
    )


def _render_expected_assertions(assertions: tuple[RehearsalAssertion, ...]) -> str:
    if not assertions:
        body = '<p class="empty-state">No expected safe assertions.</p>'
    else:
        rows = "".join(_assertion_row(item) for item in assertions)
        body = (
            '<table class="dense"><thead><tr>'
            "<th>Key</th><th>Expected</th><th>Observed</th><th>Passed</th>"
            f"</tr></thead><tbody>{rows}</tbody></table>"
        )
    return (
        '    <section class="panel" id="expected-safe-assertions">\n'
        "      <h2>Expected safe assertions</h2>\n"
        '      <p class="hint">These assertions are review reminders only. '
        "This page does not execute, apply settings, lift halt, or change "
        "live flags. Expected values include OUTBOUND_ENABLED=false, "
        "go_live_permitted=false, execution_allowed=false, "
        "deployment_allowed=false, owner_approved=false, and halt unchanged.</p>\n"
        f"      {body}\n"
        "    </section>"
    )


def _assertion_row(item: RehearsalAssertion) -> str:
    status = "ready_for_owner_review" if item.passed else FindingSeverity.BLOCKED.value
    return (
        f'<tr class="{_status_class(status)}">'
        f'<td class="mono">{html_escape(item.key)}</td>'
        f'<td class="mono">{html_escape(item.expected)}</td>'
        f'<td class="mono">{html_escape(item.observed)}</td>'
        f"<td>{yes_no(item.passed)}</td>"
        "</tr>"
    )


def _render_source_references(checklist: GoLiveRehearsalChecklist) -> str:
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
                "Provider setup checklist",
                checklist.source_provider_setup_command,
                checklist.source_provider_setup_route,
                checklist.source_provider_setup_overall_status,
                OPERATOR_PROVIDER_SETUP_CHECKLIST_PATH,
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
            _source_row(
                "Release artifact manifest",
                checklist.source_manifest_command,
                checklist.source_manifest_route,
                checklist.source_manifest_overall_status,
                OPERATOR_RELEASE_ARTIFACT_MANIFEST_PATH,
            ),
        )
    )
    return (
        '    <section class="panel" id="source-references">\n'
        "      <h2>Source references</h2>\n"
        '      <p class="hint">This page reuses the existing Phase 51 '
        "go-live rehearsal checklist payload. It does not recalculate "
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


def _render_included_surfaces(sources: tuple[RehearsalSourceSurface, ...]) -> str:
    if not sources:
        body = '<p class="empty-state">No included source surfaces.</p>'
    else:
        body = "".join(_render_source_card(source) for source in sources)
    return (
        '    <section class="panel" id="included-surfaces">\n'
        "      <h2>Included source surfaces</h2>\n"
        '      <p class="hint">Each card is a Phase 51 source surface. '
        "Opening a linked page does not execute, apply, build, publish, or "
        "deploy.</p>\n"
        f"{body}"
        "    </section>"
    )


def _render_source_card(source: RehearsalSourceSurface) -> str:
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


def _render_rehearsal_steps(steps: tuple[RehearsalStep, ...]) -> str:
    if not steps:
        body = '<p class="empty-state">No rehearsal steps.</p>'
    else:
        body = "".join(_render_step_card(step) for step in steps)
    return (
        '    <section class="panel" id="rehearsal-steps">\n'
        "      <h2>Manual rehearsal steps</h2>\n"
        '      <p class="hint">Each card is a Phase 51 rehearsal step. '
        "Steps are manual instructions only. runnable=false and executed=0. "
        "Command names and routes are references only. This page does not "
        "run commands or change live state.</p>\n"
        f"{body}"
        "    </section>"
    )


def _render_step_card(step: RehearsalStep) -> str:
    html_link = (
        f'<a class="nav-link" href="{escape(step.html_route)}">Open HTML</a>'
        if step.html_route
        else ""
    )
    json_link = (
        f'<a class="nav-link" href="{escape(step.json_route)}">JSON</a>'
        if step.json_route
        else ""
    )
    command = (
        f'<span class="mono">{html_escape(step.command_name)}</span>'
        if step.command_name
        else html_escape("—")
    )
    return (
        f'      <section class="panel" id="step-{escape(step.step_key)}">\n'
        f"        <h3>{html_escape(step.label)}</h3>\n"
        '        <p class="hint">Required owner approval type '
        f"{html_escape(step.required_owner_approval_type)} · gate "
        f"{html_escape(step.gate_key)} · status {html_escape(step.status)} · "
        f"kind {html_escape(step.step_kind)}. {html_link} {json_link} "
        f"Command {command}</p>\n"
        f'        <p class="hint">{html_escape(step.instruction)}</p>\n'
        '        <div class="metric-grid">\n'
        f"          {metric('Step key', step.step_key)}\n"
        f"          {metric('Gate key', step.gate_key)}\n"
        f"          {metric('Approval type', step.required_owner_approval_type)}\n"
        f"          {metric('Step kind', step.step_kind)}\n"
        f"          {metric('Runnable', yes_no(step.runnable))}\n"
        f"          {metric('Executed', step.executed)}\n"
        f"          {metric('Config name', step.config_name)}\n"
        "        </div>\n"
        "        <h3>Expected assertions</h3>\n"
        f"        {_render_codes(step.expected_assertions, empty='No expected assertions.')}\n"
        "        <h3>Blocker codes</h3>\n"
        f"        {_render_codes(step.blocker_codes, empty='No blocker codes.')}\n"
        "        <h3>Gate codes</h3>\n"
        f"        {_render_codes(step.gate_codes, empty='No gate codes.')}\n"
        "      </section>\n"
    )


def _render_rollback_guidance(notes: tuple[RehearsalRollbackNote, ...]) -> str:
    if not notes:
        body = '<p class="empty-state">No rollback or abort guidance.</p>'
    else:
        rows = "".join(_rollback_row(note) for note in notes)
        body = (
            '<table class="dense"><thead><tr>'
            "<th>Code</th><th>Label</th><th>Instruction</th>"
            f"</tr></thead><tbody>{rows}</tbody></table>"
        )
    return (
        '    <section class="panel" id="rollback-guidance">\n'
        "      <h2>Rollback and abort guidance</h2>\n"
        '      <p class="hint">Review text only. This page does not abort, '
        "roll back, lift halt, apply settings, or change live flags.</p>\n"
        f"      {body}\n"
        "    </section>"
    )


def _rollback_row(note: RehearsalRollbackNote) -> str:
    return (
        "<tr>"
        f'<td class="mono">{html_escape(note.code)}</td>'
        f"<td>{html_escape(note.label)}</td>"
        f"<td>{html_escape(note.instruction)}</td>"
        "</tr>"
    )


def _render_related_inventory(checklist: GoLiveRehearsalChecklist) -> str:
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


def _render_next_actions(actions: tuple[RehearsalNextAction, ...]) -> str:
    if not actions:
        body = '<p class="empty-state">No owner next steps.</p>'
    else:
        rows = "".join(_next_action_row(action) for action in actions)
        body = (
            '<table class="dense"><thead><tr>'
            "<th>Code</th><th>Status</th><th>Command</th><th>Route</th>"
            "<th>Config name</th><th>Label</th>"
            f"</tr></thead><tbody>{rows}</tbody></table>"
        )
    return (
        '    <section class="panel" id="owner-next-steps">\n'
        "      <h2>Non-executable owner next steps</h2>\n"
        '      <p class="hint">These labels are review reminders only. They do '
        "not execute, approve, apply, deploy, or lift halt.</p>\n"
        f"      {body}\n"
        "    </section>"
    )


def _next_action_row(action: RehearsalNextAction) -> str:
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


def _render_footer(checklist: GoLiveRehearsalChecklist, generated: str) -> str:
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
        f"Go-live rehearsal checklist is not go-live="
        f"{yes_no(checklist.go_live_rehearsal_checklist_is_not_go_live)}. "
        f"Checklist is not permission to go live="
        f"{yes_no(checklist.checklist_is_not_permission_to_go_live)}. "
        f"Checklist is not execution={yes_no(checklist.checklist_is_not_execution)}. "
        f"Rehearsal is not a script runner="
        f"{yes_no(checklist.rehearsal_is_not_a_script_runner)}. "
        "There are no apply, execute, lift-halt, enable-outbound, provider, "
        "build, publish, deploy, campaign, booking, call, or spend controls on "
        "this page. This is a read-only manual rehearsal review view, not "
        "permission to go live and not an execution surface. Current route "
        f"{html_escape(OPERATOR_GO_LIVE_REHEARSAL_CHECKLIST_PATH)}.</p>\n"
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
