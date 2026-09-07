"""Read-only compliance evidence binder HTML shell.

Phase 36 renders the Phase 35 compliance evidence binder as an internal
HTML page. It never applies settings, lifts halt, enables outbound,
executes requests, packets, or approved items, sets live owner-approved
state, or performs any live action. This page is not permission or
machinery for going live.
"""

from __future__ import annotations

from html import escape
from typing import Never

import structlog
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from vyro_growth.api.compliance_evidence_binder import (
    AuditTimelineEntryEvidenceResponse,
    AuditTimelineEvidenceResponse,
    BinderChecklistItemResponse,
    CiGateEvidenceResponse,
    CiGateStatusResponse,
    ComplianceEvidenceBinderResponse,
    ConsentPhoneEvidenceResponse,
    GuardrailDocEvidenceResponse,
    LiveProviderDefaultEvidenceResponse,
    NoExecutionEvidenceResponse,
    OutboundHaltEvidenceResponse,
    RedactionEvidenceResponse,
    ReusedSummaryEvidenceResponse,
    SecretPresenceItemResponse,
    build_compliance_evidence_binder_response,
)
from vyro_growth.api.operator_ui import (
    COMPLIANCE_EVIDENCE_BINDER_JSON_PATH,
    LAUNCH_READINESS_JSON_PATH,
    NO_STORE_HEADERS,
    OPERATOR_AUDIT_TIMELINE_PATH,
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
from vyro_growth.services.compliance_evidence_binder import ComplianceEvidenceBinderService

logger = structlog.get_logger(__name__)


def render_compliance_evidence_binder_error() -> str:
    return render_failure_page(
        page_id="operator-compliance-evidence-binder-error",
        title="Compliance evidence binder unavailable",
        heading="Read-only compliance evidence binder unavailable",
        banner="Unable to load the compliance evidence binder.",
        detail=(
            "The sanitized owner-review binder could not be rendered. "
            "Retry after checking database connectivity and runtime config. "
            "This page is not permission or machinery for going live."
        ),
    )


def render_compliance_evidence_binder(binder: ComplianceEvidenceBinderResponse) -> str:
    generated = html_escape(format_dt(binder.generated_at))
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '  <meta charset="utf-8">\n'
        '  <meta name="viewport" content="width=device-width, initial-scale=1">\n'
        "  <title>Compliance evidence binder</title>\n"
        f"{OPERATOR_UI_STYLES}\n"
        "</head>\n"
        "<body>\n"
        '  <main id="operator-compliance-evidence-binder" data-read-only="true" '
        'data-dry-run-only="true" data-execution-allowed="false" '
        'data-go-live-permitted="false" data-no-execution="true" '
        'data-manual-review-only="true" data-binder-is-not-go-live="true">\n'
        f"{_render_header(binder, generated)}\n"
        f"{render_operator_nav('compliance-evidence-binder')}\n"
        f"{_render_related_links()}\n"
        f"{_render_overall(binder)}\n"
        f"{_render_outbound_and_halt(binder.outbound_and_halt)}\n"
        f"{_render_live_provider_defaults(binder.live_provider_defaults)}\n"
        f"{_render_no_execution(binder.no_execution_side_effects)}\n"
        f"{_render_redaction(binder.phi_secrets_redaction)}\n"
        f"{_render_consent(binder.consent_phone_boundary)}\n"
        f"{_render_ci_gates(binder.ci_gates)}\n"
        f"{_render_guardrails(binder.documented_guardrails)}\n"
        f"{_render_audit_timeline(binder.operator_audit_timeline)}\n"
        f"{_render_reused_summaries(binder.reused_summaries)}\n"
        f"{_render_checklist(binder.remaining_manual_owner_checklist)}\n"
        f"{_render_footer(binder, generated)}\n"
        "  </main>\n"
        "</body>\n"
        "</html>\n"
    )


def build_operator_compliance_evidence_binder_response(
    db: Session,
    settings: Settings,
    *,
    service: ComplianceEvidenceBinderService | None = None,
) -> HTMLResponse:
    try:
        binder = build_compliance_evidence_binder_response(db, settings, service=service)
        html = render_compliance_evidence_binder(binder)
        return HTMLResponse(content=html, status_code=200, headers=NO_STORE_HEADERS)
    except Exception:
        logger.exception("operator_compliance_evidence_binder_render_failed", read_only=True)
        return HTMLResponse(
            content=render_compliance_evidence_binder_error(),
            status_code=500,
            headers=NO_STORE_HEADERS,
        )


