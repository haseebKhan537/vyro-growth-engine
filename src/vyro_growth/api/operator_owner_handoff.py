"""Read-only owner go-live handoff packet HTML shell.

Phase 33 renders the Phase 32 owner handoff packet as an internal HTML page.
It never applies settings, lifts halt, enables outbound, executes requests,
packets, or approved items, sets live owner-approved state, or performs any
live action. This page is not permission or machinery for going live.
"""

from __future__ import annotations

from html import escape
from typing import Never

import structlog
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from vyro_growth.api.operator_ui import (
    ACTION_READINESS_JSON_PATH,
    LAUNCH_READINESS_JSON_PATH,
    NO_STORE_HEADERS,
    OPERATOR_ACTION_READINESS_PATH,
    OPERATOR_APPROVAL_PACKETS_PATH,
    OPERATOR_SETTINGS_CHANGE_REQUESTS_PATH,
    OPERATOR_SETTINGS_EXECUTION_PREFLIGHT_PATH,
    OPERATOR_UI_STYLES,
    OWNER_HANDOFF_JSON_PATH,
    SETTINGS_EXECUTION_PREFLIGHT_JSON_PATH,
    format_dt,
    html_escape,
    metric,
    render_failure_page,
    render_operator_nav,
    short_id,
    titleize,
    yes_no,
)
from vyro_growth.api.owner_handoff import (
    HandoffActionReadinessItemResponse,
    HandoffActionReadinessSummaryResponse,
    HandoffApprovalPacketItemResponse,
    HandoffApprovalPacketSummaryResponse,
    HandoffChecklistItemResponse,
    HandoffLaunchReadinessResponse,
    HandoffSettingsPreflightItemResponse,
    HandoffSettingsPreflightSummaryResponse,
    HandoffSettingsRequestItemResponse,
    HandoffSettingsRequestSummaryResponse,
    OwnerHandoffPacketResponse,
    build_owner_handoff_response,
)
from vyro_growth.config import Settings
from vyro_growth.domain import FindingSeverity
from vyro_growth.services.owner_handoff import OwnerHandoffPacketService

logger = structlog.get_logger(__name__)


def render_owner_handoff_error() -> str:
    return render_failure_page(
        page_id="operator-owner-handoff-packet-error",
        title="Owner go-live handoff packet unavailable",
        heading="Read-only owner go-live handoff packet unavailable",
        banner="Unable to load the owner go-live handoff packet.",
        detail=(
            "The sanitized manual-review packet could not be rendered. "
            "Retry after checking database connectivity and runtime config. "
            "This page is not permission or machinery for going live."
        ),
    )


def render_owner_handoff(packet: OwnerHandoffPacketResponse) -> str:
    generated = html_escape(format_dt(packet.generated_at))
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '  <meta charset="utf-8">\n'
        '  <meta name="viewport" content="width=device-width, initial-scale=1">\n'
        "  <title>Owner go-live handoff packet</title>\n"
        f"{OPERATOR_UI_STYLES}\n"
        "</head>\n"
        "<body>\n"
        '  <main id="operator-owner-handoff-packet" data-read-only="true" '
        'data-dry-run-only="true" data-execution-allowed="false" '
        'data-go-live-permitted="false" data-no-execution="true" '
        'data-manual-review-only="true">\n'
        f"{_render_header(packet, generated)}\n"
        f"{render_operator_nav('owner-handoff-packet')}\n"
        f"{_render_related_links()}\n"
        f"{_render_overall(packet)}\n"
        f"{_render_launch_readiness(packet.launch_readiness)}\n"
        f"{_render_settings_requests(packet.settings_change_requests)}\n"
        f"{_render_settings_preflight(packet.settings_execution_preflight)}\n"
        f"{_render_approval_packets(packet.owner_approval_packets)}\n"
        f"{_render_action_readiness(packet.approved_action_readiness)}\n"
        f"{_render_checklist(packet.remaining_manual_owner_checklist)}\n"
        f"{_render_footer(packet, generated)}\n"
        "  </main>\n"
        "</body>\n"
        "</html>\n"
    )


