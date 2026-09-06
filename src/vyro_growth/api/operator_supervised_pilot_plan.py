"""Read-only operator supervised pilot launch plan HTML shell.

Phase 56 renders a sanitized view of the existing Phase 55 supervised
pilot launch plan. It reuses SupervisedPilotPlanService and never
recalculates readiness. It never executes, builds, publishes, deploys,
applies settings, lifts halt, enables outbound, calls providers, spends,
or changes live state. This page is a supervised pilot planning review
view only, not permission to go live and not an execution surface.
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
from vyro_growth.services.release_artifact_manifest import LocalGitMetadata
from vyro_growth.services.supervised_pilot_plan import (
    PilotAbortCriterion,
    PilotAssertion,
    PilotNextAction,
    PilotPrerequisite,
    PilotRunbookStep,
    PilotScopeRecommendation,
    SupervisedPilotPlan,
    SupervisedPilotPlanService,
)

logger = structlog.get_logger(__name__)


def render_supervised_pilot_plan_error() -> str:
    return render_failure_page(
        page_id="operator-supervised-pilot-plan-error",
        title="Supervised pilot launch plan unavailable",
        heading="Read-only supervised pilot launch plan unavailable",
        banner="Unable to load the supervised pilot launch plan.",
        detail=(
            "The sanitized supervised-pilot review view could not be rendered. "
            "Retry after checking database connectivity and runtime config. "
            "This page is a supervised pilot planning review view only, not "
            "permission to go live and not an execution surface."
        ),
    )


def render_supervised_pilot_plan(plan: SupervisedPilotPlan) -> str:
    generated = html_escape(format_dt(plan.generated_at))
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '  <meta charset="utf-8">\n'
        '  <meta name="viewport" content="width=device-width, initial-scale=1">\n'
        "  <title>Supervised pilot launch plan</title>\n"
        f"{OPERATOR_UI_STYLES}\n"
        "</head>\n"
        "<body>\n"
        '  <main id="operator-supervised-pilot-plan" data-read-only="true" '
        'data-dry-run-only="true" data-execution-allowed="false" '
        'data-go-live-permitted="false" data-deployment-allowed="false" '
        'data-build-allowed="false" data-artifact-publish-allowed="false" '
        'data-spend-allowed="false" data-no-execution="true" '
        'data-no-go-live="true" data-no-deployment="true" '
        'data-no-spend="true" data-manual-review-only="true" '
        'data-supervised-pilot-plan-is-not-go-live="true" '
        'data-plan-is-not-permission-to-go-live="true" '
        'data-plan-is-not-execution="true" '
        'data-rehearsal-outcome-report-is-not-go-live="true" '
        'data-go-live-rehearsal-checklist-is-not-go-live="true" '
        'data-rehearsal-is-not-a-script-runner="true" '
        'data-index-is-not-permission-to-go-live="true" '
        'data-dossier-is-not-permission-to-go-live="true" '
        'data-staged-rollout-plan-is-not-go-live="true" '
        'data-provider-setup-checklist-is-not-go-live="true" '
        'data-runbook-is-not-deployment="true" '
        'data-manifest-is-not-a-build-or-deploy="true">\n'
        f"{_render_header(plan, generated)}\n"
        f"{render_operator_nav('supervised-pilot-plan')}\n"
        f"{_render_related_links()}\n"
        f"{_render_live_blocking_flags(plan)}\n"
        f"{_render_pilot_scope(plan.pilot_scope)}\n"
        f"{_render_prerequisites(plan.prerequisites)}\n"
        f"{_render_safety_assertions(plan)}\n"
        f"{_render_remaining_approvals(plan)}\n"
        f"{_render_blocker_gate_codes(plan)}\n"
        f"{_render_missing_names(plan)}\n"
        f"{_render_closed_flags(plan)}\n"
        f"{_render_runbook_steps(plan.runbook_steps)}\n"
        f"{_render_abort_criteria(plan.abort_criteria)}\n"
        f"{_render_source_references(plan)}\n"
        f"{_render_related_inventory(plan)}\n"
        f"{_render_local_git(plan.local_git)}\n"
        f"{_render_next_actions(plan.next_actions)}\n"
        f"{_render_footer(plan, generated)}\n"
        "  </main>\n"
        "</body>\n"
        "</html>\n"
    )


def build_operator_supervised_pilot_plan_response(
    db: Session,
    settings: Settings,
    *,
    service: SupervisedPilotPlanService | None = None,
) -> HTMLResponse:
    try:
        builder = service or SupervisedPilotPlanService()
        plan = builder.build(db, settings)
        html = render_supervised_pilot_plan(plan)
        return HTMLResponse(content=html, status_code=200, headers=NO_STORE_HEADERS)
    except Exception:
        logger.exception("operator_supervised_pilot_plan_render_failed", read_only=True)
        return HTMLResponse(
            content=render_supervised_pilot_plan_error(),
            status_code=500,
            headers=NO_STORE_HEADERS,
        )


def _render_header(plan: SupervisedPilotPlan, generated: str) -> str:
    git = plan.local_git
    git_meta = (
        f" · git {html_escape(git.current_branch)}@{html_escape(git.current_sha)}"
        if git.available
        else " · local git unavailable"
    )
    return (
        '    <header class="page-header">\n'
        "      <div>\n"
        "        <h1>Supervised pilot launch plan</h1>\n"
        '        <p class="lede">Read-only owner/operator review view of the '
        "existing supervised pilot launch plan. Execution remains disabled. "
        "This page does not build, publish, deploy, apply settings, spend, "
        "or lift halt. OUTBOUND_ENABLED=false. go_live_permitted=false. "
        "execution_allowed=false. deployment_allowed=false. "
        "build_allowed=false. artifact_publish_allowed=false. "
        "spend_allowed=false. owner_approved=false. "
        "supervised_pilot_plan_is_not_go_live=true. "
        "plan_is_not_permission_to_go_live=true. "
        "plan_is_not_execution=true. This page is a supervised pilot "
        "planning review view only, not permission to go live and not an "
        "execution surface.</p>\n"
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
    outcome_href = escape(OPERATOR_REHEARSAL_OUTCOME_REPORT_PATH)
    outcome_json_href = escape(REHEARSAL_OUTCOME_REPORT_JSON_PATH)
    plan_json_href = escape(SUPERVISED_PILOT_PLAN_JSON_PATH)
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
        f'      <a class="nav-link" href="{outcome_href}">Rehearsal outcome</a>\n'
        f'      <a class="nav-link" href="{outcome_json_href}">JSON outcome</a>\n'
        f'      <a class="nav-link" href="{plan_json_href}">JSON pilot plan</a>\n'
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


def _render_live_blocking_flags(plan: SupervisedPilotPlan) -> str:
    halt_unchanged = plan.operator_halt_before == plan.operator_halt_after
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
        f"      {metric('Artifact publish allowed', yes_no(plan.artifact_publish_allowed))}\n"
        f"      {metric('Spend allowed', yes_no(plan.spend_allowed))}\n"
        f"      {
            metric(
                'Supervised pilot plan is not go-live',
                yes_no(plan.supervised_pilot_plan_is_not_go_live),
            )
        }\n"
        f"      {
            metric(
                'Plan is not permission to go live',
                yes_no(plan.plan_is_not_permission_to_go_live),
            )
        }\n"
        f"      {metric('Plan is not execution', yes_no(plan.plan_is_not_execution))}\n"
        "    </section>\n"
        '    <section class="panel" id="plan-gates">\n'
        "      <h2>Read-only flags and halt proof</h2>\n"
        '      <div class="metric-grid">\n'
        f"        {metric('Packet kind', plan.packet_kind)}\n"
        f"        {metric('Purpose', plan.purpose)}\n"
        f"        {metric('OUTBOUND_ENABLED', 'false' if not plan.outbound_enabled else 'true')}\n"
        f"        {metric('Operator halt', plan.operator_halt_status)}\n"
        f"        {metric('Halt before', plan.operator_halt_before)}\n"
        f"        {metric('Halt after', plan.operator_halt_after)}\n"
        f"        {metric('Halt unchanged', yes_no(halt_unchanged))}\n"
        f"        {metric('Halt changed', yes_no(plan.halt_changed))}\n"
        f"        {metric('Live providers enabled', yes_no(plan.live_providers_enabled))}\n"
        f"        {metric('Settings applied', yes_no(plan.settings_applied))}\n"
        f"        {metric('Owner approved live', yes_no(plan.owner_approved))}\n"
        f"        {metric('Live action', yes_no(plan.live_action))}\n"
        f"        {metric('Read only', yes_no(plan.read_only))}\n"
        f"        {metric('No execution', yes_no(plan.no_execution))}\n"
        f"        {metric('No go-live', yes_no(plan.no_go_live))}\n"
        f"        {metric('No deployment', yes_no(plan.no_deployment))}\n"
        f"        {metric('No spend', yes_no(plan.no_spend))}\n"
        f"        {metric('Dry-run only', yes_no(plan.dry_run_only))}\n"
        f"        {metric('Manual review only', yes_no(plan.manual_review_only))}\n"
        f"        {metric('Spend allowed', yes_no(plan.spend_allowed))}\n"
        f"        {metric('Executed', plan.executed)}\n"
        "      </div>\n"
        '      <p class="hint">Operator halt before and after must match. '
        "This page never shows secret values, environment values, API keys, "
        "tokens, message bodies, emails, phones, evidence snippets, assertion "
        "expected/observed values, or unsafe error text. OUTBOUND_ENABLED=false. "
        "go_live_permitted=false and execution_allowed=false. spend_allowed=false. "
        "This is a read-only supervised pilot planning review view, not "
        "permission to go live.</p>\n"
        "    </section>"
    )


def _render_pilot_scope(scope: PilotScopeRecommendation) -> str:
    return (
        '    <section class="panel" id="pilot-scope">\n'
        "      <h2>Safe count-only pilot scope</h2>\n"
        '      <p class="hint">Planning counts only. These limits do not '
        "enroll, send, spend, or execute.</p>\n"
        '      <div class="metric-grid">\n'
        f"        {metric('Suggested max leads', scope.suggested_max_leads)}\n"
        f"        {metric('Suggested max drafts', scope.suggested_max_drafts)}\n"
        f"        {
            metric(
                'Suggested max manually reviewed sends',
                scope.suggested_max_manually_reviewed_sends,
            )
        }\n"
        f"        {metric('Suggested max daily activity', scope.suggested_max_daily_activity)}\n"
        "      </div>\n"
        "      <h3>Stop conditions</h3>\n"
        f"      {_render_codes(scope.stop_conditions, empty='No stop conditions.')}\n"
        f'      <p class="hint">{html_escape(scope.recommendation_summary)}</p>\n'
        "    </section>"
    )


def _render_prerequisites(items: tuple[PilotPrerequisite, ...]) -> str:
    if not items:
        body = '<p class="empty-state">No grouped prerequisites.</p>'
    else:
        body = "".join(_render_prerequisite_card(item) for item in items)
    return (
        '    <section class="panel" id="prerequisites">\n'
        "      <h2>Grouped prerequisites</h2>\n"
        '      <p class="hint">Website, email/domain, outreach, enrichment, '
        "calendar, compliance, owner approvals, and monitoring. Names, "
        "codes, and statuses only. This page does not configure providers "
        "or change live flags.</p>\n"
        f"{body}"
        "    </section>"
    )


def _render_prerequisite_card(item: PilotPrerequisite) -> str:
    return (
        f'      <section class="panel" id="prerequisite-{escape(item.key)}">\n'
        f"        <h3>{html_escape(item.label)}</h3>\n"
        '        <p class="hint">Category '
        f"{html_escape(item.category)} · status {html_escape(item.status)} · "
        f"required owner approval type {html_escape(item.required_owner_approval_type)}</p>\n"
        f'        <p class="hint">{html_escape(item.review_text)}</p>\n'
        "        <h3>Missing credential names</h3>\n"
        f"        {_render_codes(item.missing_credential_names, empty='None missing.')}\n"
        "        <h3>Closed provider flag names</h3>\n"
        f"        {_render_codes(item.closed_provider_flag_names, empty='None closed.')}\n"
        "        <h3>Blocker codes</h3>\n"
        f"        {_render_codes(item.blocker_codes, empty='No blocker codes.')}\n"
        "        <h3>Related commands</h3>\n"
        f"        {_render_codes(item.related_commands, empty='No related commands.')}\n"
        "        <h3>Related routes</h3>\n"
        f"        {_render_route_links(item.related_routes, empty='No related routes.')}\n"
        "      </section>\n"
    )


def _render_safety_assertions(plan: SupervisedPilotPlan) -> str:
    return (
        '    <section class="panel" id="safety-assertions">\n'
        "      <h2>Safety assertions</h2>\n"
        '      <div class="metric-grid">\n'
        f"        {metric('Assertion count', plan.expected_safe_assertion_count)}\n"
        f"        {metric('Passed', plan.expected_safe_assertions_passed)}\n"
        f"        {metric('Failed', plan.expected_safe_assertions_failed)}\n"
        "      </div>\n"
        "      <h3>Assertion keys</h3>\n"
        f"      {_render_assertion_keys(plan.safety_assertions)}\n"
        "      <h3>Failed safe assertion keys</h3>\n"
        f"      {
            _render_codes(plan.failed_safe_assertion_keys, empty='No failed safe assertion keys.')
        }\n"
        '      <p class="hint">Assertion keys and pass/fail only. Expected '
        "and observed values are never shown. Expected safe values include "
        "OUTBOUND_ENABLED=false, go_live_permitted=false, "
        "execution_allowed=false, deployment_allowed=false, "
        "owner_approved=false, halt_changed=false, and spend_allowed=false.</p>\n"
        "    </section>"
    )


def _render_assertion_keys(assertions: tuple[PilotAssertion, ...]) -> str:
    if not assertions:
        return '<p class="empty-state">No safety assertions.</p>'
    rows = "".join(
        (
            f'<tr class="{_status_class("blocked" if not item.passed else "info")}">'
            f'<td class="mono">{html_escape(item.key)}</td>'
            f"<td>{yes_no(item.passed)}</td>"
            "</tr>"
        )
        for item in assertions
    )
    return (
        '<table class="dense"><thead><tr>'
        "<th>Key</th><th>Passed</th>"
        f"</tr></thead><tbody>{rows}</tbody></table>"
    )


def _render_remaining_approvals(plan: SupervisedPilotPlan) -> str:
    return (
        '    <section class="panel" id="remaining-owner-approvals">\n'
        "      <h2>Remaining owner approval types</h2>\n"
        f"      {
            _render_codes(
                plan.remaining_owner_approval_types, empty='No remaining owner approval types.'
            )
        }\n"
        "    </section>"
    )


def _render_blocker_gate_codes(plan: SupervisedPilotPlan) -> str:
    return (
        '    <section class="panel" id="blocker-gate-codes">\n'
        "      <h2>Blocker and gate code rollups</h2>\n"
        "      <h3>Blocker codes</h3>\n"
        f"      {_render_codes(plan.blocker_codes, empty='No blocker codes.')}\n"
        "      <h3>Gate codes</h3>\n"
        f"      {_render_codes(plan.gate_codes, empty='No gate codes.')}\n"
        "    </section>"
    )


def _render_missing_names(plan: SupervisedPilotPlan) -> str:
    return (
        '    <section class="panel" id="missing-names">\n'
        "      <h2>Missing credential and config names</h2>\n"
        "      <h3>Missing credential names</h3>\n"
        f"      {_render_codes(plan.missing_credential_names, empty='None missing.')}\n"
        "      <h3>Missing config names</h3>\n"
        f"      {_render_codes(plan.missing_config_names, empty='None missing.')}\n"
        '      <p class="hint">Names only. Values are never shown.</p>\n'
        "    </section>"
    )


def _render_closed_flags(plan: SupervisedPilotPlan) -> str:
    return (
        '    <section class="panel" id="closed-provider-flags">\n'
        "      <h2>Closed provider and live flag names</h2>\n"
        f"      {_render_codes(plan.closed_provider_flag_names, empty='None closed.')}\n"
        "    </section>"
    )


def _render_runbook_steps(steps: tuple[PilotRunbookStep, ...]) -> str:
    if not steps:
        body = '<p class="empty-state">No manual runbook steps.</p>'
    else:
        body = "".join(_render_step_card(step) for step in steps)
    return (
        '    <section class="panel" id="runbook-steps">\n'
        "      <h2>Manual runbook steps</h2>\n"
        '      <p class="hint">Each card is a Phase 55 runbook step. '
        "Steps are manual instructions only. runnable=false and executed=0. "
        "Command names and routes are references only. This page does not "
        "run commands or change live state.</p>\n"
        f"{body}"
        "    </section>"
    )


def _render_step_card(step: PilotRunbookStep) -> str:
    html_link = (
        f'<a class="nav-link" href="{escape(step.html_route)}">Open HTML</a>'
        if step.html_route
        else ""
    )
    json_link = (
        f'<a class="nav-link" href="{escape(step.json_route)}">JSON</a>' if step.json_route else ""
    )
    command = (
        f'<span class="mono">{html_escape(step.command_name)}</span>'
        if step.command_name
        else html_escape("—")
    )
    return (
        f'      <section class="panel" id="step-{escape(step.step_key)}">\n'
        f"        <h3>{html_escape(step.label)}</h3>\n"
        '        <p class="hint">Status '
        f"{html_escape(step.status)}. {html_link} {json_link} Command {command}</p>\n"
        f'        <p class="hint">{html_escape(step.instruction)}</p>\n'
        '        <div class="metric-grid">\n'
        f"          {metric('Step key', step.step_key)}\n"
        f"          {metric('Runnable', yes_no(step.runnable))}\n"
        f"          {metric('Executed', step.executed)}\n"
        f"          {metric('Config name', step.config_name)}\n"
        "        </div>\n"
        "      </section>\n"
    )


def _render_abort_criteria(notes: tuple[PilotAbortCriterion, ...]) -> str:
    if not notes:
        body = '<p class="empty-state">No abort or rollback criteria.</p>'
    else:
        rows = "".join(_abort_row(note) for note in notes)
        body = (
            '<table class="dense"><thead><tr>'
            "<th>Code</th><th>Label</th><th>Instruction</th>"
            f"</tr></thead><tbody>{rows}</tbody></table>"
        )
    return (
        '    <section class="panel" id="abort-criteria">\n'
        "      <h2>Abort and rollback criteria</h2>\n"
        '      <p class="hint">Review text only. This page does not abort, '
        "roll back, lift halt, apply settings, spend, or change live flags.</p>\n"
        f"      {body}\n"
        "    </section>"
    )


def _abort_row(note: PilotAbortCriterion) -> str:
    return (
        "<tr>"
        f'<td class="mono">{html_escape(note.code)}</td>'
        f"<td>{html_escape(note.label)}</td>"
        f"<td>{html_escape(note.instruction)}</td>"
        "</tr>"
    )


def _render_source_references(plan: SupervisedPilotPlan) -> str:
    rows = "".join(
        (
            _source_row(
                "Rehearsal outcome report",
                plan.source_outcome_command,
                plan.source_outcome_route,
                plan.source_outcome_overall_status,
                plan.source_outcome_html_route,
            ),
            _source_row(
                "Go-live rehearsal checklist",
                plan.source_rehearsal_command,
                plan.source_rehearsal_route,
                plan.source_rehearsal_overall_status,
                plan.source_rehearsal_html_route,
            ),
            _source_row(
                "Launch readiness",
                plan.source_launch_readiness_command,
                plan.source_launch_readiness_route,
                plan.source_launch_readiness_overall_status,
                LAUNCH_READINESS_JSON_PATH,
            ),
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
                "Staged go-live rollout plan",
                plan.source_staged_rollout_command,
                plan.source_staged_rollout_route,
                plan.source_staged_rollout_overall_status,
                OPERATOR_STAGED_ROLLOUT_PLAN_PATH,
            ),
            _source_row(
                "Owner launch dossier",
                plan.source_dossier_command,
                plan.source_dossier_route,
                plan.source_dossier_overall_status,
                OPERATOR_OWNER_LAUNCH_DOSSIER_PATH,
            ),
            _source_row(
                "Provider setup checklist",
                plan.source_provider_setup_command,
                plan.source_provider_setup_route,
                plan.source_provider_setup_overall_status,
                OPERATOR_PROVIDER_SETUP_CHECKLIST_PATH,
            ),
            _source_row(
                "Settings execution preflight",
                plan.source_preflight_command,
                plan.source_preflight_route,
                plan.source_preflight_overall_status,
                OPERATOR_SETTINGS_EXECUTION_PREFLIGHT_PATH,
            ),
        )
    )
    return (
        '    <section class="panel" id="source-references">\n'
        "      <h2>Source references</h2>\n"
        '      <p class="hint">This page reuses the existing Phase 55 '
        "supervised pilot launch plan payload. It does not recalculate "
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


def _render_related_inventory(plan: SupervisedPilotPlan) -> str:
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


def _render_next_actions(actions: tuple[PilotNextAction, ...]) -> str:
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
        "not execute, approve, apply, deploy, spend, or lift halt.</p>\n"
        f"      {body}\n"
        "    </section>"
    )


def _next_action_row(action: PilotNextAction) -> str:
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


def _render_footer(plan: SupervisedPilotPlan, generated: str) -> str:
    return (
        '    <footer class="footnote" id="side-effects">\n'
        f"      <p>Generated {generated}. Read-only={yes_no(plan.read_only)}. "
        f"Manual review only={yes_no(plan.manual_review_only)}. "
        f"Dry-run only={yes_no(plan.dry_run_only)}. "
        f"No execution={yes_no(plan.no_execution)}. "
        f"No go-live={yes_no(plan.no_go_live)}. "
        f"No deployment={yes_no(plan.no_deployment)}. "
        f"No spend={yes_no(plan.no_spend)}. "
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
        f"Spend allowed={yes_no(plan.spend_allowed)}. "
        f"Supervised pilot plan is not go-live="
        f"{yes_no(plan.supervised_pilot_plan_is_not_go_live)}. "
        f"Plan is not permission to go live="
        f"{yes_no(plan.plan_is_not_permission_to_go_live)}. "
        f"Plan is not execution={yes_no(plan.plan_is_not_execution)}. "
        f"Rehearsal outcome report is not go-live="
        f"{yes_no(plan.rehearsal_outcome_report_is_not_go_live)}. "
        f"Go-live rehearsal checklist is not go-live="
        f"{yes_no(plan.go_live_rehearsal_checklist_is_not_go_live)}. "
        f"Rehearsal is not a script runner="
        f"{yes_no(plan.rehearsal_is_not_a_script_runner)}. "
        "There are no apply, execute, lift-halt, enable-outbound, provider, "
        "build, publish, deploy, campaign, booking, call, or spend controls on "
        "this page. This is a read-only supervised pilot planning review view, "
        "not permission to go live and not an execution surface. Current route "
        f"{html_escape(OPERATOR_SUPERVISED_PILOT_PLAN_PATH)}.</p>\n"
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
