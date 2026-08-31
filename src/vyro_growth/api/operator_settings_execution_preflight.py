"""Read-only settings execution preflight HTML shell.

Phase 31 renders the Phase 30 dry-run simulator as an internal HTML page.
It never applies settings, lifts halt, enables outbound, executes requests,
sets live owner-approved state, or performs any live action.
"""

from __future__ import annotations

from html import escape
from typing import Never

import structlog
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from vyro_growth.api.operator_ui import (
    NO_STORE_HEADERS,
    OPERATOR_SETTINGS_CHANGE_REQUESTS_PATH,
    OPERATOR_SETTINGS_EXECUTION_PREFLIGHT_PATH,
    OPERATOR_UI_STYLES,
    SETTINGS_EXECUTION_PREFLIGHT_JSON_PATH,
    filter_link,
    format_dt,
    html_escape,
    metric,
    render_failure_page,
    render_operator_nav,
    short_id,
    titleize,
    yes_no,
)
from vyro_growth.api.settings_execution_preflight import (
    SettingsExecutionPreflightItemResponse,
    SettingsExecutionPreflightResponse,
    build_settings_execution_preflight_response,
)
from vyro_growth.config import Settings
from vyro_growth.domain import (
    SettingsChangeDecisionStatus,
    SettingsChangeRequestType,
    SettingsExecutionPreflightStatus,
)
from vyro_growth.services.settings_execution_preflight import SettingsExecutionPreflightService

logger = structlog.get_logger(__name__)

_REQUEST_TYPES: tuple[str, ...] = tuple(item.value for item in SettingsChangeRequestType)
_DECISION_STATUSES: tuple[str, ...] = tuple(item.value for item in SettingsChangeDecisionStatus)
_EXECUTION_STATUSES: tuple[str, ...] = tuple(
    item.value for item in SettingsExecutionPreflightStatus
)


def parse_request_type(value: str | None) -> str | None:
    return _parse_allowed(value, _REQUEST_TYPES)


def parse_decision_status(value: str | None) -> str | None:
    return _parse_allowed(value, _DECISION_STATUSES)


def parse_execution_status(value: str | None) -> str | None:
    return _parse_allowed(value, _EXECUTION_STATUSES)


def render_settings_execution_preflight_error() -> str:
    return render_failure_page(
        page_id="operator-settings-execution-preflight-error",
        title="Settings execution preflight unavailable",
        heading="Read-only settings execution preflight unavailable",
        banner="Unable to load the settings execution preflight.",
        detail=(
            "The sanitized dry-run preflight could not be rendered. "
            "Retry after checking database connectivity and runtime config. "
            "This page is not permission or machinery for going live."
        ),
    )


def render_settings_execution_preflight(
    result: SettingsExecutionPreflightResponse,
    *,
    request_type: str | None,
    decision_status: str | None,
    execution_status: str | None,
) -> str:
    generated = html_escape(format_dt(result.generated_at))
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '  <meta charset="utf-8">\n'
        '  <meta name="viewport" content="width=device-width, initial-scale=1">\n'
        "  <title>Settings execution preflight</title>\n"
        f"{OPERATOR_UI_STYLES}\n"
        "</head>\n"
        "<body>\n"
        '  <main id="operator-settings-execution-preflight" data-read-only="true" '
        'data-dry-run-only="true" data-execution-allowed="false" '
        'data-no-execution="true">\n'
        f"{_render_header(result, generated)}\n"
        f"{render_operator_nav('settings-execution-preflight')}\n"
        f"{_render_filters(request_type, decision_status, execution_status)}\n"
        f"{_render_summary(result)}\n"
        f"{_render_requests(
            result.requests,
            request_type=request_type,
            decision_status=decision_status,
            execution_status=execution_status,
        )}\n"
        f"{_render_footer(result, generated)}\n"
        "  </main>\n"
        "</body>\n"
        "</html>\n"
    )