def _render_header(binder: ComplianceEvidenceBinderResponse, generated: str) -> str:
    return (
        '    <header class="page-header">\n'
        "      <div>\n"
        "        <h1>Compliance evidence binder</h1>\n"
        '        <p class="lede">Read-only owner-review view of the consolidated '
        "compliance evidence binder. Execution remains disabled. "
        "go_live_permitted=false. execution_allowed=false. "
        "binder_is_not_go_live=true. This page is not permission or machinery "
        "for going live.</p>\n"
        "      </div>\n"
        f'      <p class="meta">Generated {generated} · overall '
        f"{html_escape(binder.overall_status)} · halt "
        f"{html_escape(binder.operator_halt_status)} · "
        f"{html_escape(binder.packet_kind)} · {html_escape(binder.purpose)}</p>\n"
        "    </header>"
    )


def _render_related_links() -> str:
    json_href = escape(COMPLIANCE_EVIDENCE_BINDER_JSON_PATH)
    launch_href = escape(LAUNCH_READINESS_JSON_PATH)
    preflight_href = escape(OPERATOR_SETTINGS_EXECUTION_PREFLIGHT_PATH)
    handoff_href = escape(OPERATOR_OWNER_HANDOFF_PACKET_PATH)
    timeline_href = escape(OPERATOR_AUDIT_TIMELINE_PATH)
    runbook_href = escape(OPERATOR_RELEASE_CANDIDATE_RUNBOOK_PATH)
    manifest_href = escape(OPERATOR_RELEASE_ARTIFACT_MANIFEST_PATH)
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
    return (
        '    <nav class="filter-nav" aria-label="Related read-only surfaces">\n'
        f'      <a class="nav-link nav-json" href="{json_href}">JSON binder</a>\n'
        f'      <a class="nav-link" href="{launch_href}">Launch readiness JSON</a>\n'
        f'      <a class="nav-link" href="{preflight_href}">Settings preflight</a>\n'
        f'      <a class="nav-link" href="{handoff_href}">Owner handoff</a>\n'
        f'      <a class="nav-link" href="{timeline_href}">Audit timeline</a>\n'
        f'      <a class="nav-link" href="{runbook_href}">Release runbook</a>\n'
        f'      <a class="nav-link" href="{manifest_href}">Release manifest</a>\n'
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
        "    </nav>"
    )


def _render_overall(binder: ComplianceEvidenceBinderResponse) -> str:
    return (
        '    <section class="status-strip" aria-label="Binder flags">\n'
        f"      {metric('Overall', binder.overall_status)}\n"
        f"      {metric('Go live permitted', yes_no(binder.go_live_permitted))}\n"
        f"      {metric('Execution allowed', yes_no(binder.execution_allowed))}\n"
        f"      {metric('Binder is not go-live', yes_no(binder.binder_is_not_go_live))}\n"
        f"      {metric('Manual review only', yes_no(binder.manual_review_only))}\n"
        f"      {metric('Read only', yes_no(binder.read_only))}\n"
        f"      {metric('Dry-run only', yes_no(binder.dry_run_only))}\n"
        f"      {metric('No execution', yes_no(binder.no_execution))}\n"
        f"      {metric('Executed', binder.executed)}\n"
        "    </section>\n"
        '    <section class="panel" id="binder-gates">\n'
        "      <h2>Manual-review gates</h2>\n"
        '      <div class="metric-grid">\n'
        f"        {metric('Outbound enabled', yes_no(binder.outbound_enabled))}\n"
        f"        {metric('Live providers', yes_no(binder.live_providers_enabled))}\n"
        f"        {metric('Operator halt', binder.operator_halt_status)}\n"
        f"        {metric('Halt before', binder.operator_halt_before)}\n"
        f"        {metric('Halt after', binder.operator_halt_after)}\n"
        f"        {metric('Halt changed', yes_no(binder.halt_changed))}\n"
        f"        {metric('Settings applied', yes_no(binder.settings_applied))}\n"
        f"        {metric('Owner approved live', yes_no(binder.owner_approved))}\n"
        f"        {metric('Live action', yes_no(binder.live_action))}\n"
        f"        {metric('Future execution phase',
            yes_no(binder.future_execution_phase_exists))}\n"
        f"        {metric('Outbound attempted', yes_no(binder.outbound_attempted))}\n"
        f"        {metric('Spend attempted', yes_no(binder.spend_attempted))}\n"
        f"        {metric('CLI command', binder.cli_command)}\n"
        f"        {metric('HTTP route', binder.http_route)}\n"
        "      </div>\n"
        "      <h3>Blocker codes</h3>\n"
        f"      {_render_codes(binder.blocker_codes, empty='No blocker codes.')}\n"
        "      <h3>Missing credential variable names</h3>\n"
        f"      {_render_codes(binder.missing_credential_names, empty='None missing.')}\n"
        "      <h3>Closed provider flag names</h3>\n"
        f"      {_render_codes(binder.closed_provider_flag_names, empty='None closed.')}\n"
        "      <h3>Related commands</h3>\n"
        f"      {_render_codes(binder.related_commands, empty='No related commands.')}\n"
        "      <h3>Related routes</h3>\n"
        f"      {_render_codes(binder.related_routes, empty='No related routes.')}\n"
        '      <p class="hint">This page never shows secret values, environment '
        "values, API keys, tokens, message bodies, emails, phones, evidence "
        "snippets, or unsafe error text. go_live_permitted=false, "
        "execution_allowed=false, and binder_is_not_go_live=true. This is a "
        "read-only owner-review view, not permission to go live.</p>\n"
        "    </section>"
    )


