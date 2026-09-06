"""Read-only release-candidate deployment runbook HTML shell.

Phase 38 renders the Phase 37 release-candidate runbook as an internal
HTML page. It never deploys, applies settings, lifts halt, enables
outbound, executes requests, packets, or approved items, sets live
owner-approved state, or performs any live action. This page is not a
deployment mechanism or permission to go live.
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
    OPERATOR_RELEASE_ARTIFACT_MANIFEST_PATH,
    OPERATOR_SETTINGS_EXECUTION_PREFLIGHT_PATH,
    OPERATOR_STAGED_ROLLOUT_PLAN_PATH,
    OPERATOR_UI_STYLES,
    RELEASE_CANDIDATE_RUNBOOK_JSON_PATH,
    format_dt,
    html_escape,
    metric,
    render_failure_page,
    render_operator_nav,
    titleize,
    yes_no,
)
from vyro_growth.api.release_candidate_runbook import (
    ReleaseCandidateRunbookResponse,
    RunbookChecklistItemResponse,
    RunbookCiAndLocalVerificationResponse,
    RunbookCiGateResponse,
    RunbookGuardrailDocResponse,
    RunbookHaltVerificationResponse,
    RunbookIdentityResponse,
    RunbookInstructionStepResponse,
    RunbookReusedSummariesResponse,
    RunbookSafeDefaultsResponse,
    build_release_candidate_runbook_response,
)
from vyro_growth.config import Settings
from vyro_growth.domain import FindingSeverity
from vyro_growth.services.release_candidate_runbook import ReleaseCandidateRunbookService

logger = structlog.get_logger(__name__)


def render_release_candidate_runbook_error() -> str:
    return render_failure_page(
        page_id="operator-release-candidate-runbook-error",
        title="Release-candidate runbook unavailable",
        heading="Read-only release-candidate runbook unavailable",
        banner="Unable to load the release-candidate deployment runbook.",
        detail=(
            "The sanitized owner-review runbook could not be rendered. "
            "Retry after checking database connectivity and runtime config. "
            "This page is not a deployment mechanism or permission to go live."
        ),
    )


def render_release_candidate_runbook(runbook: ReleaseCandidateRunbookResponse) -> str:
    generated = html_escape(format_dt(runbook.generated_at))
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '  <meta charset="utf-8">\n'
        '  <meta name="viewport" content="width=device-width, initial-scale=1">\n'
        "  <title>Release-candidate deployment runbook</title>\n"
        f"{OPERATOR_UI_STYLES}\n"
        "</head>\n"
        "<body>\n"
        '  <main id="operator-release-candidate-runbook" data-read-only="true" '
        'data-dry-run-only="true" data-execution-allowed="false" '
        'data-go-live-permitted="false" data-deployment-allowed="false" '
        'data-no-execution="true" data-manual-review-only="true" '
        'data-runbook-is-not-deployment="true">\n'
        f"{_render_header(runbook, generated)}\n"
        f"{render_operator_nav('release-candidate-runbook')}\n"
        f"{_render_related_links()}\n"
        f"{_render_overall(runbook)}\n"
        f"{_render_identity(runbook.release_candidate_identity)}\n"
        f"{_render_ci_and_local(runbook.ci_gates_and_local_verification)}\n"
        f"{_render_safe_defaults(runbook.safe_environment_defaults)}\n"
        f"{_render_halt(runbook.operator_halt_and_outbound)}\n"
        f"{_render_instruction_steps(
            'manual-deployment-sequence',
            'Manual deployment sequence (instructions only)',
            runbook.manual_deployment_sequence,
            empty=(
                'No manual deployment instructions. This page does not deploy '
                'or execute anything.'
            ),
        )}\n"
        f"{_render_instruction_steps(
            'rollback-checklist',
            'Rollback checklist (instructions only)',
            runbook.rollback_checklist,
            empty=(
                'No rollback checklist items. This page does not roll back, '
                'deploy, or execute anything.'
            ),
        )}\n"
        f"{_render_instruction_steps(
            'post-deploy-verification',
            'Post-deploy read-only verification',
            runbook.post_deploy_verification,
            empty=(
                'No post-deploy verification steps. This page does not deploy '
                'or execute anything.'
            ),
        )}\n"
        f"{_render_guardrails(runbook.documented_guardrails)}\n"
        f"{_render_reused_summaries(runbook.reused_summaries)}\n"
        f"{_render_checklist(runbook.remaining_manual_owner_checklist)}\n"
        f"{_render_footer(runbook, generated)}\n"
        "  </main>\n"
        "</body>\n"
        "</html>\n"
    )


def build_operator_release_candidate_runbook_response(
    db: Session,
    settings: Settings,
    *,
    service: ReleaseCandidateRunbookService | None = None,
) -> HTMLResponse:
    try:
        runbook = build_release_candidate_runbook_response(db, settings, service=service)
        html = render_release_candidate_runbook(runbook)
        return HTMLResponse(content=html, status_code=200, headers=NO_STORE_HEADERS)
    except Exception:
        logger.exception("operator_release_candidate_runbook_render_failed", read_only=True)
        return HTMLResponse(
            content=render_release_candidate_runbook_error(),
            status_code=500,
            headers=NO_STORE_HEADERS,
        )


def _render_header(runbook: ReleaseCandidateRunbookResponse, generated: str) -> str:
    return (
        '    <header class="page-header">\n'
        "      <div>\n"
        "        <h1>Release-candidate deployment runbook</h1>\n"
        '        <p class="lede">Read-only owner-review view of the future manual '
        "deployment plan. Execution remains disabled. This page does not deploy. "
        "go_live_permitted=false. execution_allowed=false. "
        "deployment_allowed=false. runbook_is_not_deployment=true. This page is "
        "not a deployment mechanism or permission to go live.</p>\n"
        "      </div>\n"
        f'      <p class="meta">Generated {generated} · overall '
        f"{html_escape(runbook.overall_status)} · halt "
        f"{html_escape(runbook.operator_halt_status)} · "
        f"{html_escape(runbook.packet_kind)} · {html_escape(runbook.purpose)}</p>\n"
        "    </header>"
    )


def _render_related_links() -> str:
    json_href = escape(RELEASE_CANDIDATE_RUNBOOK_JSON_PATH)
    binder_href = escape(OPERATOR_COMPLIANCE_EVIDENCE_BINDER_PATH)
    binder_json_href = escape(COMPLIANCE_EVIDENCE_BINDER_JSON_PATH)
    launch_href = escape(LAUNCH_READINESS_JSON_PATH)
    preflight_href = escape(OPERATOR_SETTINGS_EXECUTION_PREFLIGHT_PATH)
    handoff_href = escape(OPERATOR_OWNER_HANDOFF_PACKET_PATH)
    timeline_href = escape(OPERATOR_AUDIT_TIMELINE_PATH)
    manifest_href = escape(OPERATOR_RELEASE_ARTIFACT_MANIFEST_PATH)
    index_href = escape(OPERATOR_GO_LIVE_READINESS_INDEX_PATH)
    plan_href = escape(OPERATOR_LAUNCH_BLOCKERS_PLAN_PATH)
    staged_href = escape(OPERATOR_STAGED_ROLLOUT_PLAN_PATH)
    dossier_href = escape(OPERATOR_OWNER_LAUNCH_DOSSIER_PATH)
    checklist_href = escape(OPERATOR_PROVIDER_SETUP_CHECKLIST_PATH)
    rehearsal_href = escape(OPERATOR_GO_LIVE_REHEARSAL_CHECKLIST_PATH)
    outcome_href = escape(OPERATOR_REHEARSAL_OUTCOME_REPORT_PATH)
    return (
        '    <nav class="filter-nav" aria-label="Related read-only surfaces">\n'
        f'      <a class="nav-link nav-json" href="{json_href}">JSON runbook</a>\n'
        f'      <a class="nav-link" href="{binder_href}">Compliance binder</a>\n'
        f'      <a class="nav-link" href="{binder_json_href}">JSON binder</a>\n'
        f'      <a class="nav-link" href="{launch_href}">Launch readiness JSON</a>\n'
        f'      <a class="nav-link" href="{preflight_href}">Settings preflight</a>\n'
        f'      <a class="nav-link" href="{handoff_href}">Owner handoff</a>\n'
        f'      <a class="nav-link" href="{timeline_href}">Audit timeline</a>\n'
        f'      <a class="nav-link" href="{manifest_href}">Release manifest</a>\n'
        f'      <a class="nav-link" href="{index_href}">Go-live index</a>\n'
        f'      <a class="nav-link" href="{plan_href}">Launch blockers</a>\n'
        f'      <a class="nav-link" href="{staged_href}">Staged rollout</a>\n'
        f'      <a class="nav-link" href="{dossier_href}">Owner launch dossier</a>\n'
        f'      <a class="nav-link" href="{checklist_href}">Provider setup</a>\n'
        f'      <a class="nav-link" href="{rehearsal_href}">Go-live rehearsal</a>\n'
        f'      <a class="nav-link" href="{outcome_href}">Rehearsal outcome</a>\n'
        "    </nav>"
    )


def _render_overall(runbook: ReleaseCandidateRunbookResponse) -> str:
    return (
        '    <section class="status-strip" aria-label="Runbook flags">\n'
        f"      {metric('Overall', runbook.overall_status)}\n"
        f"      {metric('Go live permitted', yes_no(runbook.go_live_permitted))}\n"
        f"      {metric('Execution allowed', yes_no(runbook.execution_allowed))}\n"
        f"      {metric('Deployment allowed', yes_no(runbook.deployment_allowed))}\n"
        f"      {metric('Runbook is not deployment',
            yes_no(runbook.runbook_is_not_deployment))}\n"
        f"      {metric('Manual review only', yes_no(runbook.manual_review_only))}\n"
        f"      {metric('Read only', yes_no(runbook.read_only))}\n"
        f"      {metric('Dry-run only', yes_no(runbook.dry_run_only))}\n"
        f"      {metric('No execution', yes_no(runbook.no_execution))}\n"
        f"      {metric('Executed', runbook.executed)}\n"
        "    </section>\n"
        '    <section class="panel" id="runbook-gates">\n'
        "      <h2>Manual-review gates</h2>\n"
        '      <div class="metric-grid">\n'
        f"        {metric('Outbound enabled', yes_no(runbook.outbound_enabled))}\n"
        f"        {metric('Live providers', yes_no(runbook.live_providers_enabled))}\n"
        f"        {metric('Operator halt', runbook.operator_halt_status)}\n"
        f"        {metric('Halt before', runbook.operator_halt_before)}\n"
        f"        {metric('Halt after', runbook.operator_halt_after)}\n"
        f"        {metric('Halt changed', yes_no(runbook.halt_changed))}\n"
        f"        {metric('Settings applied', yes_no(runbook.settings_applied))}\n"
        f"        {metric('Owner approved live', yes_no(runbook.owner_approved))}\n"
        f"        {metric('Live action', yes_no(runbook.live_action))}\n"
        f"        {metric('Deployed', yes_no(runbook.deployed))}\n"
        f"        {metric('Deployment attempted', yes_no(runbook.deployment_attempted))}\n"
        f"        {metric('Future execution phase',
            yes_no(runbook.future_execution_phase_exists))}\n"
        f"        {metric('Future deployment phase',
            yes_no(runbook.future_deployment_phase_exists))}\n"
        f"        {metric('Outbound attempted', yes_no(runbook.outbound_attempted))}\n"
        f"        {metric('Spend attempted', yes_no(runbook.spend_attempted))}\n"
        f"        {metric('CLI command', runbook.cli_command)}\n"
        f"        {metric('HTTP route', runbook.http_route)}\n"
        "      </div>\n"
        "      <h3>Blocker codes</h3>\n"
        f"      {_render_codes(runbook.blocker_codes, empty='No blocker codes.')}\n"
        "      <h3>Missing credential variable names</h3>\n"
        f"      {_render_codes(runbook.missing_credential_names, empty='None missing.')}\n"
        "      <h3>Closed provider flag names</h3>\n"
        f"      {_render_codes(runbook.closed_provider_flag_names, empty='None closed.')}\n"
        "      <h3>Related commands</h3>\n"
        f"      {_render_codes(runbook.related_commands, empty='No related commands.')}\n"
        "      <h3>Related routes</h3>\n"
        f"      {_render_codes(runbook.related_routes, empty='No related routes.')}\n"
        '      <p class="hint">This page never shows secret values, environment '
        "values, API keys, tokens, message bodies, emails, phones, evidence "
        "snippets, or unsafe error text. go_live_permitted=false, "
        "execution_allowed=false, deployment_allowed=false, and "
        "runbook_is_not_deployment=true. This is a read-only owner-review view, "
        "not a deployment mechanism or permission to go live.</p>\n"
        "    </section>"
    )


def _render_identity(identity: RunbookIdentityResponse) -> str:
    return (
        '    <section class="panel" id="release-candidate-identity">\n'
        "      <h2>Release candidate identity and repo branch expectations</h2>\n"
        '      <div class="metric-grid">\n'
        f"        {metric('Expected base branch', identity.expected_base_branch)}\n"
        f"        {metric('Expected workflow path', identity.expected_workflow_path)}\n"
        f"        {metric('Expected release channel', identity.expected_release_channel)}\n"
        f"        {metric('Git provider called', yes_no(identity.git_provider_called))}\n"
        f"        {metric('Deployment from runbook',
            yes_no(identity.deployment_from_runbook))}\n"
        "      </div>\n"
        '      <p class="hint">This identity is documentary only. The page does '
        "not call GitHub Actions or deploy from this runbook.</p>\n"
        "    </section>"
    )


def _render_ci_and_local(evidence: RunbookCiAndLocalVerificationResponse) -> str:
    return (
        '    <section class="panel" id="ci-gates-and-local-verification">\n'
        "      <h2>Required CI gates and local dry-run verification commands</h2>\n"
        "      <h3>Required CI job names</h3>\n"
        f"      {_render_codes(evidence.required_ci_job_names, empty='No CI job names.')}\n"
        "      <h3>Smoke-dry-run gate</h3>\n"
        f"      {_render_gate(evidence.smoke_gate)}\n"
        "      <h3>Deploy-config gate</h3>\n"
        f"      {_render_gate(evidence.deploy_config_gate)}\n"
        "      <h3>Local verification commands</h3>\n"
        f"      {_render_codes(
            evidence.local_verification_commands, empty='No local verification commands.'
        )}\n"
        '      <div class="metric-grid">\n'
        f"        {metric('GitHub Actions called',
            yes_no(evidence.github_actions_called))}\n"
        "      </div>\n"
        '      <p class="hint">Commands are listed for owner review only. This '
        "page does not run CI, call GitHub Actions, or deploy.</p>\n"
        "    </section>"
    )


def _render_gate(status: RunbookCiGateResponse) -> str:
    return (
        '<div class="metric-grid">\n'
        f"        {metric('Present', yes_no(status.present))}\n"
        f"        {metric('Documented', yes_no(status.documented))}\n"
        f"        {metric('Job name', status.job_name)}\n"
        f"        {metric('Command name', status.command_name)}\n"
        "      </div>"
    )


def _render_safe_defaults(defaults: RunbookSafeDefaultsResponse) -> str:
    return (
        '    <section class="panel" id="safe-environment-defaults">\n'
        "      <h2>Required safe environment defaults</h2>\n"
        '      <div class="metric-grid">\n'
        f"        {metric('Outbound enabled required',
            yes_no(defaults.outbound_enabled_required))}\n"
        f"        {metric('Outbound enabled', yes_no(defaults.outbound_enabled))}\n"
        f"        {metric('Live providers', yes_no(defaults.live_providers_enabled))}\n"
        f"        {metric('.env.example defaults',
            yes_no(defaults.env_example_defaults_present))}\n"
        f"        {metric('Dockerfile defaults',
            yes_no(defaults.dockerfile_defaults_present))}\n"
        f"        {metric('Compose defaults', yes_no(defaults.compose_defaults_present))}\n"
        f"        {metric('Secret values included',
            yes_no(defaults.secret_values_included))}\n"
        "      </div>\n"
        "      <h3>Required flag names</h3>\n"
        f"      {_render_codes(defaults.required_flag_names, empty='None required.')}\n"
        "      <h3>Closed provider flag names</h3>\n"
        f"      {_render_codes(defaults.closed_provider_flag_names, empty='None closed.')}\n"
        "      <h3>Missing credential variable names</h3>\n"
        f"      {_render_codes(defaults.missing_credential_names, empty='None missing.')}\n"
        '      <p class="hint">Only flag names, states, and missing credential '
        "variable names are shown. Secret values and raw environment values are "
        "never included. OUTBOUND_ENABLED remains false by default.</p>\n"
        "    </section>"
    )


def _render_halt(evidence: RunbookHaltVerificationResponse) -> str:
    return (
        '    <section class="panel" id="operator-halt-and-outbound">\n'
        "      <h2>Operator halt and outbound-disabled verification</h2>\n"
        '      <div class="metric-grid">\n'
        f"        {metric('Outbound enabled', yes_no(evidence.outbound_enabled))}\n"
        f"        {metric('Operator halt', evidence.operator_halt_status)}\n"
        f"        {metric('Halt before', evidence.operator_halt_before)}\n"
        f"        {metric('Halt after', evidence.operator_halt_after)}\n"
        f"        {metric('Halt changed', yes_no(evidence.halt_changed))}\n"
        f"        {metric('Keep outbound disabled',
            yes_no(evidence.keep_outbound_disabled))}\n"
        "      </div>\n"
        "      <h3>Verification commands</h3>\n"
        f"      {_render_codes(
            evidence.verification_commands, empty='No verification commands.'
        )}\n"
        "      <h3>Verification routes</h3>\n"
        f"      {_render_codes(evidence.verification_routes, empty='No verification routes.')}\n"
        '      <p class="hint">Operator halt is read and left unchanged. This '
        "page does not lift halt or enable outbound.</p>\n"
        "    </section>"
    )


def _render_instruction_steps(
    section_id: str,
    heading: str,
    items: list[RunbookInstructionStepResponse],
    *,
    empty: str,
) -> str:
    if not items:
        return (
            f'    <section class="panel" id="{escape(section_id)}">\n'
            f"      <h2>{escape(heading)}</h2>\n"
            f'      <p class="empty-state" id="empty-{escape(section_id)}">'
            f"{escape(empty)}</p>\n"
            "    </section>"
        )
    rows = "".join(_instruction_row(item) for item in items)
    return (
        f'    <section class="panel" id="{escape(section_id)}">\n'
        f"      <h2>{escape(heading)}</h2>\n"
        '      <table class="dense"><thead><tr>'
        "<th>Code</th><th>Instruction</th><th>Command</th><th>Route</th>"
        f"</tr></thead><tbody>{rows}</tbody></table>\n"
        '      <p class="hint">Instructions only. This page has no deploy, '
        "execute, apply, or rollback control.</p>\n"
        "    </section>"
    )


def _instruction_row(item: RunbookInstructionStepResponse) -> str:
    return (
        "<tr>"
        f'<td class="mono">{html_escape(item.code)}</td>'
        f"<td>{html_escape(item.instruction)}</td>"
        f'<td class="mono">{html_escape(item.command_name)}</td>'
        f'<td class="mono">{html_escape(item.route_name)}</td>'
        "</tr>"
    )


def _render_guardrails(items: list[RunbookGuardrailDocResponse]) -> str:
    if not items:
        return (
            '    <section class="panel" id="documented-guardrails">\n'
            "      <h2>Documented compliance guardrails</h2>\n"
            '      <p class="empty-state" id="empty-documented-guardrails">'
            "No documented guardrail files were inspected. This page does not "
            "edit docs or execute anything.</p>\n"
            "    </section>"
        )
    rows = "".join(_guardrail_row(item) for item in items)
    return (
        '    <section class="panel" id="documented-guardrails">\n'
        "      <h2>Documented compliance guardrails</h2>\n"
        '      <table class="dense"><thead><tr>'
        "<th>Path</th><th>Present</th><th>Documented codes</th>"
        f"</tr></thead><tbody>{rows}</tbody></table>\n"
        "    </section>"
    )


def _guardrail_row(item: RunbookGuardrailDocResponse) -> str:
    codes = ", ".join(item.documented_codes) if item.documented_codes else "—"
    return (
        "<tr>"
        f'<td class="mono">{html_escape(item.path)}</td>'
        f"<td>{yes_no(item.present)}</td>"
        f'<td class="mono">{html_escape(codes)}</td>'
        "</tr>"
    )


def _render_reused_summaries(evidence: RunbookReusedSummariesResponse) -> str:
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
        f"        {metric('Audit timeline matching', evidence.audit_timeline_matching_count)}\n"
        f"        {metric('Audit timeline route', evidence.audit_timeline_route)}\n"
        "      </div>\n"
        "      <h3>Launch readiness blocker codes</h3>\n"
        f"      {_render_codes(
            evidence.launch_readiness_blocker_codes, empty='No blocker codes.'
        )}\n"
        "    </section>"
    )


def _render_checklist(items: list[RunbookChecklistItemResponse]) -> str:
    if not items:
        return (
            '    <section class="panel" id="remaining-manual-owner-checklist">\n'
            "      <h2>Remaining unresolved blockers and manual owner checklist</h2>\n"
            '      <p class="empty-state" id="empty-remaining-manual-owner-checklist">'
            "No remaining checklist items. This page still does not permit "
            "deploying, going live, or executing anything.</p>\n"
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


def _checklist_row(item: RunbookChecklistItemResponse) -> str:
    return (
        f'<tr class="{_severity_class(item.severity)}">'
        f'<td class="mono">{html_escape(item.code)}</td>'
        f"<td>{html_escape(item.severity)}</td>"
        f"<td>{titleize(item.source_section)}</td>"
        f"<td>{html_escape(item.status)}</td>"
        "</tr>"
    )


def _render_footer(runbook: ReleaseCandidateRunbookResponse, generated: str) -> str:
    return (
        '    <footer class="footnote" id="side-effects">\n'
        f"      <p>Generated {generated}. Read-only={yes_no(runbook.read_only)}. "
        f"Manual review only={yes_no(runbook.manual_review_only)}. "
        f"Dry-run only={yes_no(runbook.dry_run_only)}. "
        f"No execution={yes_no(runbook.no_execution)}. "
        f"Executed={html_escape(runbook.executed)}. "
        f"Settings applied={yes_no(runbook.settings_applied)}. "
        f"Halt changed={yes_no(runbook.halt_changed)}. "
        f"Owner approved={yes_no(runbook.owner_approved)}. "
        f"Live action={yes_no(runbook.live_action)}. "
        f"Execution allowed={yes_no(runbook.execution_allowed)}. "
        f"Go live permitted={yes_no(runbook.go_live_permitted)}. "
        f"Deployment allowed={yes_no(runbook.deployment_allowed)}. "
        f"Deployment attempted={yes_no(runbook.deployment_attempted)}. "
        f"Deployed={yes_no(runbook.deployed)}. "
        f"Runbook is not deployment={yes_no(runbook.runbook_is_not_deployment)}. "
        f"Future execution phase exists="
        f"{yes_no(runbook.future_execution_phase_exists)}. "
        f"Future deployment phase exists="
        f"{yes_no(runbook.future_deployment_phase_exists)}. "
        "There are no apply, execute, lift-halt, enable-outbound, provider, "
        "deploy, campaign, booking, call, publish, or spend controls on this "
        "page. This is a read-only owner-review view, not a deployment "
        "mechanism or permission to go live.</p>\n"
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
    raise RuntimeError(f"unhandled release candidate runbook checklist severity: {value!r}")