def build_operator_owner_handoff_response(
    db: Session,
    settings: Settings,
    *,
    service: OwnerHandoffPacketService | None = None,
) -> HTMLResponse:
    try:
        packet = build_owner_handoff_response(db, settings, service=service)
        html = render_owner_handoff(packet)
        return HTMLResponse(content=html, status_code=200, headers=NO_STORE_HEADERS)
    except Exception:
        logger.exception("operator_owner_handoff_packet_render_failed", read_only=True)
        return HTMLResponse(
            content=render_owner_handoff_error(),
            status_code=500,
            headers=NO_STORE_HEADERS,
        )


def _render_header(packet: OwnerHandoffPacketResponse, generated: str) -> str:
    return (
        '    <header class="page-header">\n'
        "      <div>\n"
        "        <h1>Owner go-live handoff packet</h1>\n"
        '        <p class="lede">Read-only manual-review view of the consolidated '
        "owner go-live handoff packet. Execution remains disabled. "
        "go_live_permitted=false. execution_allowed=false. This page is not "
        "permission or machinery for going live.</p>\n"
        "      </div>\n"
        f'      <p class="meta">Generated {generated} · overall '
        f"{html_escape(packet.overall_status)} · halt "
        f"{html_escape(packet.operator_halt_status)} · "
        f"{html_escape(packet.packet_kind)} · {html_escape(packet.purpose)}</p>\n"
        "    </header>"
    )


def _render_related_links() -> str:
    json_href = escape(OWNER_HANDOFF_JSON_PATH)
    launch_href = escape(LAUNCH_READINESS_JSON_PATH)
    preflight_href = escape(OPERATOR_SETTINGS_EXECUTION_PREFLIGHT_PATH)
    preflight_json_href = escape(SETTINGS_EXECUTION_PREFLIGHT_JSON_PATH)
    requests_href = escape(OPERATOR_SETTINGS_CHANGE_REQUESTS_PATH)
    packets_href = escape(OPERATOR_APPROVAL_PACKETS_PATH)
    readiness_href = escape(OPERATOR_ACTION_READINESS_PATH)
    readiness_json_href = escape(ACTION_READINESS_JSON_PATH)
    return (
        '    <nav class="filter-nav" aria-label="Related read-only surfaces">\n'
        f'      <a class="nav-link nav-json" href="{json_href}">JSON packet</a>\n'
        f'      <a class="nav-link" href="{launch_href}">Launch readiness JSON</a>\n'
        f'      <a class="nav-link" href="{preflight_href}">Settings preflight</a>\n'
        f'      <a class="nav-link" href="{preflight_json_href}">JSON preflight</a>\n'
        f'      <a class="nav-link" href="{requests_href}">Settings requests</a>\n'
        f'      <a class="nav-link" href="{packets_href}">Approval packets</a>\n'
        f'      <a class="nav-link" href="{readiness_href}">Action readiness</a>\n'
        f'      <a class="nav-link" href="{readiness_json_href}">JSON readiness</a>\n'
        "    </nav>"
    )


def _render_overall(packet: OwnerHandoffPacketResponse) -> str:
    return (
        '    <section class="status-strip" aria-label="Handoff flags">\n'
        f"      {metric('Overall', packet.overall_status)}\n"
        f"      {metric('Go live permitted', yes_no(packet.go_live_permitted))}\n"
        f"      {metric('Execution allowed', yes_no(packet.execution_allowed))}\n"
        f"      {metric('Manual review only', yes_no(packet.manual_review_only))}\n"
        f"      {metric('Read only', yes_no(packet.read_only))}\n"
        f"      {metric('Dry-run only', yes_no(packet.dry_run_only))}\n"
        f"      {metric('No execution', yes_no(packet.no_execution))}\n"
        f"      {metric('Executed', packet.executed)}\n"
        "    </section>\n"
        '    <section class="panel" id="handoff-gates">\n'
        "      <h2>Manual-review gates</h2>\n"
        '      <div class="metric-grid">\n'
        f"        {metric('Outbound enabled', yes_no(packet.outbound_enabled))}\n"
        f"        {metric('Live providers', yes_no(packet.live_providers_enabled))}\n"
        f"        {metric('Operator halt', packet.operator_halt_status)}\n"
        f"        {metric('Halt before', packet.operator_halt_before)}\n"
        f"        {metric('Halt after', packet.operator_halt_after)}\n"
        f"        {metric('Halt changed', yes_no(packet.halt_changed))}\n"
        f"        {metric('Settings applied', yes_no(packet.settings_applied))}\n"
        f"        {metric('Owner approved live', yes_no(packet.owner_approved))}\n"
        f"        {metric('Live action', yes_no(packet.live_action))}\n"
        f"        {metric('Future execution phase',
            yes_no(packet.future_execution_phase_exists))}\n"
        f"        {metric('Outbound attempted', yes_no(packet.outbound_attempted))}\n"
        f"        {metric('Spend attempted', yes_no(packet.spend_attempted))}\n"
        "      </div>\n"
        "      <h3>Blocker codes</h3>\n"
        f"      {_render_codes(packet.blocker_codes, empty='No blocker codes.')}\n"
        "      <h3>Missing credential variable names</h3>\n"
        f"      {_render_codes(packet.missing_credential_names, empty='None missing.')}\n"
        "      <h3>Closed provider flag names</h3>\n"
        f"      {_render_codes(packet.closed_provider_flag_names, empty='None closed.')}\n"
        '      <p class="hint">This page never shows secret values, environment '
        "values, API keys, tokens, message bodies, emails, phones, evidence "
        "snippets, or unsafe error text. go_live_permitted=false and "
        "execution_allowed=false. This is a read-only manual-review view, not "
        "permission to go live.</p>\n"
        "    </section>"
    )