def _render_outbound_and_halt(evidence: OutboundHaltEvidenceResponse) -> str:
    return (
        '    <section class="panel" id="outbound-and-halt">\n'
        "      <h2>Outbound disabled and operator halt evidence</h2>\n"
        '      <div class="metric-grid">\n'
        f"        {metric('Outbound enabled', yes_no(evidence.outbound_enabled))}\n"
        f"        {metric('Settings halt', yes_no(evidence.outbound_halted_settings))}\n"
        f"        {metric('Operator halt', evidence.operator_halt_status)}\n"
        f"        {metric('Halt before', evidence.operator_halt_before)}\n"
        f"        {metric('Halt after', evidence.operator_halt_after)}\n"
        f"        {metric('Halt changed', yes_no(evidence.halt_changed))}\n"
        f"        {metric('Keep outbound disabled', yes_no(evidence.keep_outbound_disabled))}\n"
        f"        {metric('Command', evidence.command_name)}\n"
        f"        {metric('Route', evidence.route_name)}\n"
        "      </div>\n"
        "    </section>"
    )


def _render_live_provider_defaults(evidence: LiveProviderDefaultEvidenceResponse) -> str:
    flag_items = _kv_items(evidence.live_provider_flags, empty="No live-provider flags.")
    return (
        '    <section class="panel" id="live-provider-defaults">\n'
        "      <h2>No-live-provider default config evidence</h2>\n"
        '      <div class="metric-grid">\n'
        f"        {metric('Live providers', yes_no(evidence.live_providers_enabled))}\n"
        f"        {metric('.env.example defaults',
            yes_no(evidence.env_example_defaults_present))}\n"
        f"        {metric('Dockerfile defaults',
            yes_no(evidence.dockerfile_defaults_present))}\n"
        f"        {metric('Compose defaults', yes_no(evidence.compose_defaults_present))}\n"
        "      </div>\n"
        "      <h3>Live-provider flag states</h3>\n"
        f'      <ul class="kv-list">{flag_items}</ul>\n'
        "      <h3>Closed provider flag names</h3>\n"
        f"      {_render_codes(evidence.closed_provider_flag_names, empty='None closed.')}\n"
        "      <h3>Required flag names</h3>\n"
        f"      {_render_codes(evidence.required_flag_names, empty='None required.')}\n"
        "    </section>"
    )