def build_operator_settings_execution_preflight_response(
    db: Session,
    settings: Settings,
    *,
    request_type: str | None = None,
    decision_status: str | None = None,
    execution_status: str | None = None,
    service: SettingsExecutionPreflightService | None = None,
) -> HTMLResponse:
    try:
        parsed_type = parse_request_type(request_type)
        parsed_decision = parse_decision_status(decision_status)
        parsed_execution = parse_execution_status(execution_status)
        result = build_settings_execution_preflight_response(
            db,
            settings,
            request_type=parsed_type,
            decision_status=parsed_decision,
            execution_status=parsed_execution,
            service=service,
        )
        html = render_settings_execution_preflight(
            result,
            request_type=parsed_type,
            decision_status=parsed_decision,
            execution_status=parsed_execution,
        )
        return HTMLResponse(content=html, status_code=200, headers=NO_STORE_HEADERS)
    except Exception:
        logger.exception("operator_settings_execution_preflight_render_failed", read_only=True)
        return HTMLResponse(
            content=render_settings_execution_preflight_error(),
            status_code=500,
            headers=NO_STORE_HEADERS,
        )


def _parse_allowed(value: str | None, allowed: tuple[str, ...]) -> str | None:
    if value is None or not value.strip():
        return None
    cleaned = value.strip()
    if cleaned in allowed:
        return cleaned
    return None


def _render_header(result: SettingsExecutionPreflightResponse, generated: str) -> str:
    return (
        '    <header class="page-header">\n'
        "      <div>\n"
        "        <h1>Settings execution preflight</h1>\n"
        '        <p class="lede">Read-only dry-run blocker view over recorded '
        "settings-change requests. Execution remains disabled. This page is not "
        "permission or machinery for going live.</p>\n"
        "      </div>\n"
        f'      <p class="meta">Generated {generated} · overall '
        f"{html_escape(result.overall_status)} · halt "
        f"{html_escape(result.operator_halt_status)}</p>\n"
        "    </header>"
    )


def _render_filters(
    request_type: str | None,
    decision_status: str | None,
    execution_status: str | None,
) -> str:
    type_links = [
        filter_link(
            _list_href(None, decision_status, execution_status),
            "All types",
            current=request_type is None,
        )
    ]
    for name in _REQUEST_TYPES:
        type_links.append(
            filter_link(
                _list_href(name, decision_status, execution_status),
                name.replace("_", " "),
                current=request_type == name,
            )
        )
    decision_links = [
        filter_link(
            _list_href(request_type, None, execution_status),
            "All decisions",
            current=decision_status is None,
        )
    ]
    for name in _DECISION_STATUSES:
        decision_links.append(
            filter_link(
                _list_href(request_type, name, execution_status),
                name.replace("_", " "),
                current=decision_status == name,
            )
        )
    execution_links = [
        filter_link(
            _list_href(request_type, decision_status, None),
            "All execution",
            current=execution_status is None,
        )
    ]
    for name in _EXECUTION_STATUSES:
        execution_links.append(
            filter_link(
                _list_href(request_type, decision_status, name),
                name.replace("_", " "),
                current=execution_status == name,
            )
        )
    json_href = escape(SETTINGS_EXECUTION_PREFLIGHT_JSON_PATH)
    requests_href = escape(OPERATOR_SETTINGS_CHANGE_REQUESTS_PATH)
    return (
        '    <nav class="filter-nav" aria-label="Request type filters">'
        f"{' '.join(type_links)}</nav>\n"
        '    <nav class="filter-nav" aria-label="Decision status filters">'
        f"{' '.join(decision_links)}</nav>\n"
        '    <nav class="filter-nav" aria-label="Execution status filters">'
        f"{' '.join(execution_links)}\n"
        f'      <a class="nav-link nav-json" href="{json_href}">JSON preflight</a>\n'
        f'      <a class="nav-link" href="{requests_href}">Settings requests</a>\n'
        "    </nav>"
    )


def _list_href(
    request_type: str | None,
    decision_status: str | None,
    execution_status: str | None,
) -> str:
    params: list[str] = []
    if request_type:
        params.append(f"request_type={request_type}")
    if decision_status:
        params.append(f"decision_status={decision_status}")
    if execution_status:
        params.append(f"execution_status={execution_status}")
    if not params:
        return OPERATOR_SETTINGS_EXECUTION_PREFLIGHT_PATH
    return f"{OPERATOR_SETTINGS_EXECUTION_PREFLIGHT_PATH}?{'&'.join(params)}"