def _render_launch_readiness(summary: HandoffLaunchReadinessResponse) -> str:
    return (
        '    <section class="panel" id="launch-readiness">\n'
        "      <h2>Launch readiness summary</h2>\n"
        '      <div class="metric-grid">\n'
        f"        {metric('Overall', summary.overall_status)}\n"
        f"        {metric('Operator halt', summary.operator_halt_status)}\n"
        f"        {metric('Outbound enabled', yes_no(summary.outbound_enabled))}\n"
        f"        {metric('Live providers', yes_no(summary.live_providers_enabled))}\n"
        f"        {metric('Config ok', yes_no(summary.config_ok))}\n"
        f"        {metric('CI smoke present', yes_no(summary.ci_smoke_gate_present))}\n"
        f"        {metric('CI smoke documented', yes_no(summary.ci_smoke_gate_documented))}\n"
        f"        {metric('CI smoke job', summary.ci_smoke_gate_job_name)}\n"
        f"        {metric('Pending packets', summary.pending_owner_approval_packets)}\n"
        f"        {metric('Action candidates', summary.action_readiness_candidate_count)}\n"
        f"        {metric('Action blocked', summary.action_readiness_blocked_count)}\n"
        f"        {metric('Pending settings requests',
            summary.pending_settings_change_request_count)}\n"
        f"        {metric('No execution', yes_no(summary.no_execution))}\n"
        f"        {metric('Owner approved live', yes_no(summary.owner_approved))}\n"
        f"        {metric('Live action', yes_no(summary.live_action))}\n"
        "      </div>\n"
        "      <h3>Finding codes</h3>\n"
        f"      {_render_codes(summary.finding_codes, empty='No finding codes.')}\n"
        "      <h3>Blocker codes</h3>\n"
        f"      {_render_codes(summary.blocker_codes, empty='No blocker codes.')}\n"
        "      <h3>Next-action codes</h3>\n"
        f"      {_render_codes(summary.next_action_codes, empty='No next-action codes.')}\n"
        "      <h3>Missing credential variable names</h3>\n"
        f"      {_render_codes(summary.missing_credential_names, empty='None missing.')}\n"
        "      <h3>Closed provider flag names</h3>\n"
        f"      {_render_codes(summary.closed_provider_flag_names, empty='None closed.')}\n"
        "    </section>"
    )


def _render_settings_requests(summary: HandoffSettingsRequestSummaryResponse) -> str:
    type_items = _kv_items(summary.by_request_type, empty="No request types.")
    status_items = _kv_items(summary.by_status, empty="No request statuses.")
    decision_items = _kv_items(summary.by_decision_status, empty="No decision statuses.")
    body = _settings_request_table(summary.requests)
    return (
        '    <section class="panel" id="settings-change-requests">\n'
        "      <h2>Settings change request summary</h2>\n"
        '      <div class="metric-grid">\n'
        f"        {metric('Requests', summary.request_count)}\n"
        f"        {metric('Pending', summary.pending_count)}\n"
        f"        {metric('Approved', summary.approved_count)}\n"
        f"        {metric('Rejected', summary.rejected_count)}\n"
        f"        {metric('Needs changes', summary.needs_changes_count)}\n"
        f"        {metric('Record only', yes_no(summary.record_only))}\n"
        f"        {metric('No execution', yes_no(summary.no_execution))}\n"
        f"        {metric('Settings applied', yes_no(summary.settings_applied))}\n"
        f"        {metric('Owner approved live', yes_no(summary.owner_approved))}\n"
        "      </div>\n"
        "      <h3>Request IDs</h3>\n"
        f"      {_render_codes(summary.request_ids, empty='No request IDs.')}\n"
        "      <h3>Setting names</h3>\n"
        f"      {_render_codes(summary.setting_names, empty='No setting names.')}\n"
        "      <h3>By request type</h3>\n"
        f'      <ul class="kv-list">{type_items}</ul>\n'
        "      <h3>By status</h3>\n"
        f'      <ul class="kv-list">{status_items}</ul>\n'
        "      <h3>By owner decision</h3>\n"
        f'      <ul class="kv-list">{decision_items}</ul>\n'
        f"      {body}\n"
        "    </section>"
    )