def _render_no_execution(evidence: NoExecutionEvidenceResponse) -> str:
    return (
        '    <section class="panel" id="no-execution-side-effects">\n'
        "      <h2>No-execution side-effect evidence</h2>\n"
        '      <div class="metric-grid">\n'
        f"        {metric('Executed', evidence.executed)}\n"
        f"        {metric('Execution attempted', yes_no(evidence.execution_attempted))}\n"
        f"        {metric('Outbound attempted', yes_no(evidence.outbound_attempted))}\n"
        f"        {metric('Live call attempted', yes_no(evidence.live_call_attempted))}\n"
        f"        {metric('Recommendation applied', yes_no(evidence.recommendation_applied))}\n"
        f"        {metric('Spend attempted', yes_no(evidence.spend_attempted))}\n"
        f"        {metric('Campaign launched', yes_no(evidence.campaign_launched))}\n"
        f"        {metric('Pages published', yes_no(evidence.pages_published))}\n"
        f"        {metric('Ads launched', yes_no(evidence.ads_launched))}\n"
        f"        {metric('Owner approved live', yes_no(evidence.owner_approved))}\n"
        f"        {metric('Settings applied', yes_no(evidence.settings_applied))}\n"
        f"        {metric('Live action', yes_no(evidence.live_action))}\n"
        f"        {metric('Execution allowed', yes_no(evidence.execution_allowed))}\n"
        f"        {metric('Go live permitted', yes_no(evidence.go_live_permitted))}\n"
        f"        {metric('Future execution phase',
            yes_no(evidence.future_execution_phase_exists))}\n"
        f"        {metric('Live calendar events', evidence.live_calendar_events)}\n"
        f"        {metric('Live Meet links', evidence.live_meet_links)}\n"
        f"        {metric('Live phone calls', evidence.live_phone_calls)}\n"
        f"        {metric('Live send attempts', evidence.live_send_attempted_enrollments)}\n"
        f"        {metric('Outbound classifications',
            evidence.outbound_attempted_classifications)}\n"
        "      </div>\n"
        "      <h3>Undeployed outbound job names</h3>\n"
        f"      {_render_codes(evidence.undeployed_outbound_jobs, empty='None undeployed.')}\n"
        "    </section>"
    )


def _render_redaction(evidence: RedactionEvidenceResponse) -> str:
    return (
        '    <section class="panel" id="phi-secrets-redaction">\n'
        "      <h2>PHI, secrets, and redaction evidence</h2>\n"
        '      <div class="metric-grid">\n'
        f"        {metric('PHI fields present', yes_no(evidence.phi_fields_present))}\n"
        f"        {metric('Secret values included', yes_no(evidence.secret_values_included))}\n"
        f"        {metric('Message bodies included', yes_no(evidence.message_bodies_included))}\n"
        f"        {metric('Evidence snippets included',
            yes_no(evidence.evidence_snippets_included))}\n"
        f"        {metric('Emails included', yes_no(evidence.emails_included))}\n"
        f"        {metric('Phones included', yes_no(evidence.phones_included))}\n"
        f"        {metric('Redaction applied', yes_no(evidence.redaction_applied))}\n"
        "      </div>\n"
        "      <h3>Missing credential variable names</h3>\n"
        f"      {_render_codes(evidence.missing_credential_names, empty='None missing.')}\n"
        f"      {_secret_inventory_table(evidence.secret_inventory)}\n"
        "    </section>"
    )


def _secret_inventory_table(items: list[SecretPresenceItemResponse]) -> str:
    if not items:
        return (
            '<p class="empty-state" id="empty-secret-inventory">'
            "No secret inventory rows. This page never shows secret values.</p>"
        )
    rows = "".join(
        "<tr>"
        f'<td class="mono">{html_escape(item.name)}</td>'
        f"<td>{yes_no(item.present)}</td>"
        f"<td>{html_escape(item.status)}</td>"
        f"<td>{yes_no(item.required)}</td>"
        "</tr>"
        for item in items
    )
    return (
        "<h3>Secret presence inventory</h3>\n"
        '      <table class="dense"><thead><tr>'
        "<th>Variable</th><th>Present</th><th>Status</th><th>Required</th>"
        f"</tr></thead><tbody>{rows}</tbody></table>"
    )


def _render_consent(evidence: ConsentPhoneEvidenceResponse) -> str:
    return (
        '    <section class="panel" id="consent-phone-boundary">\n'
        "      <h2>Consent-based phone-only boundary evidence</h2>\n"
        '      <div class="metric-grid">\n'
        f"        {metric('Voice live enabled', yes_no(evidence.voice_live_enabled))}\n"
        f"        {metric('Consent to call required',
            yes_no(evidence.consent_to_call_required))}\n"
        f"        {metric('Cold calling disabled', yes_no(evidence.cold_calling_disabled))}\n"
        f"        {metric('No live dialer', yes_no(evidence.no_live_dialer))}\n"
        f"        {metric('Undeployed callback job', evidence.undeployed_callback_job)}\n"
        f"        {metric('Live phone calls', evidence.live_phone_calls)}\n"
        f"        {metric('Voice calls placed', evidence.voice_calls_placed)}\n"
        "      </div>\n"
        "    </section>"
    )