def _render_summary(result: SettingsExecutionPreflightResponse) -> str:
    type_items = _kv_items(result.by_request_type, empty="No request types.")
    decision_items = _kv_items(result.by_decision_status, empty="No decision statuses.")
    execution_items = _kv_items(result.by_execution_status, empty="No execution statuses.")
    return (
        '    <section class="status-strip" aria-label="Preflight counts">\n'
        f"      {metric('Overall', result.overall_status)}\n"
        f"      {metric('Requests', result.request_count)}\n"
        f"      {metric('Pending decisions', result.pending_decision_count)}\n"
        f"      {metric('Approved decisions', result.approved_decision_count)}\n"
        f"      {metric('Rejected / needs changes', result.rejected_or_needs_changes_count)}\n"
        f"      {metric('Blocked', result.blocked_count)}\n"
        f"      {metric('Executable', result.executable_count)}\n"
        f"      {metric('Dry-run only', yes_no(result.dry_run_only))}\n"
        f"      {metric('No execution', yes_no(result.no_execution))}\n"
        f"      {metric('Execution allowed', yes_no(result.execution_allowed))}\n"
        "    </section>\n"
        '    <section class="panel">\n'
        "      <h2>Dry-run gates</h2>\n"
        '      <div class="metric-grid">\n'
        f"        {metric('Outbound enabled', yes_no(result.outbound_enabled))}\n"
        f"        {metric('Live providers', yes_no(result.live_providers_enabled))}\n"
        f"        {metric('Operator halt', result.operator_halt_status)}\n"
        f"        {metric('Halt before', result.operator_halt_before)}\n"
        f"        {metric('Halt after', result.operator_halt_after)}\n"
        f"        {metric('Halt changed', yes_no(result.halt_changed))}\n"
        f"        {metric('Settings applied', yes_no(result.settings_applied))}\n"
        f"        {metric('Owner approved live', yes_no(result.owner_approved))}\n"
        f"        {metric('Executed', result.executed)}\n"
        f"        {metric('Live action', yes_no(result.live_action))}\n"
        f"        {metric('Future execution phase',
            yes_no(result.future_execution_phase_exists))}\n"
        f"        {metric('Pending packets', result.pending_owner_approval_packet_count)}\n"
        f"        {metric('Approved packets', result.approved_owner_approval_packet_count)}\n"
        "      </div>\n"
        "      <h3>Blocker codes</h3>\n"
        f"      {_render_codes(result.blocker_codes, empty='No blocker codes.')}\n"
        "      <h3>Missing approval codes</h3>\n"
        f"      {_render_codes(result.missing_approval_codes, empty='None missing.')}\n"
        "      <h3>Missing gate codes</h3>\n"
        f"      {_render_codes(result.missing_gate_codes, empty='None missing.')}\n"
        "      <h3>Missing credential variable names</h3>\n"
        f"      {_render_codes(result.missing_credential_names, empty='None missing.')}\n"
        "      <h3>Closed provider flag names</h3>\n"
        f"      {_render_codes(result.closed_provider_flag_names, empty='None closed.')}\n"
        "      <h3>By request type</h3>\n"
        f'      <ul class="kv-list">{type_items}</ul>\n'
        "      <h3>By owner decision</h3>\n"
        f'      <ul class="kv-list">{decision_items}</ul>\n'
        "      <h3>By execution status</h3>\n"
        f'      <ul class="kv-list">{execution_items}</ul>\n'
        '      <p class="hint">This page never shows secret values, environment '
        "values, API keys, tokens, message bodies, emails, phones, evidence "
        "snippets, or unsafe error text. An approved decision is not permission "
        "to apply the setting.</p>\n"
        "    </section>"
    )


def _kv_items(counts: dict[str, int], *, empty: str) -> str:
    items = "".join(
        f"<li><span>{titleize(key)}</span><strong>{html_escape(count)}</strong></li>"
        for key, count in sorted(counts.items())
    )
    return items or f'<li class="empty">{escape(empty)}</li>'