def _settings_request_table(requests: list[HandoffSettingsRequestItemResponse]) -> str:
    if not requests:
        return (
            '<p class="empty-state" id="empty-settings-change-requests">'
            "No settings-change requests in this packet. This page does not "
            "create requests, apply settings, or execute live actions.</p>"
        )
    rows = "".join(_settings_request_row(item) for item in requests)
    return (
        "<h3>Requests</h3>\n"
        '      <table class="dense"><thead><tr>'
        "<th>Type</th><th>Request</th><th>Status</th><th>Decision</th>"
        "<th>Setting names</th><th>Desired</th><th>Codes</th><th>Flags</th>"
        f"</tr></thead><tbody>{rows}</tbody></table>"
    )


def _settings_request_row(item: HandoffSettingsRequestItemResponse) -> str:
    href = f"{OPERATOR_SETTINGS_CHANGE_REQUESTS_PATH}/{item.request_id}"
    names = ", ".join(item.requested_setting_names) if item.requested_setting_names else "—"
    codes = ", ".join(code for code in (item.finding_code, item.next_action_code) if code) or "—"
    flags = (
        f"no-exec={yes_no(item.no_execution)} · "
        f"executed={yes_no(item.executed)} · "
        f"applied={yes_no(item.settings_applied)} · "
        f"record-only={yes_no(item.record_only)}"
    )
    return (
        f'<tr class="{_decision_class(item.decision_status)}">'
        f"<td>{titleize(item.request_type)}</td>"
        f'<td class="mono"><a class="row-link" href="{escape(href)}">'
        f"{html_escape(short_id(item.request_id))}</a></td>"
        f"<td>{html_escape(item.request_status)}</td>"
        f"<td>{html_escape(item.decision_status)}</td>"
        f'<td class="mono">{html_escape(names)}</td>'
        f"<td>{html_escape(_desired_label(item.desired_boolean, item.desired_status))}</td>"
        f'<td class="mono">{html_escape(codes)}</td>'
        f"<td>{html_escape(flags)}</td>"
        "</tr>"
    )


def _render_settings_preflight(summary: HandoffSettingsPreflightSummaryResponse) -> str:
    body = _preflight_table(summary.requests)
    return (
        '    <section class="panel" id="settings-execution-preflight">\n'
        "      <h2>Settings execution preflight summary</h2>\n"
        '      <div class="metric-grid">\n'
        f"        {metric('Overall', summary.overall_status)}\n"
        f"        {metric('Requests', summary.request_count)}\n"
        f"        {metric('Pending decisions', summary.pending_decision_count)}\n"
        f"        {metric('Approved decisions', summary.approved_decision_count)}\n"
        f"        {metric('Rejected / needs changes', summary.rejected_or_needs_changes_count)}\n"
        f"        {metric('Blocked', summary.blocked_count)}\n"
        f"        {metric('Executable', summary.executable_count)}\n"
        f"        {metric('Dry-run only', yes_no(summary.dry_run_only))}\n"
        f"        {metric('No execution', yes_no(summary.no_execution))}\n"
        f"        {metric('Execution allowed', yes_no(summary.execution_allowed))}\n"
        f"        {metric('Future execution phase',
            yes_no(summary.future_execution_phase_exists))}\n"
        "      </div>\n"
        "      <h3>Blocker codes</h3>\n"
        f"      {_render_codes(summary.blocker_codes, empty='No blocker codes.')}\n"
        "      <h3>Missing approval codes</h3>\n"
        f"      {_render_codes(summary.missing_approval_codes, empty='None missing.')}\n"
        "      <h3>Missing gate codes</h3>\n"
        f"      {_render_codes(summary.missing_gate_codes, empty='None missing.')}\n"
        "      <h3>Missing credential variable names</h3>\n"
        f"      {_render_codes(summary.missing_credential_names, empty='None missing.')}\n"
        "      <h3>Closed provider flag names</h3>\n"
        f"      {_render_codes(summary.closed_provider_flag_names, empty='None closed.')}\n"
        f"      {body}\n"
        "    </section>"
    )