def _render_ci_gates(evidence: CiGateEvidenceResponse) -> str:
    return (
        '    <section class="panel" id="ci-gates">\n'
        "      <h2>CI dry-run smoke and deploy-config gates</h2>\n"
        "      <h3>Smoke-dry-run gate</h3>\n"
        f"      {_render_gate(evidence.smoke_gate)}\n"
        "      <h3>Deploy-config gate</h3>\n"
        f"      {_render_gate(evidence.deploy_config_gate)}\n"
        '      <div class="metric-grid">\n'
        f"        {metric('Smoke run command', evidence.smoke_run_command)}\n"
        f"        {metric('Smoke check command', evidence.smoke_check_command)}\n"
        "      </div>\n"
        "    </section>"
    )


def _render_gate(status: CiGateStatusResponse) -> str:
    return (
        '<div class="metric-grid">\n'
        f"        {metric('Present', yes_no(status.present))}\n"
        f"        {metric('Documented', yes_no(status.documented))}\n"
        f"        {metric('Job name', status.job_name)}\n"
        f"        {metric('Command name', status.command_name)}\n"
        "      </div>"
    )


def _render_guardrails(items: list[GuardrailDocEvidenceResponse]) -> str:
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


def _guardrail_row(item: GuardrailDocEvidenceResponse) -> str:
    codes = ", ".join(item.documented_codes) if item.documented_codes else "—"
    return (
        "<tr>"
        f'<td class="mono">{html_escape(item.path)}</td>'
        f"<td>{yes_no(item.present)}</td>"
        f'<td class="mono">{html_escape(codes)}</td>'
        "</tr>"
    )


def _render_audit_timeline(evidence: AuditTimelineEvidenceResponse) -> str:
    type_items = _count_items(evidence.by_event_type, empty="No event types.")
    return (
        '    <section class="panel" id="operator-audit-timeline-summary">\n'
        "      <h2>Operator audit timeline summary</h2>\n"
        '      <div class="metric-grid">\n'
        f"        {metric('Matching', evidence.matching_count)}\n"
        f"        {metric('Shown', evidence.shown_count)}\n"
        f"        {metric('Truncated', yes_no(evidence.truncated))}\n"
        f"        {metric('Route', evidence.route_name)}\n"
        "      </div>\n"
        "      <h3>Available event types</h3>\n"
        f"      {_render_codes(evidence.available_event_types, empty='No event types.')}\n"
        "      <h3>Available sources</h3>\n"
        f"      {_render_codes(evidence.available_sources, empty='No sources.')}\n"
        "      <h3>By event type</h3>\n"
        f'      <ul class="kv-list">{type_items}</ul>\n'
        f"      {_audit_table(evidence.entries)}\n"
        "    </section>"
    )


def _audit_table(entries: list[AuditTimelineEntryEvidenceResponse]) -> str:
    if not entries:
        return (
            '<p class="empty-state" id="empty-operator-audit-timeline">'
            "No audit timeline entries in this binder. This page does not "
            "create records or execute anything.</p>"
        )
    rows = "".join(_audit_row(item) for item in entries)
    return (
        "<h3>Entries</h3>\n"
        '      <table class="dense"><thead><tr>'
        "<th>When</th><th>Event</th><th>Source</th><th>Status</th>"
        "<th>Decision</th><th>Flags</th>"
        f"</tr></thead><tbody>{rows}</tbody></table>"
    )


def _audit_row(item: AuditTimelineEntryEvidenceResponse) -> str:
    flags = (
        f"no-exec={yes_no(item.no_execution)} · "
        f"executed={yes_no(item.executed)} · "
        f"live={yes_no(item.live_action)} · "
        f"applied={yes_no(item.settings_applied)}"
    )
    return (
        "<tr>"
        f"<td>{html_escape(format_dt(item.occurred_at))}</td>"
        f"<td>{titleize(item.event_type)}</td>"
        f"<td>{titleize(item.source_surface)}</td>"
        f"<td>{html_escape(item.status)}</td>"
        f"<td>{html_escape(item.decision_status)}</td>"
        f"<td>{html_escape(flags)}</td>"
        "</tr>"
    )


