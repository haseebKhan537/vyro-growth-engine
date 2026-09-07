"""Read-only operator rehearsal outcome report HTML shell.

Phase 54 renders a sanitized view of the existing Phase 53 rehearsal
outcome report. It reuses RehearsalOutcomeReportService and never
recalculates readiness. It never executes, builds, publishes, deploys,
applies settings, lifts halt, enables outbound, calls providers, or
changes live state. This page is an outcome report review view only,
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
    OPERATOR_SUPERVISED_PILOT_CANDIDATES_PATH,
    OPERATOR_SUPERVISED_PILOT_FIRST_SEND_PREFLIGHT_PATH,
    OPERATOR_SUPERVISED_PILOT_GO_NO_GO_PATH,
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
    SUPERVISED_PILOT_CANDIDATES_JSON_PATH,
    SUPERVISED_PILOT_FIRST_SEND_PREFLIGHT_JSON_PATH,
    SUPERVISED_PILOT_GO_NO_GO_JSON_PATH,
    SUPERVISED_PILOT_PLAN_JSON_PATH,
    format_dt,
    html_escape,
    metric,
    render_failure_page,
    render_operator_nav,
    yes_no,
)
from vyro_growth.config import Settings
from vyro_growth.domain import FindingSeverity
from vyro_growth.services.rehearsal_outcome_report import (
    OutcomeCount,
    OutcomeNextAction,
    RehearsalOutcomeReport,
    RehearsalOutcomeReportService,
)
from vyro_growth.services.release_artifact_manifest import LocalGitMetadata

logger = structlog.get_logger(__name__)


def render_rehearsal_outcome_report_error() -> str:
    return render_failure_page(
        page_id="operator-rehearsal-outcome-report-error",
        title="Rehearsal outcome report unavailable",
        heading="Read-only rehearsal outcome report unavailable",
        banner="Unable to load the rehearsal outcome report.",
        detail=(
            "The sanitized rehearsal-outcome review view could not be rendered. "
            "Retry after checking database connectivity and runtime config. "
            "This page is an outcome report review view only, not permission "
            "to go live and not an execution surface."
        ),
    )


def render_rehearsal_outcome_report(report: RehearsalOutcomeReport) -> str:
    generated = html_escape(format_dt(report.generated_at))
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '  <meta charset="utf-8">\n'
        '  <meta name="viewport" content="width=device-width, initial-scale=1">\n'
        "  <title>Rehearsal outcome report</title>\n"
        f"{OPERATOR_UI_STYLES}\n"
        "</head>\n"
        "<body>\n"
        '  <main id="operator-rehearsal-outcome-report" data-read-only="true" '
        'data-dry-run-only="true" data-execution-allowed="false" '
        'data-go-live-permitted="false" data-deployment-allowed="false" '
        'data-build-allowed="false" data-artifact-publish-allowed="false" '
        'data-no-execution="true" data-no-go-live="true" '
        'data-no-deployment="true" data-manual-review-only="true" '
        'data-rehearsal-outcome-report-is-not-go-live="true" '
        'data-report-is-not-permission-to-go-live="true" '
        'data-report-is-not-execution="true" '
        'data-go-live-rehearsal-checklist-is-not-go-live="true" '
        'data-rehearsal-is-not-a-script-runner="true" '
        'data-index-is-not-permission-to-go-live="true" '
        'data-dossier-is-not-permission-to-go-live="true" '
        'data-staged-rollout-plan-is-not-go-live="true" '
        'data-provider-setup-checklist-is-not-go-live="true" '
        'data-runbook-is-not-deployment="true" '
        'data-manifest-is-not-a-build-or-deploy="true">\n'
        f"{_render_header(report, generated)}\n"
        f"{render_operator_nav('rehearsal-outcome-report')}\n"
        f"{_render_related_links()}\n"
        f"{_render_live_blocking_flags(report)}\n"
        f"{_render_step_counts(report)}\n"
        f"{_render_expected_assertions(report)}\n"
        f"{_render_remaining_approvals(report)}\n"
        f"{_render_blocker_gate_codes(report)}\n"
        f"{_render_missing_names(report)}\n"
        f"{_render_closed_flags(report)}\n"
        f"{_render_outcome_summary(report)}\n"
        f"{_render_source_references(report)}\n"
        f"{_render_related_inventory(report)}\n"
        f"{_render_local_git(report.local_git)}\n"
        f"{_render_next_actions(report.next_actions)}\n"
        f"{_render_footer(report, generated)}\n"
        "  </main>\n"
        "</body>\n"
        "</html>\n"
    )


def build_operator_rehearsal_outcome_report_response(
    db: Session,
    settings: Settings,
    *,
    service: RehearsalOutcomeReportService | None = None,
) -> HTMLResponse:
    try:
        builder = service or RehearsalOutcomeReportService()
        report = builder.build(db, settings)
        html = render_rehearsal_outcome_report(report)
        return HTMLResponse(content=html, status_code=200, headers=NO_STORE_HEADERS)
    except Exception:
        logger.exception("operator_rehearsal_outcome_report_render_failed", read_only=True)
        return HTMLResponse(
            content=render_rehearsal_outcome_report_error(),
            status_code=500,
            headers=NO_STORE_HEADERS,
        )


def _render_header(report: RehearsalOutcomeReport, generated: str) -> str:
    git = report.local_git
    git_meta = (
        f" · git {html_escape(git.current_branch)}@{html_escape(git.current_sha)}"
        if git.available
        else " · local git unavailable"
    )
    return (
        '    <header class="page-header">\n'
        "      <div>\n"
        "        <h1>Rehearsal outcome report</h1>\n"
        '        <p class="lede">Read-only owner/operator review view of the '
        "existing rehearsal outcome report. Execution remains disabled. "
        "This page does not build, publish, deploy, apply settings, or "
        "lift halt. OUTBOUND_ENABLED=false. go_live_permitted=false. "
        "execution_allowed=false. deployment_allowed=false. "
        "build_allowed=false. artifact_publish_allowed=false. "
        "owner_approved=false. rehearsal_outcome_report_is_not_go_live=true. "
        "report_is_not_permission_to_go_live=true. "
        "report_is_not_execution=true. This page is an outcome report "
        "review view only, not permission to go live and not an "
        "execution surface.</p>\n"
        "      </div>\n"
        f'      <p class="meta">Generated {generated} · overall '
        f"{html_escape(report.overall_status)} · halt "
        f"{html_escape(report.operator_halt_status)} · "
        f"{html_escape(report.packet_kind)} · {html_escape(report.purpose)}"
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
    rehearsal_href = escape(OPERATOR_GO_LIVE_REHEARSAL_CHECKLIST_PATH)
    rehearsal_json_href = escape(GO_LIVE_REHEARSAL_CHECKLIST_JSON_PATH)
    outcome_json_href = escape(REHEARSAL_OUTCOME_REPORT_JSON_PATH)
    pilot_href = escape(OPERATOR_SUPERVISED_PILOT_PLAN_PATH)
    pilot_json_href = escape(SUPERVISED_PILOT_PLAN_JSON_PATH)
    candidates_href = escape(OPERATOR_SUPERVISED_PILOT_CANDIDATES_PATH)
    go_no_go_href = escape(OPERATOR_SUPERVISED_PILOT_GO_NO_GO_PATH)
    first_send_href = escape(OPERATOR_SUPERVISED_PILOT_FIRST_SEND_PREFLIGHT_PATH)
    candidates_json_href = escape(SUPERVISED_PILOT_CANDIDATES_JSON_PATH)
    go_no_go_json_href = escape(SUPERVISED_PILOT_GO_NO_GO_JSON_PATH)
    first_send_json_href = escape(SUPERVISED_PILOT_FIRST_SEND_PREFLIGHT_JSON_PATH)
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
        f'      <a class="nav-link" href="{rehearsal_href}">Go-live rehearsal</a>\n'
        f'      <a class="nav-link" href="{rehearsal_json_href}">JSON rehearsal</a>\n'
        f'      <a class="nav-link" href="{outcome_json_href}">JSON outcome</a>\n'
        f'      <a class="nav-link" href="{pilot_href}">Supervised pilot</a>\n'
        f'      <a class="nav-link" href="{pilot_json_href}">JSON pilot plan</a>\n'
        f'      <a class="nav-link" href="{candidates_href}">Pilot candidates</a>\n'
        f'      <a class="nav-link" href="{candidates_json_href}">JSON candidates</a>\n'
        f'      <a class="nav-link" href="{go_no_go_href}">Pilot go/no-go</a>\n'
        f'      <a class="nav-link" href="{go_no_go_json_href}">JSON go/no-go</a>\n'
        f'      <a class="nav-link" href="{first_send_href}">First-send preflight</a>\n'
        f'      <a class="nav-link" href="{first_send_json_href}">JSON first-send</a>\n'
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


def _render_live_blocking_flags(report: RehearsalOutcomeReport) -> str:
    halt_unchanged = report.operator_halt_before == report.operator_halt_after
    return (
        '    <section class="status-strip" id="live-blocking-flags" '
        'aria-label="Live-blocking flags">\n'
        f"      {metric('Overall', report.overall_status)}\n"
        f"      {metric('OUTBOUND_ENABLED', yes_no(report.outbound_enabled))}\n"
        f"      {metric('Operator halt', report.operator_halt_status)}\n"
        f"      {metric('Live providers', yes_no(report.live_providers_enabled))}\n"
        f"      {metric('Go live permitted', yes_no(report.go_live_permitted))}\n"
        f"      {metric('Execution allowed', yes_no(report.execution_allowed))}\n"
        f"      {metric('Deployment allowed', yes_no(report.deployment_allowed))}\n"
        f"      {metric('Build allowed', yes_no(report.build_allowed))}\n"
        f"      {metric('Artifact publish allowed', yes_no(report.artifact_publish_allowed))}\n"
        f"      {
            metric(
                'Rehearsal outcome report is not go-live',
                yes_no(report.rehearsal_outcome_report_is_not_go_live),
            )
        }\n"
        f"      {
            metric(
                'Report is not permission to go live',
                yes_no(report.report_is_not_permission_to_go_live),
            )
        }\n"
        f"      {metric('Report is not execution', yes_no(report.report_is_not_execution))}\n"
        "    </section>\n"
        '    <section class="panel" id="report-gates">\n'
        "      <h2>Read-only flags and halt proof</h2>\n"
        '      <div class="metric-grid">\n'
        f"        {metric('Packet kind', report.packet_kind)}\n"
        f"        {metric('Purpose', report.purpose)}\n"
        f"        {
            metric('OUTBOUND_ENABLED', 'false' if not report.outbound_enabled else 'true')
        }\n"
        f"        {metric('Operator halt', report.operator_halt_status)}\n"
        f"        {metric('Halt before', report.operator_halt_before)}\n"
        f"        {metric('Halt after', report.operator_halt_after)}\n"
        f"        {metric('Halt unchanged', yes_no(halt_unchanged))}\n"
        f"        {metric('Halt changed', yes_no(report.halt_changed))}\n"
        f"        {metric('Live providers enabled', yes_no(report.live_providers_enabled))}\n"
        f"        {metric('Settings applied', yes_no(report.settings_applied))}\n"
        f"        {metric('Owner approved live', yes_no(report.owner_approved))}\n"
        f"        {metric('Live action', yes_no(report.live_action))}\n"
        f"        {metric('Read only', yes_no(report.read_only))}\n"
        f"        {metric('No execution', yes_no(report.no_execution))}\n"
        f"        {metric('No go-live', yes_no(report.no_go_live))}\n"
        f"        {metric('No deployment', yes_no(report.no_deployment))}\n"
        f"        {metric('Executed', report.executed)}\n"
        "      </div>\n"
        '      <p class="hint">Operator halt before and after must match. '
        "This page never shows secret values, environment values, API keys, "
        "tokens, message bodies, emails, phones, evidence snippets, assertion "
        "expected/observed values, or unsafe error text. OUTBOUND_ENABLED=false. "
        "go_live_permitted=false and execution_allowed=false. This is a "
        "read-only outcome report review view, not permission to go live.</p>\n"
        "    </section>"
    )


def _render_step_counts(report: RehearsalOutcomeReport) -> str:
    return (
        '    <section class="panel" id="rehearsal-step-counts">\n'
        "      <h2>Rehearsal step counts</h2>\n"
        '      <div class="metric-grid">\n'
        f"        {metric('Rehearsal step count', report.rehearsal_step_count)}\n"
        "      </div>\n"
        "      <h3>Counts by status</h3>\n"
        f"      {
            _render_counts(report.rehearsal_step_counts_by_status, empty='No status counts.')
        }\n"
        "      <h3>Counts by kind</h3>\n"
        f"      {_render_counts(report.rehearsal_step_counts_by_kind, empty='No kind counts.')}\n"
        "      <h3>Counts by required owner approval type</h3>\n"
        f"      {
            _render_counts(
                report.rehearsal_step_counts_by_required_owner_approval_type,
                empty='No approval-type counts.',
            )
        }\n"
        "    </section>"
    )


def _render_expected_assertions(report: RehearsalOutcomeReport) -> str:
    return (
        '    <section class="panel" id="expected-safe-assertions">\n'
        "      <h2>Expected safe assertions</h2>\n"
        '      <div class="metric-grid">\n'
        f"        {metric('Assertion count', report.expected_safe_assertion_count)}\n"
        f"        {metric('Passed', report.expected_safe_assertions_passed)}\n"
        f"        {metric('Failed', report.expected_safe_assertions_failed)}\n"
        "      </div>\n"
        "      <h3>Failed safe assertion keys</h3>\n"
        f"      {
            _render_codes(report.failed_safe_assertion_keys, empty='No failed safe assertion keys.')
        }\n"
        '      <p class="hint">Failed assertion keys are names only. Expected '
        "and observed values are never shown.</p>\n"
        "    </section>"
    )


def _render_remaining_approvals(report: RehearsalOutcomeReport) -> str:
    return (
        '    <section class="panel" id="remaining-owner-approvals">\n'
        "      <h2>Remaining owner approval types</h2>\n"
        f"      {
            _render_codes(
                report.remaining_owner_approval_types, empty='No remaining owner approval types.'
            )
        }\n"
        "    </section>"
    )


def _render_blocker_gate_codes(report: RehearsalOutcomeReport) -> str:
    return (
        '    <section class="panel" id="blocker-gate-codes">\n'
        "      <h2>Blocker and gate code rollups</h2>\n"
        "      <h3>Blocker codes</h3>\n"
        f"      {_render_codes(report.blocker_codes, empty='No blocker codes.')}\n"
        "      <h3>Gate codes</h3>\n"
        f"      {_render_codes(report.gate_codes, empty='No gate codes.')}\n"
        "    </section>"
    )


def _render_missing_names(report: RehearsalOutcomeReport) -> str:
    return (
        '    <section class="panel" id="missing-names">\n'
        "      <h2>Missing credential and config names</h2>\n"
        "      <h3>Missing credential names</h3>\n"
        f"      {_render_codes(report.missing_credential_names, empty='None missing.')}\n"
        "      <h3>Missing config names</h3>\n"
        f"      {_render_codes(report.missing_config_names, empty='None missing.')}\n"
        '      <p class="hint">Names only. Values are never shown.</p>\n'
        "    </section>"
    )


def _render_closed_flags(report: RehearsalOutcomeReport) -> str:
    return (
        '    <section class="panel" id="closed-provider-flags">\n'
        "      <h2>Closed provider and live flag names</h2>\n"
        f"      {_render_codes(report.closed_provider_flag_names, empty='None closed.')}\n"
        "    </section>"
    )


def _render_outcome_summary(report: RehearsalOutcomeReport) -> str:
    summary = report.outcome_summary
    body = (
        f'<p class="hint">{html_escape(summary)}</p>'
        if summary
        else '<p class="empty-state">No outcome summary.</p>'
    )
    return (
        '    <section class="panel" id="outcome-summary">\n'
        "      <h2>Outcome summary</h2>\n"
        '      <p class="hint">Sanitized review text only. This summary does '
        "not execute, approve, apply, deploy, or lift halt.</p>\n"
        f"      {body}\n"
        "    </section>"
    )


def _render_source_references(report: RehearsalOutcomeReport) -> str:
    rows = "".join(
        (
            _source_row(
                "Go-live rehearsal checklist",
                report.source_rehearsal_command,
                report.source_rehearsal_route,
                report.source_rehearsal_overall_status,
                report.source_rehearsal_html_route,
            ),
            _source_row(
                "Launch readiness",
                report.source_launch_readiness_command,
                report.source_launch_readiness_route,
                report.source_launch_readiness_overall_status,
                LAUNCH_READINESS_JSON_PATH,
            ),
            _source_row(
                "Go-live readiness index",
                report.source_index_command,
                report.source_index_route,
                report.source_index_overall_status,
                OPERATOR_GO_LIVE_READINESS_INDEX_PATH,
            ),
            _source_row(
                "Launch blockers remediation plan",
                report.source_blockers_plan_command,
                report.source_blockers_plan_route,
                report.source_blockers_plan_overall_status,
                OPERATOR_LAUNCH_BLOCKERS_PLAN_PATH,
            ),
            _source_row(
                "Staged go-live rollout plan",
                report.source_staged_rollout_command,
                report.source_staged_rollout_route,
                report.source_staged_rollout_overall_status,
                OPERATOR_STAGED_ROLLOUT_PLAN_PATH,
            ),
            _source_row(
                "Owner launch dossier",
                report.source_dossier_command,
                report.source_dossier_route,
                report.source_dossier_overall_status,
                OPERATOR_OWNER_LAUNCH_DOSSIER_PATH,
            ),
            _source_row(
                "Provider setup checklist",
                report.source_provider_setup_command,
                report.source_provider_setup_route,
                report.source_provider_setup_overall_status,
                OPERATOR_PROVIDER_SETUP_CHECKLIST_PATH,
            ),
            _source_row(
                "Settings execution preflight",
                report.source_preflight_command,
                report.source_preflight_route,
                report.source_preflight_overall_status,
                OPERATOR_SETTINGS_EXECUTION_PREFLIGHT_PATH,
            ),
        )
    )
    return (
        '    <section class="panel" id="source-references">\n'
        "      <h2>Source references</h2>\n"
        '      <p class="hint">This page reuses the existing Phase 53 '
        "rehearsal outcome report payload. It does not recalculate "
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
        f'<a class="row-link mono" href="{escape(json_route)}">{html_escape(json_route)}</a>'
        if json_route
        else html_escape("—")
    )
    html_cell = (
        f'<a class="row-link mono" href="{escape(html_route)}">{html_escape(html_route)}</a>'
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


def _render_related_inventory(report: RehearsalOutcomeReport) -> str:
    return (
        '    <section class="panel" id="related-routes">\n'
        "      <h2>Related safe routes</h2>\n"
        f"      {_render_route_links(report.related_routes, empty='No related routes.')}\n"
        "    </section>\n"
        '    <section class="panel" id="related-commands">\n'
        "      <h2>Related CLI commands</h2>\n"
        f"      {_render_codes(report.related_commands, empty='No related commands.')}\n"
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


def _render_next_actions(actions: tuple[OutcomeNextAction, ...]) -> str:
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


def _next_action_row(action: OutcomeNextAction) -> str:
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


def _render_footer(report: RehearsalOutcomeReport, generated: str) -> str:
    return (
        '    <footer class="footnote" id="side-effects">\n'
        f"      <p>Generated {generated}. Read-only={yes_no(report.read_only)}. "
        f"Manual review only={yes_no(report.manual_review_only)}. "
        f"Dry-run only={yes_no(report.dry_run_only)}. "
        f"No execution={yes_no(report.no_execution)}. "
        f"No go-live={yes_no(report.no_go_live)}. "
        f"No deployment={yes_no(report.no_deployment)}. "
        f"Executed={html_escape(report.executed)}. "
        f"Settings applied={yes_no(report.settings_applied)}. "
        f"Halt changed={yes_no(report.halt_changed)}. "
        f"Owner approved={yes_no(report.owner_approved)}. "
        f"Live action={yes_no(report.live_action)}. "
        f"Execution allowed={yes_no(report.execution_allowed)}. "
        f"Go live permitted={yes_no(report.go_live_permitted)}. "
        f"Deployment allowed={yes_no(report.deployment_allowed)}. "
        f"Build allowed={yes_no(report.build_allowed)}. "
        f"Artifact publish allowed={yes_no(report.artifact_publish_allowed)}. "
        f"Rehearsal outcome report is not go-live="
        f"{yes_no(report.rehearsal_outcome_report_is_not_go_live)}. "
        f"Report is not permission to go live="
        f"{yes_no(report.report_is_not_permission_to_go_live)}. "
        f"Report is not execution={yes_no(report.report_is_not_execution)}. "
        f"Go-live rehearsal checklist is not go-live="
        f"{yes_no(report.go_live_rehearsal_checklist_is_not_go_live)}. "
        f"Rehearsal is not a script runner="
        f"{yes_no(report.rehearsal_is_not_a_script_runner)}. "
        "There are no apply, execute, lift-halt, enable-outbound, provider, "
        "build, publish, deploy, campaign, booking, call, or spend controls on "
        "this page. This is a read-only outcome report review view, not "
        "permission to go live and not an execution surface. Current route "
        f"{html_escape(OPERATOR_REHEARSAL_OUTCOME_REPORT_PATH)}.</p>\n"
        "    </footer>"
    )


def _render_counts(items: tuple[OutcomeCount, ...], *, empty: str) -> str:
    if not items:
        return f'<p class="empty-state">{escape(empty)}</p>'
    rows = "".join(
        (
            f'<tr class="{_status_class(item.key)}">'
            f'<td class="mono">{html_escape(item.key)}</td>'
            f"<td>{html_escape(item.count)}</td>"
            "</tr>"
        )
        for item in items
    )
    return (
        '<table class="dense"><thead><tr>'
        "<th>Key</th><th>Count</th>"
        f"</tr></thead><tbody>{rows}</tbody></table>"
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
        f'<li class="mono"><a class="row-link" href="{escape(route)}">{html_escape(route)}</a></li>'
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