def _preflight_table(requests: list[HandoffSettingsPreflightItemResponse]) -> str:
    if not requests:
        return (
            '<p class="empty-state" id="empty-settings-execution-preflight">'
            "No settings-change requests to simulate. This dry-run view does "
            "not apply settings or execute live actions.</p>"
        )
    rows = "".join(_preflight_row(item) for item in requests)
    return (
        "<h3>Simulated requests</h3>\n"
        '      <table class="dense"><thead><tr>'
        "<th>Type</th><th>Request</th><th>Decision</th><th>Execution</th>"
        "<th>Setting names</th><th>Desired</th><th>Blockers</th><th>Flags</th>"
        f"</tr></thead><tbody>{rows}</tbody></table>"
    )


def _preflight_row(item: HandoffSettingsPreflightItemResponse) -> str:
    href = f"{OPERATOR_SETTINGS_CHANGE_REQUESTS_PATH}/{item.request_id}"
    names = ", ".join(item.requested_setting_names) if item.requested_setting_names else "—"
    blockers = ", ".join(item.blocker_codes) if item.blocker_codes else "—"
    flags = (
        f"no-exec={yes_no(item.no_execution)} · "
        f"executed={yes_no(item.executed)} · "
        f"applied={yes_no(item.settings_applied)} · "
        f"allowed={yes_no(item.execution_allowed)}"
    )
    return (
        f'<tr class="{_decision_class(item.decision_status)}">'
        f"<td>{titleize(item.request_type)}</td>"
        f'<td class="mono"><a class="row-link" href="{escape(href)}">'
        f"{html_escape(short_id(item.request_id))}</a></td>"
        f"<td>{html_escape(item.decision_status)}</td>"
        f"<td>{html_escape(item.execution_status)}</td>"
        f'<td class="mono">{html_escape(names)}</td>'
        f"<td>{html_escape(_desired_label(item.desired_boolean, item.desired_status))}</td>"
        f'<td class="mono">{html_escape(blockers)}</td>'
        f"<td>{html_escape(flags)}</td>"
        "</tr>"
    )


def _render_approval_packets(summary: HandoffApprovalPacketSummaryResponse) -> str:
    preflight_items = _kv_items(summary.by_preflight_status, empty="No preflight statuses.")
    family_items = _kv_items(summary.by_plan_family, empty="No plan families.")
    decision_items = _kv_items(summary.by_decision_status, empty="No decision statuses.")
    body = _packet_table(summary.packets)
    return (
        '    <section class="panel" id="owner-approval-packets">\n'
        "      <h2>Owner approval packet summary</h2>\n"
        '      <div class="metric-grid">\n'
        f"        {metric('Packets', summary.packet_count)}\n"
        f"        {metric('Pending', summary.pending_count)}\n"
        f"        {metric('Approved', summary.approved_count)}\n"
        f"        {metric('Rejected', summary.rejected_count)}\n"
        f"        {metric('Needs changes', summary.needs_changes_count)}\n"
        f"        {metric('No execution', yes_no(summary.no_execution))}\n"
        f"        {metric('Executed', summary.executed)}\n"
        f"        {metric('Owner approved live', yes_no(summary.owner_approved))}\n"
        f"        {metric('Live action', yes_no(summary.live_action))}\n"
        "      </div>\n"
        "      <h3>Packet IDs</h3>\n"
        f"      {_render_codes(summary.packet_ids, empty='No packet IDs.')}\n"
        "      <h3>By preflight status</h3>\n"
        f'      <ul class="kv-list">{preflight_items}</ul>\n'
        "      <h3>By plan family</h3>\n"
        f'      <ul class="kv-list">{family_items}</ul>\n'
        "      <h3>By owner decision</h3>\n"
        f'      <ul class="kv-list">{decision_items}</ul>\n'
        f"      {body}\n"
        "    </section>"
    )