def _render_reused_summaries(evidence: ReusedSummaryEvidenceResponse) -> str:
    return (
        '    <section class="panel" id="reused-summaries">\n'
        "      <h2>Reused read-only summaries</h2>\n"
        '      <div class="metric-grid">\n'
        f"        {metric('Launch readiness', evidence.launch_readiness_overall_status)}\n"
        f"        {metric('Settings preflight', evidence.settings_preflight_overall_status)}\n"
        f"        {metric('Preflight blocked', evidence.settings_preflight_blocked_count)}\n"
        f"        {metric('Preflight executable',
            evidence.settings_preflight_executable_count)}\n"
        f"        {metric('Preflight execution allowed',
            yes_no(evidence.settings_preflight_execution_allowed))}\n"
        f"        {metric('Owner handoff command', evidence.owner_handoff_command)}\n"
        f"        {metric('Owner handoff route', evidence.owner_handoff_route)}\n"
        f"        {metric('Handoff go live permitted',
            yes_no(evidence.owner_handoff_go_live_permitted))}\n"
        f"        {metric('Handoff execution allowed',
            yes_no(evidence.owner_handoff_execution_allowed))}\n"
        "      </div>\n"
        "      <h3>Launch readiness blocker codes</h3>\n"
        f"      {_render_codes(
            evidence.launch_readiness_blocker_codes, empty='No blocker codes.'
        )}\n"
        "      <h3>Launch readiness next-action codes</h3>\n"
        f"      {_render_codes(
            evidence.launch_readiness_next_action_codes, empty='No next-action codes.'
        )}\n"
        "    </section>"
    )


def _render_checklist(items: list[BinderChecklistItemResponse]) -> str:
    if not items:
        return (
            '    <section class="panel" id="remaining-manual-owner-checklist">\n'
            "      <h2>Remaining manual owner checklist</h2>\n"
            '      <p class="empty-state" id="empty-remaining-manual-owner-checklist">'
            "No remaining checklist items. This page still does not permit going "
            "live or executing anything.</p>\n"
            "    </section>"
        )
    rows = "".join(_checklist_row(item) for item in items)
    return (
        '    <section class="panel" id="remaining-manual-owner-checklist">\n'
        "      <h2>Remaining manual owner checklist</h2>\n"
        '      <table class="dense"><thead><tr>'
        "<th>Code</th><th>Severity</th><th>Source</th><th>Status</th>"
        f"</tr></thead><tbody>{rows}</tbody></table>\n"
        "    </section>"
    )


def _checklist_row(item: BinderChecklistItemResponse) -> str:
    return (
        f'<tr class="{_severity_class(item.severity)}">'
        f'<td class="mono">{html_escape(item.code)}</td>'
        f"<td>{html_escape(item.severity)}</td>"
        f"<td>{titleize(item.source_section)}</td>"
        f"<td>{html_escape(item.status)}</td>"
        "</tr>"
    )


def _render_footer(binder: ComplianceEvidenceBinderResponse, generated: str) -> str:
    return (
        '    <footer class="footnote" id="side-effects">\n'
        f"      <p>Generated {generated}. Read-only={yes_no(binder.read_only)}. "
        f"Manual review only={yes_no(binder.manual_review_only)}. "
        f"Dry-run only={yes_no(binder.dry_run_only)}. "
        f"No execution={yes_no(binder.no_execution)}. "
        f"Executed={html_escape(binder.executed)}. "
        f"Settings applied={yes_no(binder.settings_applied)}. "
        f"Halt changed={yes_no(binder.halt_changed)}. "
        f"Owner approved={yes_no(binder.owner_approved)}. "
        f"Live action={yes_no(binder.live_action)}. "
        f"Execution allowed={yes_no(binder.execution_allowed)}. "
        f"Go live permitted={yes_no(binder.go_live_permitted)}. "
        f"Binder is not go-live={yes_no(binder.binder_is_not_go_live)}. "
        f"Future execution phase exists="
        f"{yes_no(binder.future_execution_phase_exists)}. "
        "There are no apply, execute, lift-halt, enable-outbound, provider, "
        "deploy, campaign, booking, call, publish, or spend controls on this "
        "page. This is a read-only owner-review view, not permission to go "
        "live.</p>\n"
        "    </footer>"
    )


def _kv_items(flags: dict[str, bool], *, empty: str) -> str:
    items = "".join(
        f"<li><span>{titleize(key)}</span><strong>{html_escape(yes_no(value))}</strong></li>"
        for key, value in sorted(flags.items())
    )
    return items or f'<li class="empty">{escape(empty)}</li>'


def _count_items(counts: dict[str, int], *, empty: str) -> str:
    items = "".join(
        f"<li><span>{titleize(key)}</span><strong>{html_escape(count)}</strong></li>"
        for key, count in sorted(counts.items())
    )
    return items or f'<li class="empty">{escape(empty)}</li>'


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
    raise RuntimeError(f"unhandled compliance binder checklist severity: {value!r}")