def _render_requests(
    requests: list[SettingsExecutionPreflightItemResponse],
    *,
    request_type: str | None,
    decision_status: str | None,
    execution_status: str | None,
) -> str:
    filtered = bool(request_type or decision_status or execution_status)
    if not requests:
        if filtered:
            body = (
                '<p class="empty-state" id="empty-settings-execution-preflight">'
                "No settings-change requests match the current filters. "
                "This page does not apply settings or execute anything.</p>"
            )
        else:
            body = (
                '<p class="empty-state" id="empty-settings-execution-preflight">'
                "No settings-change requests to simulate. This dry-run view "
                "does not create requests, apply settings, or execute live actions.</p>"
            )
        return (
            '    <section class="panel">\n'
            "      <h2>Simulated requests</h2>\n"
            f"      {body}\n"
            "    </section>"
        )
    rows = "".join(_request_row(item) for item in requests)
    return (
        '    <section class="panel">\n'
        "      <h2>Simulated requests</h2>\n"
        '      <table class="dense"><thead><tr>'
        "<th>Type</th><th>Request</th><th>Decision</th><th>Execution</th>"
        "<th>Setting names</th><th>Desired</th><th>Blockers</th><th>Flags</th>"
        f"</tr></thead><tbody>{rows}</tbody></table>\n"
        "    </section>"
    )


def _request_row(item: SettingsExecutionPreflightItemResponse) -> str:
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
        f'<tr class="{_execution_class(item.execution_status)}">'
        f"<td>{titleize(item.request_type)}</td>"
        f'<td class="mono"><a class="row-link" href="{escape(href)}">'
        f"{html_escape(short_id(item.request_id))}</a></td>"
        f"<td>{html_escape(item.decision_status)}</td>"
        f"<td>{html_escape(item.execution_status)}</td>"
        f'<td class="mono">{html_escape(names)}</td>'
        f"<td>{html_escape(_desired_label(item))}</td>"
        f'<td class="mono">{html_escape(blockers)}</td>'
        f"<td>{html_escape(flags)}</td>"
        "</tr>"
    )


def _desired_label(item: SettingsExecutionPreflightItemResponse) -> str:
    if item.desired_status:
        return item.desired_status
    if item.desired_boolean is True:
        return "true"
    if item.desired_boolean is False:
        return "false"
    return "—"


def _execution_class(status: str) -> str:
    match status:
        case (
            SettingsExecutionPreflightStatus.BLOCKED.value
            | SettingsExecutionPreflightStatus.DECISION_NOT_APPROVED.value
            | SettingsExecutionPreflightStatus.MISSING_OWNER_PACKET_DECISION.value
            | SettingsExecutionPreflightStatus.MISSING_EXPLICIT_OWNER_APPROVAL.value
            | SettingsExecutionPreflightStatus.EXECUTION_GATES_CLOSED.value
            | SettingsExecutionPreflightStatus.DRY_RUN_BLOCKED.value
        ):
            return "severity-blocked"
        case SettingsExecutionPreflightStatus.PENDING_DECISION.value:
            return "severity-warning"
        case _:
            return _unreachable_status(status)


def _render_codes(codes: list[str], *, empty: str) -> str:
    unique = [code for code in dict.fromkeys(codes) if code]
    if not unique:
        return f'<p class="empty-state">{escape(empty)}</p>'
    rows = "".join(f'<li class="mono">{html_escape(code)}</li>' for code in unique)
    return f'<ul class="plain">{rows}</ul>'


def _render_footer(result: SettingsExecutionPreflightResponse, generated: str) -> str:
    return (
        '    <footer class="footnote" id="side-effects">\n'
        f"      <p>Generated {generated}. Record-only={yes_no(result.record_only)}. "
        f"Dry-run only={yes_no(result.dry_run_only)}. "
        f"No execution={yes_no(result.no_execution)}. "
        f"Executed={html_escape(result.executed)}. "
        f"Settings applied={yes_no(result.settings_applied)}. "
        f"Halt changed={yes_no(result.halt_changed)}. "
        f"Owner approved={yes_no(result.owner_approved)}. "
        f"Live action={yes_no(result.live_action)}. "
        f"Execution allowed={yes_no(result.execution_allowed)}. "
        f"Future execution phase exists="
        f"{yes_no(result.future_execution_phase_exists)}. "
        "There are no apply, execute, lift-halt, enable-outbound, provider, "
        "deploy, campaign, booking, call, publish, or spend controls on this "
        "page. This is a read-only blocker view, not permission to go live.</p>\n"
        "    </footer>"
    )


def _unreachable_status(value: str) -> Never:
    raise RuntimeError(f"unhandled settings execution preflight status: {value!r}")