def _packet_table(packets: list[HandoffApprovalPacketItemResponse]) -> str:
    if not packets:
        return (
            '<p class="empty-state" id="empty-owner-approval-packets">'
            "No owner approval packets in this handoff. This page does not "
            "generate packets or execute them.</p>"
        )
    rows = "".join(_packet_row(item) for item in packets)
    return (
        "<h3>Packets</h3>\n"
        '      <table class="dense"><thead><tr>'
        "<th>Family</th><th>Packet</th><th>Preflight</th><th>Decision</th>"
        "<th>Generated</th><th>Flags</th>"
        f"</tr></thead><tbody>{rows}</tbody></table>"
    )


def _packet_row(item: HandoffApprovalPacketItemResponse) -> str:
    href = f"{OPERATOR_APPROVAL_PACKETS_PATH}/{item.packet_id}"
    flags = (
        f"no-exec={yes_no(item.no_execution)} · "
        f"executed={yes_no(item.executed)} · "
        f"owner-approved={yes_no(item.owner_approved)} · "
        f"live={yes_no(item.live_action)}"
    )
    return (
        f'<tr class="{_decision_class(item.decision_status)}">'
        f"<td>{titleize(item.plan_family)}</td>"
        f'<td class="mono"><a class="row-link" href="{escape(href)}">'
        f"{html_escape(short_id(item.packet_id))}</a></td>"
        f"<td>{html_escape(item.preflight_status)}</td>"
        f"<td>{html_escape(item.decision_status)}</td>"
        f"<td>{html_escape(format_dt(item.generated_at))}</td>"
        f"<td>{html_escape(flags)}</td>"
        "</tr>"
    )


def _render_action_readiness(summary: HandoffActionReadinessSummaryResponse) -> str:
    readiness_items = _kv_items(summary.by_readiness_status, empty="No readiness statuses.")
    family_items = _kv_items(summary.by_plan_family, empty="No plan families.")
    blocker_items = _kv_items(summary.by_blocker_status, empty="No blocker statuses.")
    decision_items = _kv_items(summary.by_decision_status, empty="No decision statuses.")
    body = _action_table(summary.candidates)
    return (
        '    <section class="panel" id="approved-action-readiness">\n'
        "      <h2>Approved action readiness summary</h2>\n"
        '      <div class="metric-grid">\n'
        f"        {metric('Candidates', summary.candidate_count)}\n"
        f"        {metric('Blocked', summary.blocked_count)}\n"
        f"        {metric('Dry-run only', yes_no(summary.dry_run_only))}\n"
        f"        {metric('No execution', yes_no(summary.no_execution))}\n"
        f"        {metric('Executed', summary.executed_count)}\n"
        f"        {metric('Owner approved live', yes_no(summary.owner_approved))}\n"
        f"        {metric('Live action', yes_no(summary.live_action))}\n"
        f"        {metric('Explicit owner action required',
            yes_no(summary.explicit_live_owner_action_required))}\n"
        "      </div>\n"
        "      <h3>Candidate IDs</h3>\n"
        f"      {_render_codes(summary.candidate_ids, empty='No candidate IDs.')}\n"
        "      <h3>By readiness status</h3>\n"
        f'      <ul class="kv-list">{readiness_items}</ul>\n'
        "      <h3>By plan family</h3>\n"
        f'      <ul class="kv-list">{family_items}</ul>\n'
        "      <h3>By blocker status</h3>\n"
        f'      <ul class="kv-list">{blocker_items}</ul>\n'
        "      <h3>By decision status</h3>\n"
        f'      <ul class="kv-list">{decision_items}</ul>\n'
        f"      {body}\n"
        "    </section>"
    )


def _action_table(candidates: list[HandoffActionReadinessItemResponse]) -> str:
    if not candidates:
        return (
            '<p class="empty-state" id="empty-approved-action-readiness">'
            "No approved action-readiness candidates in this packet. This page "
            "does not execute candidates or set live owner-approved state.</p>"
        )
    rows = "".join(_action_row(item) for item in candidates)
    return (
        "<h3>Candidates</h3>\n"
        '      <table class="dense"><thead><tr>'
        "<th>Family</th><th>Candidate</th><th>Readiness</th><th>Blocker</th>"
        "<th>Review</th><th>Packet</th><th>Blockers</th><th>Flags</th>"
        f"</tr></thead><tbody>{rows}</tbody></table>"
    )


def _action_row(item: HandoffActionReadinessItemResponse) -> str:
    href = f"{OPERATOR_ACTION_READINESS_PATH}/{item.candidate_id}"
    packet_href = (
        f"{OPERATOR_APPROVAL_PACKETS_PATH}/{item.approval_packet_id}"
        if item.approval_packet_id is not None
        else None
    )
    packet_cell = (
        f'<td class="mono"><a class="row-link" href="{escape(packet_href)}">'
        f"{html_escape(short_id(item.approval_packet_id))}</a></td>"
        if packet_href is not None
        else "<td>—</td>"
    )
    blockers = ", ".join(item.blocker_codes) if item.blocker_codes else "—"
    flags = (
        f"no-exec={yes_no(item.no_execution)} · "
        f"executed={yes_no(item.executed)} · "
        f"allowed={yes_no(item.execution_allowed)} · "
        f"live={yes_no(item.live_action)}"
    )
    return (
        f'<tr class="{_readiness_class(item.readiness_status, item.blocker_status)}">'
        f"<td>{titleize(item.plan_family)}</td>"
        f'<td class="mono"><a class="row-link" href="{escape(href)}">'
        f"{html_escape(short_id(item.candidate_id))}</a></td>"
        f"<td>{html_escape(item.readiness_status)}</td>"
        f"<td>{html_escape(item.blocker_status)}</td>"
        f"<td>{html_escape(item.review_decision_status)}</td>"
        f"{packet_cell}"
        f'<td class="mono">{html_escape(blockers)}</td>'
        f"<td>{html_escape(flags)}</td>"
        "</tr>"
    )


def _render_checklist(items: list[HandoffChecklistItemResponse]) -> str:
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


def _checklist_row(item: HandoffChecklistItemResponse) -> str:
    return (
        f'<tr class="{_severity_class(item.severity)}">'
        f'<td class="mono">{html_escape(item.code)}</td>'
        f"<td>{html_escape(item.severity)}</td>"
        f"<td>{titleize(item.source_section)}</td>"
        f"<td>{html_escape(item.status)}</td>"
        "</tr>"
    )


def _render_footer(packet: OwnerHandoffPacketResponse, generated: str) -> str:
    return (
        '    <footer class="footnote" id="side-effects">\n'
        f"      <p>Generated {generated}. Read-only={yes_no(packet.read_only)}. "
        f"Manual review only={yes_no(packet.manual_review_only)}. "
        f"Dry-run only={yes_no(packet.dry_run_only)}. "
        f"No execution={yes_no(packet.no_execution)}. "
        f"Executed={html_escape(packet.executed)}. "
        f"Settings applied={yes_no(packet.settings_applied)}. "
        f"Halt changed={yes_no(packet.halt_changed)}. "
        f"Owner approved={yes_no(packet.owner_approved)}. "
        f"Live action={yes_no(packet.live_action)}. "
        f"Execution allowed={yes_no(packet.execution_allowed)}. "
        f"Go live permitted={yes_no(packet.go_live_permitted)}. "
        f"Future execution phase exists="
        f"{yes_no(packet.future_execution_phase_exists)}. "
        "There are no apply, execute, lift-halt, enable-outbound, provider, "
        "deploy, campaign, booking, call, publish, or spend controls on this "
        "page. This is a read-only manual-review view, not permission to go "
        "live.</p>\n"
        "    </footer>"
    )


def _desired_label(desired_boolean: bool | None, desired_status: str | None) -> str:
    if desired_status:
        return desired_status
    if desired_boolean is True:
        return "true"
    if desired_boolean is False:
        return "false"
    return "—"


def _kv_items(counts: dict[str, int], *, empty: str) -> str:
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


def _decision_class(status: str) -> str:
    match status:
        case "rejected" | "needs_changes" | "blocked":
            return "severity-blocked"
        case "pending" | "pending_decision":
            return "severity-warning"
        case _:
            return "severity-info"


def _readiness_class(readiness_status: str, blocker_status: str) -> str:
    if "blocked" in readiness_status or "blocked" in blocker_status:
        return "severity-blocked"
    if "pending" in readiness_status or "missing" in readiness_status:
        return "severity-warning"
    return "severity-info"


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
    raise RuntimeError(f"unhandled owner handoff checklist severity: {value!r}")
